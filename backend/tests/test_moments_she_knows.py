"""Her latest moments as she knows of them talking with the producer (GLOSSARY.md「朋友圈」
「动态」「此刻」, `recent_moments`): typing, in a call and reaching out, after what she knows
of now, not visiting the bar nor posting a moment. Of hers that have shown within three days,
the latest three, a line each, the producer's time: her Japanese, the note of a picture he
sees, whether he likes it, his comment and her reply once it shows; then how she may bring
them up, looking forward only close or intimate. Reaching out, she may reach out about them
too. Nothing of them while the deployer or the user has moments off.

Driven through the backend's external API, her moment posted and replied to as
`test_moment_producer` has it; the others are put in the database, as she would have
posted them, and the lines read through `HerNow` taken from the assembled backend, as
`test_her_now` does."""

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from eidolon.affinity import Tier
from eidolon.config import Settings
from eidolon.engine import REACH_OUT_RULES_WITH_MOMENTS
from eidolon.her_now import Occasion
from eidolon.llm import ChatMessage
from eidolon.recent_moments import BRING_UP, HEADING, LOOKING_FORWARD, moments_section
from tests.conftest import ClientFactory
from tests.fakes import FAKE_JUDGE, FakeClock, FakeLLM, SteadyRandom, context_of
from tests.test_affinity import keep
from tests.test_delete_account import user_id
from tests.test_moment_producer import COMMENT, NOWHERE, REPLIED, comment
from tests.test_moment_switch import switch
from tests.test_moments import REPLY, SEVEN, START, talked, tick, timeline
from tests.test_reach_outs import REACH_OUT, backend_of, last_contact
from tests.test_text_turn import send_turn, start_conversation

JA = "今日は公園でピーちゃんと日向ぼっこ(^^)"
"""Her moment of `test_moments.POST`, as it shows."""

NEXT_DAY = SEVEN + timedelta(days=1)
"""06:00 in Shanghai, where the producer is, the day after her moment of `SEVEN`."""


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, moments=True)


def put(
    database: Path,
    posted_at: datetime,
    ja: str = JA,
    *,
    character: str = "mano",
    note: str | None = None,
    pictured: bool = False,
    liked: bool = False,
    commented: str | None = None,
    reply: str | None = None,
    reply_at: datetime | None = None,
) -> int:
    """Have the producer's `character` have posted a moment at `posted_at`, its picture
    written with `note`, generated if `pictured`; he liking it if `liked`, and commenting
    `commented`, her `reply` due at `reply_at`, written if given."""
    with sqlite3.connect(database) as db:
        moment = db.execute(
            "INSERT INTO moments (user_id, character_id, ja, zh, image, day, posted_at)"
            " VALUES (?, ?, ?, '字幕', ?, ?, ?)",
            (user_id(database, "producer"), character, ja,
             json.dumps({"note": note}, ensure_ascii=False) if note else None,
             posted_at.date().isoformat(), posted_at.isoformat()),
        ).lastrowid
        assert moment is not None
        if pictured:
            db.execute("INSERT INTO moment_images VALUES (?, x'00')", (moment,))
        if liked:
            db.execute("INSERT INTO moment_likes VALUES (?)", (moment,))
        if commented is not None:
            db.execute(
                "INSERT INTO moment_comments (moment_id, text, commented_at, reply_at, reply_ja,"
                " reply_zh) VALUES (?, ?, ?, ?, ?, ?)",
                (moment, commented, posted_at.isoformat(),
                 reply_at and reply_at.isoformat(), reply, reply and "回复"),
            )
    return moment


async def told(
    client: httpx.AsyncClient, occasion: Occasion = "typing", tier: Tier | None = None
) -> str | None:
    """The section telling the producer's Mano of her latest moments on `occasion`, she in
    `tier`, the producer in Shanghai."""
    backend = backend_of(client)
    known = await backend.her_now.read(
        user_id(backend.settings.database_path, "producer"), "mano", None, occasion
    )
    return moments_section(known.moments, backend.clock(), "Asia/Shanghai", tier)


async def test_typing_she_knows_her_moment_his_like_his_comment_and_her_reply(
    make_client: ClientFactory, settings: Settings
):
    client, llm, clock, conversation = await talked(make_client, NOWHERE, REPLIED, REPLY)
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    [moment] = await timeline(client)
    await client.put(f"/api/moments/{moment['id']}/like")
    await comment(client, moment["id"])
    await tick(client, clock, SEVEN + timedelta(minutes=30))  # in trust, her reply shows
    clock.now = NEXT_DAY

    await send_turn(client, conversation, "昨天发了什么？")

    line = (
        f"昨天 06:00　{JA}　制作人赞了；他评论「{COMMENT}」，你回了「ピーちゃんも喜んでます！」"
    )
    told_after_now(llm.prompts[-1], f"{HEADING}\n{line}\n{BRING_UP}")


def told_after_now(prompt: list[ChatMessage], section: str) -> None:
    """That `prompt` tells `section` after what she knows of now, where what changes from
    turn to turn is, and nowhere else."""
    context = context_of(prompt)
    assert section in context
    assert context.index("# 此刻") < context.index(HEADING)
    assert all(HEADING not in m.content for m in prompt if m.content != context)


async def test_reaching_out_she_knows_her_moments_and_may_reach_out_about_them(
    make_client: ClientFactory, settings: Settings
):
    settings = replace(settings, reach_outs=True, judge=FAKE_JUDGE)
    llm = FakeLLM(REPLY, REACH_OUT)
    clock = FakeClock(NEXT_DAY + timedelta(hours=4))  # 10:00 in Shanghai
    client = make_client(llm, clock=clock, settings=settings, random=SteadyRandom(0))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "我去练习了")
    database = settings.database_path
    keep(database, "producer", 90, clock.now - timedelta(hours=5))  # intimate: 3 hours on
    last_contact(database, conversation, clock.now - timedelta(hours=3))  # due now
    put(database, SEVEN, liked=True)

    await backend_of(client).reach_outs.run_due()

    assert len(llm.prompts) == 2
    told_after_now(
        llm.prompts[-1],
        f"{HEADING}\n昨天 06:00　{JA}　制作人赞了，没评论\n{BRING_UP}{LOOKING_FORWARD}",
    )
    assert REACH_OUT_RULES_WITH_MOMENTS in context_of(llm.prompts[-1])


async def test_without_moments_to_tell_she_is_told_no_section(
    make_client: ClientFactory, settings: Settings
):
    client, *_ = await talked(make_client)

    assert await told(client, "apart") is None


async def test_in_a_call_she_is_told_of_them_visiting_the_bar_not(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, _ = await talked(make_client)
    put(settings.database_path, clock.now - timedelta(hours=1))

    assert await told(client, "visit") is None
    assert await told(client, "in_call") is not None


async def test_she_knows_the_latest_three_of_those_shown_within_three_days_her_own_only(
    make_client: ClientFactory, settings: Settings
):
    client, *_ = await talked(make_client, at=NEXT_DAY)
    database = settings.database_path
    put(database, NEXT_DAY - timedelta(days=3), "三日前")
    for hours in (60, 30, 20, 1):
        put(database, NEXT_DAY - timedelta(hours=hours), f"{hours}時間前")
    put(database, NEXT_DAY + timedelta(minutes=1), "まだ")
    put(database, NEXT_DAY - timedelta(hours=2), "灯織の", character="hiori")

    section = await told(client)

    assert section is not None
    assert section.splitlines()[1:-1] == [
        "昨天 00:00　30時間前　他还没赞也没评论",
        "昨天 10:00　20時間前　他还没赞也没评论",
        "今天 05:00　1時間前　他还没赞也没评论",
    ]


async def test_each_line_says_what_he_made_of_it_and_she_of_his_comment(
    make_client: ClientFactory, settings: Settings
):
    client, *_ = await talked(make_client, at=NEXT_DAY)
    database = settings.database_path
    at = NEXT_DAY - timedelta(hours=71)  # 07:00 on October 17 in Shanghai
    put(database, at, "写真つき", note="公园长椅上的鸽子", pictured=True)
    put(database, at + timedelta(hours=1), "まだ返事なし\n", note="没生成出来的图", liked=True,
        commented=" 早点睡\n明天见", reply="まだ", reply_at=NEXT_DAY + timedelta(minutes=5))
    put(database, at + timedelta(hours=2), "返事あり", commented="好看", reply="ありがとう",
        reply_at=NEXT_DAY - timedelta(minutes=30))

    section = await told(client)

    assert section is not None
    assert section.splitlines()[1:-1] == [
        "10月17日 07:00　写真つき（配图：公园长椅上的鸽子）　他还没赞也没评论",
        "10月17日 08:00　まだ返事なし　制作人赞了；他评论「早点睡 明天见」",
        "10月17日 09:00　返事あり　制作人没赞，评论「好看」，你回了「ありがとう」",
    ]


@pytest.mark.parametrize(("tier", "looking_forward"), [("trust", False), ("close", True)])
async def test_only_close_or_intimate_she_may_look_forward_to_his_seeing_them(
    make_client: ClientFactory, settings: Settings, tier: Tier | None, looking_forward: bool
):
    client, _, clock, _ = await talked(make_client)
    put(settings.database_path, clock.now - timedelta(hours=1))

    section = await told(client, tier=tier)

    assert section is not None
    assert section.splitlines()[-1] == BRING_UP + (LOOKING_FORWARD if looking_forward else "")


@pytest.mark.parametrize("by", ["deployer", "user"])
async def test_with_moments_off_she_knows_none_of_them(
    make_client: ClientFactory, settings: Settings, by: str
):
    if by == "deployer":
        settings = replace(settings, moments=False)
    client, _, clock, _ = await talked(make_client, settings=settings)
    put(settings.database_path, clock.now - timedelta(hours=1))
    if by == "user":
        await switch(client, False)

    assert await told(client) is None
