"""What a visit to the bar done gives (GLOSSARY.md「光顾」「抽奖」「好感度」): the day's first
done, by the Beijing day she came in on, gives a draw chance, held to the most kept
(`affinity.MAX_DRAWS`), and raises her affinity by how well each drink was served, averaged
(`affinity.SERVED_STEPS`), in a cooldown too, out of it at the thaw line, beyond the day's
limit; told of as the visit is done, and to the navigation as a reward is, but as no
conversation event. Later visits that day give nothing, nor does one left before it is done,
nor any while affinity and gifts are off. Reading the bar tells whether there is a reward
today.

Driven through the backend's external API; her affinity read from the database, as only its
tier is shown. Mano is the only character, ordering as `test_bar_visit` has her."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings
from tests.conftest import CharacterConfig, ClientFactory
from tests.fakes import FAKE_JUDGE, FakeClock, FakeLLM, FakeRandom
from tests.test_bar_draws import visit_rows
from tests.test_bar_visit import (
    COMING_IN,
    PARTING,
    coming_in,
    enter,
    events,
    her,
    mano_alone,
    mixed,
    reacting,
    serve,
)
from tests.test_affinity import keep, status
from tests.test_delete_account import user_id
from tests.test_gift_draws import state
from tests.test_schedule_job_done import affinity, count


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With the judge model, and affinity and gifts on in `.env`."""
    return replace(settings, judge=FAKE_JUDGE, affinity_and_gifts=True)


@pytest.fixture
def characters(tmp_path: Path) -> CharacterConfig:
    return mano_alone(tmp_path / "characters")


ONE_SUGAR_RUSH = (0, 0, 0, 0, 0)
"""Her first reason and topic, one drink, and of the drinks she loves the first, Sugar Rush;
how she orders it is the next number."""

BY_NAME, BY_NAME_BIG = 0, 40
"""Among the ways a novice orders Sugar Rush."""


def rewards(database: Path) -> list[tuple[str, int]]:
    """Each reward the producer was given, by its key, and its draw chances."""
    with sqlite3.connect(database) as db:
        return db.execute(
            "SELECT key, draws FROM gift_rewards WHERE user_id = ? ORDER BY key",
            (user_id(database, "producer"),),
        ).fetchall()


async def reward_today(client: httpx.AsyncClient) -> bool:
    res = await client.get("/api/bar")
    assert res.status_code == 200, res.text
    return res.json()["reward_today"]


async def done(client: httpx.AsyncClient, drink: dict) -> dict:
    """A visit of one drink, `drink` served her: the event it is done with."""
    visit_id = (await enter(client))[0]["visit_id"]
    last = events(await serve(client, visit_id, drink))[-1]
    assert last["type"] == "done", last
    return last


async def test_the_days_first_visit_done_gives_a_draw_and_raises_her_told_of_as_it_is_done(
    make_client: ClientFactory, settings: Settings
):
    database = settings.database_path
    clock = FakeClock()
    client = make_client(
        FakeLLM(COMING_IN, PARTING), clock=clock,
        random=FakeRandom(*ONE_SUGAR_RUSH, BY_NAME_BIG, 0),
    )
    before = await state(client)
    events_before = count(database, "conversation_events")

    finished = await done(client, mixed("sugar-rush", big=True))
    after = await state(client)

    assert finished == {"type": "done", "rewarded": {"draws": 1, "affinity_up": True}}
    assert (before["draws"], after["draws"]) == (2, 3)
    assert affinity(database) == 51.0  # served best, at SERVED_SCALE
    assert rewards(database) == [("bar:2026-09-25", 1)]
    assert after["rewarded_at"] == clock.now.isoformat()  # the navigation's dot lights
    assert count(database, "conversation_events") == events_before
    [row] = visit_rows(database)
    assert row["rewarded"] == 1


UNNAMED = [her("いつもと違うのを。", "来杯和平时不一样的。", order=True)]
"""Her coming in and ordering without naming a drink."""


@pytest.mark.parametrize(
    ("ordered", "said", "drink", "raised_to"),
    [
        pytest.param(
            (*ONE_SUGAR_RUSH, BY_NAME_BIG), COMING_IN, mixed("sugar-rush"), 50.8,
            id="right, a best there",
        ),
        pytest.param(
            (*ONE_SUGAR_RUSH, BY_NAME), COMING_IN, mixed("sugar-rush"), 51.0,
            id="right by name, no best",
        ),
        pytest.param(
            (*ONE_SUGAR_RUSH, BY_NAME), COMING_IN, mixed("sparkle-star"), 50.2, id="wrong"
        ),
        # Of the drinks she likes, Sparkle Star, by its flavor: Sugar Rush would be best.
        pytest.param(
            (0, 0, 0, 45, 0, 47), UNNAMED, mixed("sparkle-star"), 50.8,
            id="right by flavor, a best there",
        ),
        # Of any, Brandtini, by its kind: none she loves is of it.
        pytest.param(
            (0, 0, 0, 80, 11, 59), UNNAMED, mixed("brandtini"), 51.0,
            id="right by kind, no best",
        ),
    ],
)
async def test_how_much_she_is_raised_is_by_how_well_it_was_served(
    make_client: ClientFactory,
    settings: Settings,
    ordered: tuple[int, ...],
    said: list[str],
    drink: dict,
    raised_to: float,
):
    client = make_client(FakeLLM(said, PARTING), random=FakeRandom(*ordered, 0))

    finished = await done(client, drink)

    assert finished["rewarded"] == {"draws": 1, "affinity_up": True}
    assert affinity(settings.database_path) == pytest.approx(raised_to)


async def test_she_is_raised_by_the_average_of_her_drinks(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(COMING_IN, reacting("sparkle-star"), PARTING)
    # Two drinks, Sugar Rush by name; then Sparkle Star by name, served wrong.
    client = make_client(llm, random=FakeRandom(0, 0, 20, 0, 0, BY_NAME, 0, 0, 0, BY_NAME, 0))

    visit_id = (await enter(client))[0]["visit_id"]
    await serve(client, visit_id, mixed("sugar-rush"))
    await serve(client, visit_id, mixed("fluffy-dream"))

    assert affinity(settings.database_path) == pytest.approx(50.6)


async def test_with_the_most_draws_kept_none_is_given_nor_recorded_but_she_is_raised(
    make_client: ClientFactory, settings: Settings
):
    database = settings.database_path
    client = make_client(
        FakeLLM(COMING_IN, PARTING), random=FakeRandom(*ONE_SUGAR_RUSH, BY_NAME_BIG, 0)
    )
    await state(client)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE gift_balances SET draws = 7")
    db.close()

    finished = await done(client, mixed("sugar-rush", big=True))
    after = await state(client)

    assert finished["rewarded"] == {"draws": 0, "affinity_up": True}
    assert after["draws"] == 7
    assert rewards(database) == []
    assert after["rewarded_at"] is None
    assert affinity(database) == 51.0


@pytest.mark.parametrize(
    ("cooled_at", "raised_to", "cooling"), [(9.6, 10.6, False), (0.0, 1.0, True)]
)
async def test_in_a_cooldown_she_is_raised_the_same_out_of_it_at_the_thaw_line(
    make_client: ClientFactory,
    settings: Settings,
    cooled_at: float,
    raised_to: float,
    cooling: bool,
):
    database = settings.database_path
    clock = FakeClock()
    client = make_client(
        FakeLLM(COMING_IN, PARTING), clock=clock,
        random=FakeRandom(*ONE_SUGAR_RUSH, BY_NAME_BIG, 0),
    )
    keep(database, "producer", cooled_at, clock.now, cooling=True)

    finished = await done(client, mixed("sugar-rush", big=True))

    assert finished["rewarded"] == {"draws": 1, "affinity_up": True}
    assert affinity(database) == pytest.approx(raised_to)
    assert ((await status(client)).json()["cooldown_until"] is not None) == cooling


async def test_only_the_days_first_visit_done_gives_a_draw_but_those_after_still_raise_her(
    make_client: ClientFactory, settings: Settings
):
    database = settings.database_path
    llm = FakeLLM(COMING_IN, COMING_IN, PARTING, coming_in("sparkle-star"), PARTING)
    client = make_client(llm, clock=FakeClock(), random=FakeRandom(
        *ONE_SUGAR_RUSH, BY_NAME,  # left
        *ONE_SUGAR_RUSH, BY_NAME_BIG, 0,  # done
        # Anyone, then her first reason and topic, one drink, the first she likes but for what
        # she wanted the last time, by name.
        0, 0, 0, 0, 0, 0, BY_NAME, 0,
    ))
    rewarding_at_first = await reward_today(client)

    visit_id = (await enter(client))[0]["visit_id"]
    assert (await client.delete(f"/api/bar/visits/{visit_id}")).status_code == 204
    after_leaving = (await state(client))["draws"], affinity(database), await reward_today(client)
    first = await done(client, mixed("sugar-rush", big=True))
    after_first = (await state(client))["draws"], affinity(database), await reward_today(client)
    second = await done(client, mixed("sparkle-star"))

    assert rewarding_at_first is True
    assert after_leaving == (2, 50.0, True)
    assert first["rewarded"] == {"draws": 1, "affinity_up": True}
    assert after_first == (3, 51.0, False)
    assert second["rewarded"] == {"draws": 0, "affinity_up": True}
    assert ((await state(client))["draws"], affinity(database)) == (3, 52.0)
    assert rewards(database) == [("bar:2026-09-25", 1)]
    assert [row["rewarded"] for row in visit_rows(database)] == [1, 1]


async def test_a_visit_is_of_the_day_she_came_in_on(
    make_client: ClientFactory, settings: Settings
):
    database = settings.database_path
    clock = FakeClock()
    client = make_client(
        FakeLLM(COMING_IN, PARTING), clock=clock,
        random=FakeRandom(*ONE_SUGAR_RUSH, BY_NAME_BIG, 0),
    )
    clock.advance(hours=3, minutes=50)  # 23:50 in Shanghai
    before = (await state(client))["draws"]

    visit_id = (await enter(client))[0]["visit_id"]
    clock.advance(minutes=20)  # the next day
    finished = events(await serve(client, visit_id, mixed("sugar-rush", big=True)))[-1]

    assert finished["rewarded"] == {"draws": 1, "affinity_up": True}
    assert (before, (await state(client))["draws"]) == (2, 5)  # the new day's, then the visit's
    assert rewards(database) == [("bar:2026-09-25", 1)]
    assert await reward_today(client) is True  # none done yet that came in on the new day


async def test_with_affinity_and_gifts_off_a_visit_done_gives_nothing(
    make_client: ClientFactory, settings: Settings
):
    database = settings.database_path
    client = make_client(
        FakeLLM(COMING_IN, PARTING), settings=replace(settings, affinity_and_gifts=False),
        random=FakeRandom(*ONE_SUGAR_RUSH, BY_NAME_BIG, 0),
    )
    rewarding = await reward_today(client)

    finished = await done(client, mixed("sugar-rush", big=True))

    assert rewarding is False
    assert finished["rewarded"] is None
    for table in ("affinities", "gift_balances", "gift_rewards"):
        assert count(database, table) == 0, table
    [row] = visit_rows(database)
    assert row["rewarded"] == 0
