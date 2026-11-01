"""The producer on her moments (GLOSSARY.md「朋友圈」「动态」): he likes one, or no longer, and
comments on it, once, 140 characters at most, deletes his comment, and may comment again. A
like is kept only as it is now: liked and unliked leaves nothing, she never knows, and never
replies to it. His comment she replies to, in her own words, once, the closer she is the
sooner, unless she is cold to him, distant, or in a cooldown as he comments; looked at again
as her time comes, she does not if she is then, or has replied to as many comments of his
that day as the deployer lets her: neither tried again, nor told. Nothing of her reply shows
before it does. Of a reply, the activity record says how it turned out; neither a like, a
comment nor a reply changes her affinity, is remembered, or is being in touch.

Driven as `test_moments.py` drives moments (`SteadyRandom(0)`: she replies as soon as her tier
lets her), each test's moment of Mano's posted at `SEVEN`."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings
from eidolon.llm import LLMError
from eidolon.moment_prompt import COMMENTED, REPLY_RULES
from tests.conftest import MANO_SHEET, ClientFactory
from tests.fakes import (
    DEPLOYER_KEY,
    FAKE_JUDGE,
    FakeClock,
    FakeEmbedder,
    FakeIdentityProvider,
    FakeJudge,
    FakeLLM,
    FakeLLMService,
    FakeReranker,
    SteadyRandom,
    context_of,
)
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_affinity import keep
from tests.test_moments import POST, SEVEN, START, talked, tick, timeline
from tests.test_own_llm import LLM as OWN_LLM
from tests.test_reach_outs import backend_of, last_contact, records, remember
from tests.test_text_turn import send_turn, start_conversation

NOWHERE = [*POST, "<place>none</place>"]

COMMENT = "这只鸽子好可爱"

REPLIED = ["<ja>[happily] ピーちゃんも喜んでます！</ja>", "<zh>[happily] 小哔也很开心！</zh>"]
"""Her reply, as she writes it."""

SHOWN = {"ja": "ピーちゃんも喜んでます！", "zh": "小哔也很开心！"}
"""Her reply, as it shows."""

MOMENTS = "/api/admin/config/moments"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, moments=True, admins=frozenset({ADMIN}))


async def posted(
    make_client: ClientFactory, *replies, **services
) -> tuple[httpx.AsyncClient, FakeLLM, FakeClock, int]:
    """A client with Mano's moment posted at `SEVEN`, her chat model replying with `replies`
    after it; the moment's identifier."""
    client, llm, clock, _ = await talked(make_client, NOWHERE, *replies, **services)
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    [moment] = await timeline(client)
    return client, llm, clock, moment["id"]


async def shown(client: httpx.AsyncClient) -> dict:
    """The one moment on the timeline."""
    [moment] = await timeline(client)
    return moment


async def comment(client: httpx.AsyncClient, moment_id: int, text: str = COMMENT) -> httpx.Response:
    return await client.post(f"/api/moments/{moment_id}/comment", json={"text": text})


async def test_he_likes_her_moment_and_no_longer_each_as_often_as_he_likes(
    make_client: ClientFactory, settings: Settings
):
    client, llm, clock, moment = await posted(make_client)
    path = f"/api/moments/{moment}/like"

    liked = [(await client.put(path)).status_code, (await client.put(path)).status_code]
    after_liking = (await shown(client))["producer_liked"]
    unliked = [(await client.delete(path)).status_code, (await client.delete(path)).status_code]
    await client.put(path)
    await tick(client, clock, SEVEN + timedelta(hours=3))
    await client.delete(path)

    assert (liked, after_liking, unliked) == ([204, 204], True, [204, 204])
    assert (await shown(client))["producer_liked"] is False
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM moment_likes").fetchone() == (0,)
    assert len(llm.prompts) == 2  # the turn and the moment: a like is never replied to


async def test_his_comment_shows_as_he_wrote_it_once_and_is_not_edited(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, moment = await posted(make_client)
    clock.now = SEVEN + timedelta(minutes=3)

    first = await comment(client, moment, "  鸽子叫什么名字？\n下次带它来事务所吧  ")
    again = await comment(client, moment, "还有一句")

    assert first.status_code == 201, first.text
    expected = {
        "text": "  鸽子叫什么名字？\n下次带它来事务所吧  ",
        "commented_at": (SEVEN + timedelta(minutes=3)).isoformat(),
    }
    assert first.json() == expected
    assert again.status_code == 409
    moment_shown = await shown(client)
    assert moment_shown["producer_comment"] == expected
    assert moment_shown["reply"] is None


@pytest.mark.parametrize(
    ("text", "status"),
    [("   \n ", 422), ("鸽" * 141, 422), ("  " + "鸽" * 140 + "  ", 201)],
)
async def test_his_comment_has_1_to_140_characters_without_the_spaces_around_it(
    make_client: ClientFactory, settings: Settings, text: str, status: int
):
    client, _, _, moment = await posted(make_client)

    res = await comment(client, moment, text)

    assert res.status_code == status, res.text
    assert ((await shown(client))["producer_comment"] is not None) == (status == 201)


async def test_a_moment_not_his_not_shown_yet_or_gone_is_none(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, moment = await posted(make_client)
    friend = make_client(FakeLLM(), user="friend", clock=clock)
    later, gone = (
        copied(settings.database_path, moment, at)
        for at in (SEVEN + timedelta(hours=1), SEVEN - timedelta(days=30))
    )

    def each(client: httpx.AsyncClient, moment_id: int) -> list:
        return [
            client.put(f"/api/moments/{moment_id}/like"),
            client.delete(f"/api/moments/{moment_id}/like"),
            comment(client, moment_id),
            client.delete(f"/api/moments/{moment_id}/comment"),
        ]

    others = [(await r).status_code for r in each(friend, moment)]
    not_yet = [(await r).status_code for r in each(client, later)]
    none = [(await r).status_code for r in each(client, gone + 1)]
    over = [(await r).status_code for r in each(client, gone)]

    assert (others, not_yet, none, over) == ([404] * 4,) * 4


def copied(database: Path, moment_id: int, at: datetime) -> int:
    """A copy of the moment, shown `at`; its identifier."""
    with sqlite3.connect(database) as db:
        copy = db.execute(
            "INSERT INTO moments (user_id, character_id, ja, zh, day, posted_at)"
            " SELECT user_id, character_id, 'あ', '啊', day, ? FROM moments WHERE id = ?",
            (at.astimezone(UTC).isoformat(), moment_id),
        ).lastrowid
    assert copy is not None
    return copy


async def test_while_the_deployer_has_moments_off_he_neither_likes_nor_comments(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client, _, _, moment = await posted(make_client)
    async with admin_beside(client, github) as admin:
        res = await admin.put("/api/admin/config/moments", json={"enabled": False, "per_day": 3})
        assert res.status_code == 200

    refused = [
        (await client.put(f"/api/moments/{moment}/like")).status_code,
        (await client.delete(f"/api/moments/{moment}/like")).status_code,
        (await comment(client, moment)).status_code,
        (await client.delete(f"/api/moments/{moment}/comment")).status_code,
    ]

    assert refused == [409] * 4


def reply_records(database: Path) -> list[tuple[str, str, str, int]]:
    return [r for r in records(database) if r[0] == "moment_reply"]


async def reply_after(client: httpx.AsyncClient, clock: FakeClock, at: datetime) -> dict | None:
    """Her reply on the one moment, as it shows once the moments' tick at `at` is taken."""
    await tick(client, clock, at)
    return (await shown(client))["reply"]


async def replies(client: httpx.AsyncClient) -> dict[int, dict | None]:
    """Her reply on each moment, by its identifier."""
    return {m["id"]: m["reply"] for m in await timeline(client)}


async def let_reply(client: httpx.AsyncClient, github: FakeIdentityProvider, most: int) -> None:
    """Have the admin let her reply to as many of each user's comments a day."""
    async with admin_beside(client, github) as admin:
        res = await admin.put(MOMENTS, json={"enabled": True, "per_day": 3, "replies_per_day": most})
        assert res.status_code == 200, res.text


@pytest.mark.parametrize(("value", "after"), [(90, 5), (None, 30)])
async def test_she_replies_the_sooner_the_closer_she_is_and_nothing_of_it_shows_before(
    make_client: ClientFactory, settings: Settings, value: int | None, after: int
):
    """Intimate; trust where affinity is off. Each tier's time is `draw_reply`'s, tested at
    its own seam."""
    affinity = {} if value is None else {"settings": replace(settings, judge=FAKE_JUDGE)}
    client, llm, clock, moment = await posted(make_client, REPLIED, **affinity)
    if value is not None:
        keep(settings.database_path, "producer", value, SEVEN)
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment)).status_code == 201
    due = SEVEN + timedelta(minutes=3 + after)

    before = await reply_after(client, clock, due - timedelta(seconds=1))
    then = await reply_after(client, clock, due)

    assert (before, then) == (None, SHOWN)
    assert reply_records(settings.database_path) == [("moment_reply", "mano", "success", 0)]
    told = context_of(llm.prompts[-1])
    assert "制作人没有赞这条。" in told and "还没有别人赞或评论。" in told


@pytest.mark.parametrize("affinity", ["distant", "cooldown"])
async def test_cold_distant_or_in_a_cooldown_as_he_comments_she_never_replies(
    make_client: ClientFactory, settings: Settings, affinity: str
):
    client, llm, clock, moment = await posted(
        make_client, REPLIED, settings=replace(settings, judge=FAKE_JUDGE)
    )
    database = settings.database_path
    keep(database, "producer", {"distant": 30, "cooldown": 5}[affinity], SEVEN,
         cooling=affinity == "cooldown")
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment)).status_code == 201
    keep(database, "producer", 90, SEVEN + timedelta(minutes=4))  # intimate, at once

    for minutes in (10, 60, 180):
        await tick(client, clock, SEVEN + timedelta(minutes=minutes))

    assert (await shown(client))["reply"] is None
    assert (len(llm.prompts), reply_records(database)) == (2, [])


@pytest.mark.parametrize("affinity", ["distant", "cooldown"])
async def test_cold_distant_or_in_a_cooldown_as_her_time_comes_she_does_not_reply_for_good(
    make_client: ClientFactory, settings: Settings, affinity: str
):
    client, llm, clock, moment = await posted(
        make_client, REPLIED, settings=replace(settings, judge=FAKE_JUDGE)
    )
    database = settings.database_path
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment)).status_code == 201  # in trust: in 30 minutes
    keep(database, "producer", {"distant": 30, "cooldown": 5}[affinity],
         SEVEN + timedelta(minutes=10), cooling=affinity == "cooldown")

    await tick(client, clock, SEVEN + timedelta(minutes=33))
    keep(database, "producer", 50, SEVEN + timedelta(minutes=40))  # in trust again
    await tick(client, clock, SEVEN + timedelta(hours=3))

    assert (await shown(client))["reply"] is None
    assert (len(llm.prompts), reply_records(database)) == (2, [])


async def test_she_replies_to_as_many_of_his_comments_a_day_as_the_deployer_lets_her_by_the_day_they_show(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """One a day. In Tokyo, on October 19: at 23:20 he comments on the first, due at 23:50;
    at 23:25 on the second, due at 23:55; at 23:50 on the third, due at 00:20 on the 20th."""
    client, llm, clock, first = await posted(make_client, REPLIED, REPLIED)
    database = settings.database_path
    second, third = (copied(database, first, SEVEN) for _ in range(2))
    await let_reply(client, github, 1)
    evening = SEVEN + timedelta(hours=16)  # 23:00
    for moment, at in ((first, 20), (second, 25), (third, 50)):
        clock.now = evening + timedelta(minutes=at)
        assert (await comment(client, moment)).status_code == 201

    for at in (50, 55, 65, 80):
        await tick(client, clock, evening + timedelta(minutes=at))

    shown_replies = await replies(client)
    assert [shown_replies[m] for m in (first, second, third)] == [SHOWN, None, SHOWN]
    assert reply_records(database) == [("moment_reply", "mano", "success", 0)] * 2
    assert len(llm.prompts) == 4  # the turn, the moment, two replies


@pytest.mark.parametrize("fails", ["the model failing", "nothing to reply", "no subtitle"])
async def test_one_that_fails_is_recorded_failed_not_tried_again_nor_counted(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider, fails: str
):
    """One a day: the first fails, the second is replied to all the same."""
    written = {
        "the model failing": LLMError("模型返回 503: overloaded"),
        "nothing to reply": ["ピーちゃんも喜んでます！"],
        "no subtitle": ["<ja>ピーちゃんも喜んでます！</ja><zh>[happily]</zh>"],
    }[fails]
    client, llm, clock, first = await posted(make_client, written, REPLIED)
    database = settings.database_path
    second = copied(database, first, SEVEN)
    await let_reply(client, github, 1)
    for moment, at in ((first, 3), (second, 4)):
        clock.now = SEVEN + timedelta(minutes=at)
        assert (await comment(client, moment)).status_code == 201

    await tick(client, clock, SEVEN + timedelta(minutes=34))
    await tick(client, clock, SEVEN + timedelta(hours=3))

    assert await replies(client) == {first: None, second: SHOWN}
    assert reply_records(database) == [
        ("moment_reply", "mano", "failed", 0), ("moment_reply", "mano", "success", 0),
    ]
    assert len(llm.prompts) == 4


async def test_his_comment_deleted_before_she_replies_has_no_reply_and_he_may_comment_again(
    make_client: ClientFactory, settings: Settings
):
    client, llm, clock, moment = await posted(make_client, REPLIED)
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment)).status_code == 201
    clock.now = SEVEN + timedelta(minutes=10)
    deleted = await client.delete(f"/api/moments/{moment}/comment")

    gone = await shown(client)
    await tick(client, clock, SEVEN + timedelta(minutes=40))
    prompted = len(llm.prompts)
    again = await comment(client, moment, "再说一次")

    assert deleted.status_code == 204
    assert (gone["producer_comment"], gone["reply"]) == (None, None)
    assert (prompted, again.status_code) == (2, 201)
    assert await reply_after(client, clock, SEVEN + timedelta(minutes=70)) == SHOWN
    assert context_of(llm.prompts[-1]) and llm.prompts[-1][-1].content == COMMENTED + "再说一次"
    assert reply_records(settings.database_path) == [("moment_reply", "mano", "success", 0)]


async def test_his_comment_deleted_after_she_replied_takes_her_reply_but_not_the_count(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """One a day: commenting again, he has no reply that day."""
    client, llm, clock, moment = await posted(make_client, REPLIED, REPLIED)
    await let_reply(client, github, 1)
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment)).status_code == 201
    replied = await reply_after(client, clock, SEVEN + timedelta(minutes=33))

    deleted = await client.delete(f"/api/moments/{moment}/comment")
    gone = await shown(client)
    again = await comment(client, moment, "再说一次")
    await tick(client, clock, SEVEN + timedelta(hours=3))

    assert (replied, deleted.status_code, again.status_code) == (SHOWN, 204, 201)
    assert (gone["producer_comment"], gone["reply"]) == (None, None)
    moment_shown = await shown(client)
    assert moment_shown["producer_comment"]["text"] == "再说一次"
    assert moment_shown["reply"] is None
    assert len(llm.prompts) == 3


async def test_his_comment_deleted_as_she_replies_has_her_reply_rejected(
    make_client: ClientFactory, settings: Settings
):
    writing = asyncio.Event()
    client, llm, clock, moment = await posted(make_client, [writing, *REPLIED])
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment)).status_code == 201

    clock.now = SEVEN + timedelta(minutes=33)
    replying = asyncio.create_task(backend_of(client).moments.run_due())
    while len(llm.prompts) < 3:
        await asyncio.sleep(0)
    deleted = await client.delete(f"/api/moments/{moment}/comment")
    writing.set()
    await replying

    assert deleted.status_code == 204
    assert (await shown(client))["reply"] is None
    assert reply_records(settings.database_path) == [("moment_reply", "mano", "rejected", 0)]


async def test_she_is_asked_with_her_moment_her_circle_so_far_his_like_their_last_turns_and_his_words(
    make_client: ClientFactory, settings: Settings
):
    """Kogane's second comment shows only after she replies. Of what he told her, only what
    he told her herself."""
    circle = [
        *NOWHERE, "<likes>kogane</likes>",
        '<comment from="kogane"><ja>うちも行きたか～！</ja><zh>咱也想去～！</zh></comment>',
        '<comment from="kogane"><ja>ピーちゃん元気？</ja><zh>小哔还好吗？</zh></comment>',
    ]
    client, llm, clock, conversation = await talked(
        make_client, ["<ja>猫ちゃん？</ja><zh>小猫怎么了？</zh>"], circle, REPLIED,
        retrieval_judge=FakeJudge(answer="nothing"), embedder=FakeEmbedder(),
        reranker=FakeReranker("猫", others=0.0),
    )
    await send_turn(client, conversation, "我家的猫又捣乱了")
    database = settings.database_path
    remember(database, "制作人家里养了一只叫小白的猫", START - timedelta(days=40))
    remember(database, "制作人家的猫怕打雷", START - timedelta(days=40), told="kogane")
    last_contact(database, conversation, START - timedelta(hours=1))
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    [moment] = await timeline(client)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE moments SET image = ?", ('{"note": "公园长椅上的小哔"}',))
        db.execute(
            "UPDATE moment_circle SET shown_at = ? WHERE kind = 'comment' AND position = 1",
            ((SEVEN + timedelta(hours=3)).isoformat(),),
        )
    clock.now = SEVEN + timedelta(minutes=20)
    assert (await client.put(f"/api/moments/{moment['id']}/like")).status_code == 204
    assert (await comment(client, moment["id"])).status_code == 201

    assert await reply_after(client, clock, SEVEN + timedelta(minutes=50)) == SHOWN

    asking = llm.prompts[-1]
    assert MANO_SHEET in asking[0].content and asking[0].cache_breakpoint
    assert "# 回复格式" not in asking[0].content
    assert asking[1].content.startswith("# 制作人")
    assert [(m.role, m.content) for m in asking[2:6]] == [
        ("user", "我去练习了"), ("assistant", "<ja>はい</ja><zh>好的</zh>"),
        ("user", "我家的猫又捣乱了"), ("assistant", "<ja>猫ちゃん？</ja><zh>小猫怎么了？</zh>"),
    ]
    assert asking[-1].content == COMMENTED + COMMENT
    told = context_of(asking)
    assert "（东京时间）" in told and "你这会儿在看自己朋友圈下面的评论" in told
    assert "# 你这条朋友圈\n今日は公園でピーちゃんと日向ぼっこ(^^)（配图：公园长椅上的小哔）" in told
    assert "赞：月岡恋鐘" in told and "- 月岡恋鐘：うちも行きたか～！" in told
    assert "ピーちゃん元気" not in told
    assert "制作人赞了这条。" in told
    assert "制作人家里养了一只叫小白的猫" in told and "怕打雷" not in told
    assert told.endswith(REPLY_RULES)
    assert (llm.tools[-1], llm.keys[-1]) == ([], DEPLOYER_KEY)


async def test_she_replies_on_the_deployers_chat_model_changing_nothing_else_of_theirs(
    make_client: ClientFactory, settings: Settings, own_llm: FakeLLMService
):
    """Neither her affinity, his memories, nor when they were last in touch."""
    llm = FakeLLM(NOWHERE, REPLIED)
    own_llm.llm = FakeLLM(["<ja>はい</ja><zh>好的</zh>"])
    clock = FakeClock(START)
    client = make_client(
        llm, clock=clock, random=SteadyRandom(0), settings=replace(settings, judge=FAKE_JUDGE)
    )
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "在吗", own_llm=OWN_LLM)
    database = settings.database_path
    last_contact(database, conversation, START - timedelta(hours=1))
    keep(database, "producer", 90, START)
    remember(database, "制作人家里养了一只叫小白的猫", START - timedelta(days=1))
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    [moment] = await timeline(client)
    before = theirs(database)

    clock.now = SEVEN + timedelta(minutes=3)
    await client.put(f"/api/moments/{moment['id']}/like")
    assert (await comment(client, moment["id"])).status_code == 201
    replied = await reply_after(client, clock, SEVEN + timedelta(minutes=8))

    assert replied == SHOWN
    assert llm.keys == [DEPLOYER_KEY] * 2
    assert theirs(database) == before


def theirs(database: Path) -> tuple[list, list, list]:
    """The user's affinities, memories and messages, as the database has them."""
    with sqlite3.connect(database) as db:
        return (
            db.execute("SELECT * FROM affinities").fetchall(),
            db.execute("SELECT * FROM memories").fetchall(),
            db.execute("SELECT * FROM messages").fetchall(),
        )


async def test_turned_off_and_on_again_the_replies_whose_time_came_meanwhile_are_not_made(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client, llm, clock, moment = await posted(make_client, REPLIED)
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment)).status_code == 201

    async with admin_beside(client, github) as admin:
        assert (await admin.put(MOMENTS, json={"enabled": False, "per_day": 3})).status_code == 200
        await tick(client, clock, SEVEN + timedelta(minutes=33))
        assert (await admin.put(MOMENTS, json={"enabled": True, "per_day": 3})).status_code == 200
    await tick(client, clock, SEVEN + timedelta(minutes=40))

    assert all(m["reply"] is None for m in await timeline(client))
    assert not any(p[-1].content.startswith(COMMENTED) for p in llm.prompts)
    assert reply_records(settings.database_path) == []


async def test_the_admin_sets_how_many_comments_a_day_she_replies_to(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client = make_client(FakeLLM())
    async with admin_beside(client, github) as admin:
        described = (await admin.get("/api/admin/config")).json()["moments"]
        refused = [
            (await admin.put(MOMENTS, json={"enabled": True, "per_day": 3, "replies_per_day": n}))
            .status_code
            for n in (0, "3", True)
        ]
        saved = await admin.put(MOMENTS, json={"enabled": True, "per_day": 3, "replies_per_day": 2})
        kept = await admin.put(MOMENTS, json={"enabled": True, "per_day": 3})

    assert described["effective"]["replies_per_day"] == 10
    assert refused == [422] * 3
    assert saved.json()["moments"]["effective"]["replies_per_day"] == 2
    assert kept.json()["moments"]["effective"]["replies_per_day"] == 2


@pytest.mark.parametrize(("restarted", "replies"), [(30, True), (40, False)])
async def test_one_whose_time_came_while_the_backend_was_down_is_not_made_up_for(
    make_client: ClientFactory, settings: Settings, restarted: int, replies: bool
):
    """Due at 07:33, the backend restarted at 07:30, or at 07:40."""
    client, _, clock, moment = await posted(make_client)
    clock.now = SEVEN + timedelta(minutes=3)
    assert (await comment(client, moment)).status_code == 201

    llm = FakeLLM(REPLIED)
    restart = SEVEN + timedelta(minutes=restarted)
    again = make_client(llm, clock=(clock := FakeClock(restart)), random=SteadyRandom(0))
    await tick(again, clock, restart)
    await tick(again, clock, SEVEN + timedelta(hours=3))

    assert (await shown(again))["reply"] == (SHOWN if replies else None)
    assert len(llm.prompts) == int(replies)
