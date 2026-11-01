"""Moments (GLOSSARY.md「朋友圈」「动态」): what the characters post to each user's own moments.
The deployer turns them on; then each user who has been in touch with any character within a
week (a turn, or a call that connected; gifts are not) is planned for once a day in Tokyo,
from what is left of the day: each character they have had a turn with, in trust or above
and not in a cooldown, drawn for, and given a time in the morning, at lunch, after work or
late at night. As her time comes she posts on the deployer's chat model, whoever's LLM the
user brings, her prompt laid out as a turn's without the history; looked at again first, and
passed over for good if she is no longer to. What came as the backend was down is not made up
for, nor what failed. Each has an activity record of its own, which no count of turns or
calls takes in.

Driven through the backend's external API, with the moments' ticks taken by hand
(`Moments.run_due`), the clock moved, chance steady (`SteadyRandom(0)`: every draw posts, and
the earliest part of the day left, at its start), and when the user was last in touch set in
the database directly, as the store writes the time as it is."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings
from eidolon.llm import LLMError
from eidolon.moment_prompt import HER_BIRTHDAY, POST_RULES, WANTS_TO_POST
from tests.conftest import KOGANE_SHEET, MANO_SHEET, CharacterConfig, ClientFactory
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
    FakeServiceClients,
    SteadyRandom,
    context_of,
)
from tests.test_activity_records import dashboard, health
from tests.test_admin_users import ADMIN, admin_beside, details, find
from tests.test_affinity import keep
from tests.test_own_llm import LLM as OWN_LLM
from tests.test_reach_outs import (
    backend_of,
    connected_call,
    last_contact,
    records,
    remember,
    write_event,
)
from tests.test_text_turn import send_turn, start_conversation
from tests.test_user_limits import set_limits

REPLY = ["<ja>はい</ja><zh>好的</zh>"]
POST = [
    "<post><ja>[happily] 今日は公園でピーちゃんと日向ぼっこ(^^)</ja>",
    "<zh>今天和小哔在公园晒太阳(^^)</zh></post>",
]
MOMENTS = "/api/admin/config/moments"
START = datetime(2026, 10, 18, 15, 30, tzinfo=UTC)
"""00:30 on October 19 in Tokyo: the first tick of the day."""
SEVEN = datetime(2026, 10, 18, 22, tzinfo=UTC)
"""07:00 that day in Tokyo, the earliest a moment planned at `START` is due."""

FACTS = """\
# 人物关系
## 風野灯織
illumination STARS 的伙伴，真乃叫她「灯織ちゃん」。
# 家人
真乃和父母以及鸽子ピーちゃん住在一起。
# 小时候
真乃小时候就喜欢偶像。
# 兴趣
喜欢在公园晒太阳。
# 学校
高一学生。
"""


@pytest.fixture
def characters(tmp_path: Path) -> CharacterConfig:
    """Mano, with facts, her birthday on April 25; Kogane, without."""
    return (
        CharacterConfig(tmp_path / "characters")
        .add("mano", "櫻木真乃", MANO_SHEET, birthday="04-25", facts=FACTS)
        .add("kogane", "月岡恋鐘", KOGANE_SHEET, birthday="02-25")
    )


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With moments on in `.env`, and an admin."""
    return replace(settings, moments=True, admins=frozenset({ADMIN}))


async def talked(
    make_client: ClientFactory, *replies, at: datetime = START, **services
) -> tuple[httpx.AsyncClient, FakeLLM, FakeClock, str]:
    """A client whose user has had a turn with Mano an hour before `at`, her chat model
    replying with `REPLY` and then `replies`, on a clock of its own set to `at`, chance
    steady."""
    llm = FakeLLM(REPLY, *replies)
    clock = FakeClock(at)
    services.setdefault("random", SteadyRandom(0))
    client = make_client(llm, clock=clock, **services)
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "我去练习了")
    last_contact(database_of(client), conversation, at - timedelta(hours=1))
    return client, llm, clock, conversation


def database_of(client: httpx.AsyncClient) -> Path:
    return backend_of(client).settings.database_path


async def tick(client: httpx.AsyncClient, clock: FakeClock, at: datetime) -> None:
    clock.now = at
    await backend_of(client).moments.run_due()


async def timeline(client: httpx.AsyncClient) -> list[dict]:
    res = await client.get("/api/moments")
    assert res.status_code == 200, res.text
    return res.json()["moments"]


def moment_records(database: Path) -> list[tuple[str, str, str, int]]:
    return [r for r in records(database) if r[0] == "moment"]


async def test_planned_after_midnight_she_posts_at_her_time_asked_as_a_turn_without_history(
    make_client: ClientFactory, settings: Settings
):
    client, llm, clock, _ = await talked(make_client, POST)

    await tick(client, clock, START)
    await tick(client, clock, SEVEN - timedelta(minutes=1))
    before = await timeline(client)
    await tick(client, clock, SEVEN)

    assert before == []
    assert await timeline(client) == [{
        "id": 1, "character_id": "mano",
        "ja": "今日は公園でピーちゃんと日向ぼっこ(^^)", "zh": "今天和小哔在公园晒太阳(^^)",
        "image": None, "place": None, "weather": None, "posted_at": SEVEN.isoformat(),
        "likes": [], "comments": [],
        "producer_liked": False, "producer_comment": None, "reply": None,
    }]
    assert (await client.get("/api/account")).json()["moments"] is True
    assert moment_records(settings.database_path) == [("moment", "mano", "success", 0)]
    posting = llm.prompts[-1]
    assert [m.role for m in posting] == ["system", "system", "system", "user"]  # no history
    assert MANO_SHEET in posting[0].content and POST_RULES in posting[0].content
    assert "# 回复格式" not in posting[0].content
    assert posting[0].cache_breakpoint
    assert posting[1].content.startswith("# 制作人")
    assert posting[-1].content == WANTS_TO_POST
    told = context_of(posting)
    assert "2026年10月19日（星期一）07:00（东京时间）" in told
    assert "你这会儿在发朋友圈" in told and "上次和制作人说话" not in told
    assert "- 家人：真乃和父母以及鸽子ピーちゃん住在一起。" in told
    assert "- 小时候：真乃小时候就喜欢偶像。" in told and "- 兴趣：喜欢在公园晒太阳。" in told
    assert "高一学生" not in told and "灯織ちゃん" not in told  # three drawn, none of 人物关系
    assert HER_BIRTHDAY not in told
    assert (llm.tools[-1], llm.keys[-1]) == ([], DEPLOYER_KEY)


async def test_she_posts_on_the_deployers_chat_model_whatever_the_user_brings(
    make_client: ClientFactory, settings: Settings, own_llm: FakeLLMService
):
    llm = FakeLLM(POST)
    own_llm.llm = FakeLLM(REPLY)
    clients = FakeServiceClients(llm)
    clock = FakeClock(START)
    client = make_client(llm, clock=clock, clients=clients, random=SteadyRandom(0))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "在吗", own_llm=OWN_LLM)
    last_contact(settings.database_path, conversation, START - timedelta(hours=1))

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    assert llm.keys == [DEPLOYER_KEY]
    assert clients.efforts == [settings.chat_llm.reasoning_effort]  # as text turns, not calls
    assert len(await timeline(client)) == 1


@pytest.mark.parametrize(
    ("touch", "posts"),
    [("a turn 6 days ago", 1), ("a turn over 7 days ago", 0), ("a call 2 days ago", 1),
     ("a gift an hour ago", 0)],
)
async def test_a_user_has_moments_who_was_in_touch_within_a_week_but_by_a_gift(
    make_client: ClientFactory, settings: Settings, touch: str, posts: int
):
    client, _, clock, conversation = await talked(make_client, POST)
    database = settings.database_path
    turn_ago = timedelta(days=6) if touch == "a turn 6 days ago" else timedelta(days=7, minutes=1)
    last_contact(database, conversation, START - turn_ago)
    if touch == "a call 2 days ago":
        connected_call(database, conversation, START - timedelta(days=2), 600)
    if touch == "a gift an hour ago":
        write_event(database, conversation, "gift", START - timedelta(hours=1))

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    assert len(await timeline(client)) == posts, touch


@pytest.mark.parametrize(("affinity", "posts"), [("intimate", 1), ("distant", 0), ("cooldown", 0)])
async def test_she_posts_who_has_had_a_turn_with_the_user_in_trust_or_above_out_of_a_cooldown(
    make_client: ClientFactory, settings: Settings, affinity: str, posts: int
):
    """Kogane, in a conversation without a turn, never."""
    client, _, clock, _ = await talked(
        make_client, POST, settings=replace(settings, judge=FAKE_JUDGE)
    )
    await start_conversation(client, "kogane")
    keep(settings.database_path, "producer", {"intimate": 90, "distant": 30, "cooldown": 5}[affinity],
         START, cooling=affinity == "cooldown")

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    assert [m["character_id"] for m in await timeline(client)] == ["mano"] * posts


async def test_one_back_in_the_day_is_planned_for_what_is_left_of_it(
    make_client: ClientFactory, settings: Settings
):
    """At 10:00 in Tokyo, the morning is over: lunch, from 12:00."""
    ten = START + timedelta(hours=9, minutes=30)
    client, _, clock, _ = await talked(make_client, POST, at=ten)

    await tick(client, clock, ten)
    await tick(client, clock, ten + timedelta(hours=1, minutes=59))
    before = await timeline(client)
    await tick(client, clock, ten + timedelta(hours=2))

    assert (len(before), len(await timeline(client))) == (0, 1)


async def test_one_come_up_to_trust_since_the_day_was_planned_waits_for_the_next(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, conversation = await talked(
        make_client, POST, settings=replace(settings, judge=FAKE_JUDGE)
    )
    keep(settings.database_path, "producer", 39, START)  # distant, recovering

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    that_day = await timeline(client)
    await tick(client, clock, START + timedelta(days=1))
    await tick(client, clock, SEVEN + timedelta(days=1))

    assert (len(that_day), len(await timeline(client))) == (0, 1)


@pytest.mark.parametrize(
    ("restarted", "posts"), [(START + timedelta(hours=3), 1), (SEVEN + timedelta(hours=1), 0)]
)
async def test_the_plan_is_read_again_after_a_restart_but_what_came_while_down_is_not_made_up_for(
    make_client: ClientFactory, settings: Settings, restarted: datetime, posts: int
):
    client, _, clock, _ = await talked(make_client)
    await tick(client, clock, START)

    llm = FakeLLM(POST)
    again = make_client(llm, clock=(clock := FakeClock(restarted)), random=SteadyRandom(0))
    await tick(again, clock, restarted)
    await tick(again, clock, restarted + timedelta(hours=5))  # past 07:00 either way

    assert (len(await timeline(again)), len(llm.prompts)) == (posts, posts)


@pytest.mark.parametrize(
    "why", ["banned", "no turns on the deployer's keys", "cooldown", "a week ago",
            "the day's moments had"],
)
async def test_one_due_she_is_no_longer_to_post_is_passed_over_unrecorded(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider, why: str
):
    client, llm, clock, conversation = await talked(
        make_client, POST, settings=replace(settings, judge=FAKE_JUDGE)
    )
    database = settings.database_path
    await tick(client, clock, START)
    async with admin_beside(client, github) as admin:
        producer = (await find(admin, "producer"))["id"]
        if why == "banned":
            assert (await admin.post(f"/api/admin/users/{producer}/ban", json={})).status_code == 200
        elif why == "no turns on the deployer's keys":
            await set_limits(admin, producer, turns_per_hour=0)
    if why == "cooldown":
        keep(database, "producer", 5, START, cooling=True)
    if why == "a week ago":
        last_contact(database, conversation, SEVEN - timedelta(days=7, minutes=1))
    if why == "the day's moments had":
        with sqlite3.connect(database) as db:
            db.executemany(
                "INSERT INTO moments (user_id, character_id, ja, zh, day, posted_at)"
                " VALUES (?, 'kogane', 'あ', '啊', '2026-10-19', ?)",
                [(producer, START.isoformat())] * 3,
            )

    await tick(client, clock, SEVEN)
    await tick(client, clock, SEVEN + timedelta(hours=1))

    assert len(llm.prompts) == 1, why  # the turn's only
    assert moment_records(database) == [], why


async def test_turned_off_and_on_again_she_posts_what_is_left_of_the_day_planned_anew(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """Off at 07:00, on again by 09:00, as the morning is over: at lunch, from 12:00."""
    client, _, clock, _ = await talked(make_client, POST)
    await tick(client, clock, START)

    async with admin_beside(client, github) as admin:
        assert (await admin.put(MOMENTS, json={"enabled": False, "per_day": 3})).status_code == 200
        await tick(client, clock, SEVEN)
        assert (await admin.put(MOMENTS, json={"enabled": True, "per_day": 3})).status_code == 200
    came = []
    for at in (SEVEN + timedelta(hours=2), SEVEN + timedelta(hours=4, minutes=59),
               SEVEN + timedelta(hours=5)):
        await tick(client, clock, at)
        came.append(len(await timeline(client)))

    assert came == [0, 0, 1]


@pytest.mark.parametrize(
    "fails", ["the model failing", "nothing to post", "no subtitle"],
)
async def test_one_that_fails_is_recorded_failed_and_not_tried_again(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider, fails: str
):
    """Only the model failing counts as the chat model's failure."""
    written = {
        "the model failing": LLMError("模型返回 503: overloaded"),
        "nothing to post": ["<ja>今日も頑張った</ja><zh>今天也努力了</zh>"],
        "no subtitle": ["<post><ja>今日も頑張った</ja><zh>[happily]</zh></post>"],
    }[fails]
    client, llm, clock, _ = await talked(make_client, written, POST)

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    await tick(client, clock, SEVEN + timedelta(hours=3))
    async with admin_beside(client, github) as admin:
        chat = health(await dashboard(admin), "chat_llm")

    assert await timeline(client) == []
    assert moment_records(settings.database_path) == [("moment", "mano", "failed", 0)]
    assert len(llm.prompts) == 2
    assert chat is not None and chat["errors"] == (1 if fails == "the model failing" else 0)


async def test_off_by_default_the_admin_turns_them_on_with_how_many_a_day(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """Mano and Kogane both drawn, one a day."""
    client, _, clock, _ = await talked(
        make_client, REPLY, POST, settings=replace(settings, moments=False)
    )
    kogane = await start_conversation(client, "kogane")
    await send_turn(client, kogane, "在吗")

    async with admin_beside(client, github) as admin:
        described = (await admin.get("/api/admin/config")).json()["moments"]
        await tick(client, clock, START)
        account = (await client.get("/api/account")).json()
        refused_timeline = await client.get("/api/moments")
        refused = [
            await admin.put(MOMENTS, json=body)
            for body in ({"enabled": "yes", "per_day": 3}, {"enabled": True, "per_day": 0})
        ]
        turned_on = await admin.put(MOMENTS, json={"enabled": True, "per_day": 1})
    await tick(client, clock, START + timedelta(minutes=1))
    await tick(client, clock, SEVEN)
    await tick(client, clock, SEVEN + timedelta(hours=16, minutes=59))

    assert described == {
        "status": "env",
        "env": {"enabled": False, "per_day": 3, "map": "osm", "replies_per_day": 10},
        "effective": {"enabled": False, "per_day": 3, "map": "osm", "replies_per_day": 10},
        "override": None,
        "failure": None,
    }
    assert account["moments"] is None
    assert refused_timeline.status_code == 409
    assert [r.status_code for r in refused] == [422] * 2
    assert turned_on.status_code == 200
    assert turned_on.json()["moments"]["effective"] == {
        "enabled": True, "per_day": 1, "map": "osm", "replies_per_day": 10,
    }
    assert (await client.get("/api/account")).json()["moments"] is True
    assert len(await timeline(client)) == 1


async def test_each_has_an_activity_record_of_its_own_which_no_turn_or_call_counts_take_in(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """The turn a day before, out of the dashboard's last 24 hours."""
    llm = FakeLLM(REPLY, POST, tokens=(1000, 200))
    clock = FakeClock(START - timedelta(days=1))
    client = make_client(llm, clock=clock, random=SteadyRandom(0))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "在吗")
    last_contact(settings.database_path, conversation, START - timedelta(hours=1))

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    async with admin_beside(client, github) as admin:
        board = await dashboard(admin)
        user = await find(admin, "producer")
        shown = await details(admin, user["id"])

    assert records(settings.database_path) == [
        ("turn", "mano", "success", 0), ("moment", "mano", "success", 0),
    ]
    assert (board["turns"]["total"], board["calls"]["total"], board["active_users"]) == (0, 0, 0)
    assert sum(point["turns"] + point["calls"] + point["active_users"]
               for point in board["trend"]) == 0
    assert board["characters"] == []
    chat = health(board, "chat_llm")
    assert chat is not None and (chat["calls"], chat["errors"]) == (1, 0)
    [cost] = [r for r in board["cost"]["rows"] if r["service"] == "chat_llm"]
    assert (cost["calls"], cost["input"], cost["output"]) == (1, 1000, 200)
    assert user["usage_24h"] == {"turns": 0, "calls": 0}
    assert shown["usage"]["7d"]["turns"] == {"deployer": 1, "own_keys": 0}


async def test_she_is_told_only_what_he_told_her_herself_found_with_their_last_turn(
    make_client: ClientFactory, settings: Settings
):
    embedder, reranker = FakeEmbedder(), FakeReranker("猫", others=0.0)
    client, llm, clock, conversation = await talked(
        make_client, ["<ja>猫ちゃん？</ja><zh>小猫怎么了？</zh>"], POST,
        retrieval_judge=FakeJudge(answer="nothing"), embedder=embedder, reranker=reranker,
    )
    await send_turn(client, conversation, "我家的猫又捣乱了")
    database = settings.database_path
    remember(database, "制作人家里养了一只叫小白的猫", START - timedelta(days=40))
    remember(database, "制作人家的猫怕打雷", START - timedelta(days=40), told="kogane")
    remember(database, "制作人最近在学吉他", START - timedelta(days=1), told="kogane")
    last_contact(database, conversation, START - timedelta(hours=1))

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    told = context_of(llm.prompts[-1])
    found = [line.split("（")[0] for line in told.splitlines() if line.startswith("- 制作人")]
    assert found == ["- 制作人家里养了一只叫小白的猫"]
    assert "最多隐约呼应一件" in told
    assert reranker.calls[-1][0] == "我家的猫又捣乱了\n小猫怎么了？"


async def test_she_is_told_her_latest_five_moments_and_on_her_birthday_that_it_is(
    make_client: ClientFactory, settings: Settings
):
    """April 25 in Tokyo, the producer's birthday too where they are."""
    birthday = datetime(2027, 4, 24, 15, 30, tzinfo=UTC)
    client, llm, clock, _ = await talked(make_client, POST, at=birthday)
    res = await client.put(
        "/api/profile", json={"birthday": {"month": 4, "day": 25}, "timezone": "Asia/Tokyo"}
    )
    assert res.status_code == 200, res.text
    with sqlite3.connect(settings.database_path) as db:
        db.executemany(
            "INSERT INTO moments (user_id, character_id, ja, zh, day, posted_at)"
            " VALUES ((SELECT id FROM users WHERE name = 'producer'), ?, ?, '字幕', ?, ?)",
            [("mano", f"{n}日目", "2027-04-01", (birthday - timedelta(days=10 - n)).isoformat())
             for n in range(6)] + [("kogane", "恋鐘の", "2027-04-01", birthday.isoformat())],
        )

    await tick(client, clock, birthday)
    await tick(client, clock, birthday + timedelta(hours=6, minutes=30))

    told = context_of(llm.prompts[-1])
    recent = told.split("# 你最近发的朋友圈\n最新的在前：\n")[1].splitlines()[:6]
    assert recent[:5] == ["- 5日目", "- 4日目", "- 3日目", "- 2日目", "- 1日目"]
    assert "0日目" not in told and "恋鐘の" not in told
    assert HER_BIRTHDAY in told and "今天是制作人的生日" in told
