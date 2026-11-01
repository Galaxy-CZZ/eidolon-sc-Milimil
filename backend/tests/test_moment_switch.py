"""The user's own switch for moments (GLOSSARY.md「朋友圈」): on by default, kept on the server
so that it holds on every device; the account says it where the deployer turns moments on,
nothing where not, and it cannot be set then. One who switches it off has nothing planned nor
posted to them, the moments planned passed over as their times come, no reply to their
comments, and their moments refused them (409), kept as they are, to go as ever; switched on
again, what was planned of the day and not yet due is posted, and one not yet planned for is
from what is left of the day.

Driven as `test_moments.py` drives moments (`SteadyRandom(0)`)."""

from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from eidolon.config import Settings
from eidolon.moment_prompt import COMMENTED
from tests.conftest import ClientFactory
from tests.test_moment_producer import REPLIED, comment, posted, reply_records
from tests.test_moments import POST, SEVEN, START, moment_records, talked, tick, timeline

SWITCH = "/api/account/moments"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With moments on in `.env`."""
    return replace(settings, moments=True)


async def switched_on(client: httpx.AsyncClient) -> bool | None:
    res = await client.get("/api/account")
    assert res.status_code == 200
    return res.json()["moments"]


async def switch(client: httpx.AsyncClient, on: bool) -> None:
    res = await client.put(SWITCH, json={"on": on})
    assert res.status_code == 204, res.text


async def test_the_account_says_nothing_where_the_deployer_has_them_off_else_the_users_switch(
    make_client: ClientFactory, settings: Settings
):
    off, *_ = await talked(make_client, settings=replace(settings, moments=False))
    on, *_ = await talked(make_client, settings=settings)
    by_default = await switched_on(on)

    await switch(on, False)

    assert (await switched_on(off), by_default, await switched_on(on)) == (None, True, False)


async def test_it_cannot_be_set_where_the_deployer_has_them_off(
    make_client: ClientFactory, settings: Settings
):
    off, *_ = await talked(make_client, settings=replace(settings, moments=False))

    refused = (await off.put(SWITCH, json={"on": False})).status_code

    assert refused == 409
    assert (await switched_on(off)) is None


async def test_switched_off_nothing_is_planned_nor_posted_and_on_again_from_what_is_left_of_the_day(
    make_client: ClientFactory, settings: Settings
):
    """Off over the first tick of the day; on again by 09:00, as the morning is over: at
    lunch, from 12:00."""
    client, llm, clock, _ = await talked(make_client, POST)

    await switch(client, False)
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    while_off = len(llm.prompts)
    await switch(client, True)
    came = []
    for at in (SEVEN + timedelta(hours=2), SEVEN + timedelta(hours=4, minutes=59),
               SEVEN + timedelta(hours=5)):
        await tick(client, clock, at)
        came.append(len(await timeline(client)))

    assert while_off == 1  # the turn's only
    assert came == [0, 0, 1]


async def test_one_planned_whose_time_comes_while_off_is_passed_over_unrecorded(
    make_client: ClientFactory, settings: Settings
):
    client, llm, clock, _ = await talked(make_client, POST)
    await tick(client, clock, START)

    await switch(client, False)
    await tick(client, clock, SEVEN)
    await switch(client, True)
    await tick(client, clock, SEVEN + timedelta(hours=5))

    assert len(llm.prompts) == 1  # the turn's only: planned already that day
    assert moment_records(settings.database_path) == []


async def test_one_planned_and_switched_off_and_on_again_before_its_time_posts_at_it(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, _ = await talked(make_client, POST)
    await tick(client, clock, START)

    await switch(client, False)
    await tick(client, clock, START + timedelta(hours=1))
    await switch(client, True)
    await tick(client, clock, SEVEN)

    assert len(await timeline(client)) == 1


async def test_switched_off_his_moments_are_refused_him_and_kept_as_they_are(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, moment = await posted(make_client)
    kept = await timeline(client)

    await switch(client, False)
    refused = [
        (await client.get("/api/moments")).status_code,
        (await client.get(f"/api/moments/{moment}/image")).status_code,
        (await client.put(f"/api/moments/{moment}/like")).status_code,
        (await client.delete(f"/api/moments/{moment}/like")).status_code,
        (await comment(client, moment)).status_code,
        (await client.delete(f"/api/moments/{moment}/comment")).status_code,
        (await client.get("/api/moments/unseen")).status_code,
    ]
    await switch(client, True)

    assert refused == [409] * 7
    assert await timeline(client) == kept


async def test_switched_off_as_her_time_comes_she_does_not_reply_for_good(
    make_client: ClientFactory, settings: Settings
):
    client, llm, clock, moment = await posted(make_client, REPLIED)
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment)).status_code == 201

    await switch(client, False)
    await tick(client, clock, SEVEN + timedelta(minutes=33))
    await switch(client, True)
    await tick(client, clock, SEVEN + timedelta(minutes=40))

    assert all(m["reply"] is None for m in await timeline(client))
    assert not any(p[-1].content.startswith(COMMENTED) for p in llm.prompts)
    assert reply_records(settings.database_path) == []
