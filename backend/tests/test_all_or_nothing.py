"""All or nothing (ADR-0028): a turn, a gift given and a reset card used are each kept in one
transaction, with what they change of her affinity and what they count towards, the
achievements, and the letters what they unlock is the occasion for. Should any of it fail
part-way, nothing of it is left: the turn fails with no record and her affinity as it was,
the gift and the card are still the user's. Driven
through the backend's external API, the failure made in the database itself."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import FAKE_JUDGE, FakeClock, FakeLLM, FakeServiceClients, level
from tests.test_achievements import goals, hers, turns, unlocked, with_goals
from tests.test_affinity import keep, status
from tests.test_conversation_events import record
from tests.test_gift_draws import state
from tests.test_gift_giving import CAKE, backpack, catalog, draw_them, give, holding  # noqa: F401
from tests.test_reset_cards import USE, holding_cards, kept
from tests.test_text_turn import send_turn, start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With the judge model, and affinity and gifts and letters on in `.env`."""
    return replace(settings, judge=FAKE_JUDGE, affinity_and_gifts=True, letters=True)


def failing(database: Path, table: str, on: str = "INSERT") -> None:
    """Have every `on` of `table` fail from now on, as if writing it went wrong."""
    with sqlite3.connect(database) as db:
        db.execute(
            f"CREATE TRIGGER failing BEFORE {on} ON {table}"
            " BEGIN SELECT RAISE(ABORT, 'failing on purpose'); END"
        )


async def test_a_turn_whose_achievements_fail_to_be_kept_fails_leaving_nothing(
    make_client: ClientFactory, settings: Settings
):
    clients = FakeServiceClients()
    clients.judge.judgings = [level(0)]  # hurts her
    client = make_client(FakeLLM(REPLY), clients=clients, clock=FakeClock())
    await state(client)
    conversation = await start_conversation(client)
    failing(settings.database_path, "achievement_progress")

    events = await send_turn(client, conversation, "随便你")

    assert events[-1]["type"] == "error"
    assert await record(client, conversation) == []
    assert (await status(client)).json() == {"tier": "trust", "cooldown_until": None}
    assert (await state(client))["draws"] == 2


async def test_a_gift_whose_achievements_fail_to_be_kept_is_not_given(
    make_client: ClientFactory, settings: Settings
):
    clock = FakeClock()
    client = holding(make_client, clock, CAKE)
    await draw_them(client, clock, 1)
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 25, clock.now)
    failing(settings.database_path, "achievement_progress")

    with pytest.raises(sqlite3.IntegrityError):
        await give(client, "cake")

    assert await backpack(client) == {"cake": 1}
    assert kept(settings.database_path, "mano") == (25, False)
    assert await record(client, conversation) == []


async def test_a_reset_card_that_fails_to_bring_her_back_is_still_the_users(
    make_client: ClientFactory, settings: Settings
):
    clock = FakeClock()
    client = await holding_cards(make_client, clock, 1)
    keep(settings.database_path, "producer", 25, clock.now)
    failing(settings.database_path, "affinities", on="UPDATE")

    with pytest.raises(sqlite3.IntegrityError):
        await client.post(USE)

    assert (await state(client))["reset_cards"] == 1
    assert kept(settings.database_path, "mano") == (25, False)


async def test_a_gift_completing_her_whose_letter_fails_to_be_kept_is_not_given(
    make_client: ClientFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    clock = FakeClock()
    client = holding(make_client, clock, CAKE)
    await draw_them(client, clock, 1)
    with_goals(monkeypatch, "PER_CHARACTER", turns=goals(1), gifts=goals(1))
    await turns(client, await start_conversation(client), 1)
    before = await state(client)
    failing(settings.database_path, "letters_due")

    with pytest.raises(sqlite3.IntegrityError):
        await give(client, "cake")

    assert await backpack(client) == {"cake": 1}
    after = await state(client)
    assert (after["draws"], after["reset_cards"]) == (before["draws"], before["reset_cards"])
    assert unlocked(await hers(client), "gifts") == []
