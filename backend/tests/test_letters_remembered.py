"""She remembers the letters she wrote (GLOSSARY.md「信」): typing, in a call and reaching out,
what changes from turn to turn tells her of the latest `EARLIER` she wrote the producer, each
with its day, its occasions and what it says, without delivery cues; none she wrote others,
nor one deleted; no section without any. What every turn opens with stays as it was, for a
service to cache it (ADR-0020).

Letters are written as `test_letters.py` writes them, or set in the database directly where
several are wanted on days of the test's choosing."""

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from eidolon.config import Settings
from eidolon.letter_prompt import EARLIER, WRITE
from tests.conftest import ClientFactory
from tests.fakes import FakeLLM, FakeRandom, context_of
from tests.test_concurrent_calls import another_user
from tests.test_call_turns import MANO_REPLY, CallUnderTest, spoken
from tests.test_dynamic_context import shape
from tests.test_letters import REPLY, close_with_mano, letters, written
from tests.test_letters import settings  # noqa: F401
from tests.test_reach_outs import MIDDLE, REACH_OUT, backend_of, last_contact, talked
from tests.test_text_turn import send_turn, start_conversation

HEADING = "# 你写给制作人的信"
FIRST_CLOSE = (
    "## 2026年9月25日（第一次和他更近了一步）\nプロデューサーさんへ\n"
    "いつもありがとうございます。\nこれからもよろしくお願いします。"
)
"""The letter `test_letters.LETTER`, written on her first reaching close, as she is told of it."""


def wrote(
    database: Path, character: str, day: str, salutation: str, to: str = "producer"
) -> None:
    """Have the character have written the user named `to` a letter on `day`, on her
    birthday, opening with `salutation`, its one paragraph `……`."""
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO letters (user_id, character_id, occasions, day, written_at,"
            " salutation, paragraphs)"
            " VALUES ((SELECT id FROM users WHERE name = ?), ?, ?, ?, ?, ?, ?)",
            (
                to, character, json.dumps(["her_birthday"]), day, f"{day}T01:00:00+00:00",
                salutation, json.dumps([{"ja": "[softly] ……", "zh": "……"}]),
            ),
        )


async def test_typing_she_is_told_of_the_letter_she_wrote_where_what_changes_each_turn_is(
    make_client: ClientFactory, settings: Settings
):
    client, llm, _, conversation = await close_with_mano(
        make_client, settings, written(), REPLY
    )
    await backend_of(client).letters.run_due()

    await send_turn(client, conversation, "信收到了")

    turns = [p for p in llm.prompts if p[-1].content != WRITE]
    before, after = turns[-2], turns[-1]
    assert HEADING not in context_of(before)
    told = context_of(after)
    assert f"{HEADING}\n" in told and FIRST_CLOSE in told
    assert "[smiling]" not in told and "[softly]" not in told
    opening = shape(before[:-2])
    assert shape(after[: len(opening)]) == opening


async def test_in_a_call_she_is_told_of_it(make_client: ClientFactory, settings: Settings):
    client, _, _, conversation = await close_with_mano(make_client, settings, written())
    await backend_of(client).letters.run_due()
    call = await CallUnderTest.of(settings, client, conversation)
    call_llm = FakeLLM(MANO_REPLY)

    await call.run(call_llm, [spoken("信收到了")])

    assert FIRST_CLOSE in context_of(call_llm.prompts[-1])


async def test_reaching_out_she_is_told_of_it(make_client: ClientFactory, settings: Settings):
    reaching_out = replace(settings, reach_outs=True)
    client, llm, clock, conversation = await talked(
        make_client, REACH_OUT, settings=reaching_out, random=FakeRandom(MIDDLE)
    )
    database = settings.database_path
    wrote(database, "mano", "2026-04-25", "[happily] プロデューサーさんへ")
    last_contact(database, conversation, clock.now - timedelta(hours=28))

    await backend_of(client).reach_outs.run_due()

    assert "## 2026年4月25日（你自己的生日）\nプロデューサーさんへ\n……" in context_of(
        llm.prompts[-1]
    )


async def test_only_her_latest_to_them_she_has_not_deleted_the_earliest_first(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(REPLY)
    client = make_client(llm)
    conversation = await start_conversation(client)
    database = settings.database_path
    for day in range(1, EARLIER + 3):
        wrote(database, "mano", f"2026-04-0{day}", f"第{day}封")
    wrote(database, "kogane", "2026-04-09", "恋鐘的")
    await letters(another_user(client, "someone"))  # so that they are a user
    wrote(database, "mano", "2026-04-09", "别人的", to="someone")
    [her_latest] = [
        each for each in await letters(client)
        if (each["character_id"], each["day"]) == ("mano", "2026-04-05")
    ]
    assert (await client.delete(f"/api/letters/{her_latest['id']}")).status_code == 204

    await send_turn(client, conversation, "你好")

    told = context_of(llm.prompts[-1])
    salutations = [line for line in told.splitlines() if line.startswith("第")]
    assert salutations == ["第2封", "第3封", "第4封"]
    assert "恋鐘的" not in told and "别人的" not in told
