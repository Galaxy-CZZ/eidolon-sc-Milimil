"""The dashboard's「朋友圈」section (GLOSSARY.md「看板」「朋友圈」): over the dashboard's range,
how many moments were posted, how many failed, how many of the producer's comments she replied
to, and how many of those failed, a reply rejected as his comment was deleted no failure; and,
whatever the range, the share of the moments shown within the last 30 days the producer likes
or has commented on, of all users together. Not by character; and where the deployer has
moments off and none were recorded in the range, there is no section.

Driven as `test_moment_producer` drives moments: Mano's moment posted at `SEVEN`."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings
from eidolon.llm import LLMError
from tests.conftest import ClientFactory
from tests.fakes import FakeIdentityProvider
from tests.test_activity_records import dashboard
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_moment_producer import MOMENTS, NOWHERE, REPLIED, comment, copied, posted
from tests.test_moments import SEVEN, START, talked, tick
from tests.test_reach_outs import backend_of

FAILS = LLMError("模型返回 503: overloaded")


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With an admin, and moments on in `.env`."""
    return replace(settings, moments=True, admins=frozenset({ADMIN}))


async def section(
    client: httpx.AsyncClient, github: FakeIdentityProvider, range: str = "24h"
) -> dict | None:
    async with admin_beside(client, github) as admin:
        return (await dashboard(admin, range))["moments"]


async def test_it_counts_those_posted_and_failed_and_the_replies_and_failed_but_not_rejected(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """Three of his comments: her reply to the first fails, to the second is made, to the third
    rejected; the next day her moment fails."""
    writing = asyncio.Event()
    client, llm, clock, first = await posted(
        make_client, FAILS, REPLIED, [writing, *REPLIED], FAILS,
    )
    database = settings.database_path
    moments = [first, copied(database, first, SEVEN), copied(database, first, SEVEN)]
    for at, moment in enumerate(moments, start=3):
        clock.now = SEVEN + timedelta(minutes=at)
        assert (await comment(client, moment)).status_code == 201
    clock.now = SEVEN + timedelta(minutes=35)
    replying = asyncio.create_task(backend_of(client).moments.run_due())
    while len(llm.prompts) < 5:
        await asyncio.sleep(0)
    assert (await client.delete(f"/api/moments/{moments[2]}/comment")).status_code == 204
    writing.set()
    await replying
    await tick(client, clock, START + timedelta(days=1))
    await tick(client, clock, SEVEN + timedelta(days=1))

    shown = await section(client, github, "7d")

    assert len(llm.prompts) == 6
    assert shown == {
        "posted": 1, "posts_failed": 1, "replied": 1, "replies_failed": 1,
        "liked_or_commented_share": pytest.approx(2 / 3),
    }


def liked(database: Path, moment_id: int) -> None:
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO moment_likes (moment_id) VALUES (?)", (moment_id,))


def anothers(database: Path, moment_id: int) -> int:
    """A copy of the moment, as another user's (the admin's); its identifier."""
    with sqlite3.connect(database) as db:
        copy = db.execute(
            "INSERT INTO moments (user_id, character_id, ja, zh, day, posted_at)"
            " SELECT u.id, m.character_id, 'あ', '啊', m.day, m.posted_at FROM moments m, users u"
            " WHERE m.id = ? AND u.id != m.user_id",
            (moment_id,),
        ).lastrowid
    assert copy is not None
    return copy


async def test_the_share_liked_or_commented_on_is_of_those_shown_within_30_days_whatever_the_range(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """Of four shown, he likes one, comments on another, and the admin likes their own; one
    shown 30 days ago and one not shown yet he likes, neither counted."""
    client, _, clock, first = await posted(make_client)
    database = settings.database_path
    copied(database, first, SEVEN)  # neither liked nor commented on
    commented = copied(database, first, SEVEN)
    gone = copied(database, first, SEVEN - timedelta(days=30))
    later = copied(database, first, SEVEN + timedelta(hours=1))
    none_yet = await section(client, github)
    elsewhere = anothers(database, first)
    for moment in (gone, later, elsewhere):
        liked(database, moment)
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await client.put(f"/api/moments/{first}/like")).status_code == 204
    assert (await comment(client, commented)).status_code == 201

    shown = [await section(client, github, range) for range in ("24h", "90d")]

    assert none_yet is not None and none_yet["liked_or_commented_share"] == 0
    assert [s and s["liked_or_commented_share"] for s in shown] == [0.75, 0.75]


async def test_with_moments_off_and_none_in_the_range_there_is_no_section(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client, _, clock, _ = await talked(make_client, NOWHERE)
    on_and_none = await section(client, github)
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    async with admin_beside(client, github) as admin:
        res = await admin.put(MOMENTS, json={"enabled": False, "per_day": 3})
        assert res.status_code == 200, res.text
        off_with_one = (await dashboard(admin))["moments"]
        clock.advance(hours=25)  # out of the last 24 hours
        off_and_none = (await dashboard(admin))["moments"]

    assert on_and_none == {
        "posted": 0, "posts_failed": 0, "replied": 0, "replies_failed": 0,
        "liked_or_commented_share": None,
    }
    assert off_with_one == {
        "posted": 1, "posts_failed": 0, "replied": 0, "replies_failed": 0,
        "liked_or_commented_share": 0,
    }
    assert off_and_none is None


async def test_what_they_cost_is_in_the_services_they_called(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """The turn a day before, out of the last 24 hours: the moment and her reply alone."""
    client, llm, clock, moment = await posted(make_client, REPLIED, at=START - timedelta(days=1))
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment)).status_code == 201
    await tick(client, clock, SEVEN + timedelta(minutes=33))
    async with admin_beside(client, github) as admin:
        board = await dashboard(admin)

    assert len(llm.prompts) == 3
    assert [(r["service"], r["calls"]) for r in board["cost"]["rows"]] == [("chat_llm", 2)]
