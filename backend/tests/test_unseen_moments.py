"""Unseen moments (GLOSSARY.md「朋友圈」): whether something has shown on the user's moments
since they last opened them, a moment of hers or her reply to his comment, which lights the
dot on 「朋友圈」; the likes and comments of her circle, as they show, do not. Reading the
timeline, on any device, opens them. One who never has is counted from when they were first
planned for, not from each day's planning.

Driven as `test_moments.py` drives moments (`SteadyRandom(0)`), with the world and the
characters of `test_moment_circle.py`, so that her circle likes 5 minutes after she posts and
comments 15 minutes after."""

import sqlite3
from datetime import timedelta

import httpx

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import FakeLLM
from tests.test_moment_circle import (
    LIKED_AND_COMMENTED,
    characters,  # noqa: F401  Mano, her unit, and Kogane's
    settings,  # noqa: F401  moments on in `.env`
)
from tests.test_moment_producer import REPLIED, comment
from tests.test_moments import SEVEN, START, talked, tick, timeline

UNSEEN = "/api/moments/unseen"


async def unseen(client: httpx.AsyncClient) -> bool:
    res = await client.get(UNSEEN)
    assert res.status_code == 200, res.text
    return res.json()["unseen"]


async def test_a_moment_of_hers_shown_is_unseen_till_the_timeline_is_read(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, _ = await talked(make_client, LIKED_AND_COMMENTED)
    await tick(client, clock, START)
    clock.now = SEVEN - timedelta(seconds=1)  # planned, not yet posted
    not_yet = await unseen(client)

    await tick(client, clock, SEVEN)
    shown = await unseen(client)
    await timeline(client)

    assert (not_yet, shown, await unseen(client)) == (False, True, False)


async def test_her_circles_likes_and_comments_as_they_show_are_not_unseen(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, _ = await talked(make_client, LIKED_AND_COMMENTED)
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    await timeline(client)

    clock.now = SEVEN + timedelta(minutes=20)
    after = await unseen(client)

    [moment] = await timeline(client)
    assert (len(moment["likes"]), len(moment["comments"])) == (2, 2)  # shown meanwhile
    assert after is False


async def test_her_reply_to_his_comment_shown_is_unseen_till_the_timeline_is_read(
    make_client: ClientFactory, settings: Settings
):
    """Trust, affinity off: she replies 30 minutes after he comments."""
    client, _, clock, _ = await talked(make_client, LIKED_AND_COMMENTED, REPLIED)
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    [moment] = await timeline(client)
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment["id"])).status_code == 201
    await timeline(client)

    await tick(client, clock, SEVEN + timedelta(minutes=33) - timedelta(seconds=1))
    before = await unseen(client)
    await tick(client, clock, SEVEN + timedelta(minutes=33))
    shown = await unseen(client)
    [moment] = await timeline(client)

    assert moment["reply"] is not None
    assert (before, shown, await unseen(client)) == (False, True, False)


async def test_the_timeline_read_on_another_device_has_it_seen(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, _ = await talked(make_client, LIKED_AND_COMMENTED)
    elsewhere = make_client(FakeLLM(), clock=clock)  # the same user, signed in again
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    assert (await unseen(client), await unseen(elsewhere)) == (True, True)

    await timeline(elsewhere)

    assert await unseen(client) is False


async def test_one_who_never_opened_them_is_counted_from_when_first_planned_for(
    make_client: ClientFactory, settings: Settings
):
    """A moment shown before he was first planned for is not new; one shown after it is,
    however many days later he is planned for again."""
    client, _, clock, _ = await talked(make_client, LIKED_AND_COMMENTED)
    await tick(client, clock, START)
    database = settings.database_path
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO moments (user_id, character_id, ja, zh, day, posted_at)"
            " VALUES ('producer', 'mano', 'あ', '啊', '2026-10-18', ?)",
            ((START - timedelta(minutes=1)).isoformat(),),
        )
    before = await unseen(client)

    await tick(client, clock, SEVEN)
    await tick(client, clock, START + timedelta(days=1))  # still in touch: planned again

    assert (before, await unseen(client)) == (False, True)

