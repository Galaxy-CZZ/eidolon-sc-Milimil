"""Her circle (GLOSSARY.md「朋友圈」): the other idols who like and comment on her moment,
written with it and shown later, each at a time of its own. She is told of each she may have:
what her facts say of her, and how she speaks (her sheet's 「自称」「对他人的称呼」「口癖」);
she names them by identifier, and the backend knows them by name and short name too. Those
not in her circle are left out, as is a comment without its Japanese or its subtitle, and as
many over as there may be; a list of likes not written is no one's. Each that is made do
without is recorded.

Driven as `test_moments.py` drives moments (`SteadyRandom(0)`: her circle as small as it is,
one of another unit in it, the likes 5 minutes after, the comments 15), with a world of Mano's
unit, with Hiori in it, and of Kogane's (`write_world`), and Hazuki the clerk, who is in no
one's circle."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from eidolon.characters import Character
from eidolon.config import Settings
from eidolon.moment_prompt import (
    LIKES,
    LIKES_OVER,
    POST_RULES,
    Member,
    PostMaterial,
    parse_post,
)
from eidolon.producer import Birthday, ProducerProfile
from tests.conftest import KOGANE_SHEET, MANO_SHEET, CharacterConfig, ClientFactory
from tests.fakes import context_of
from tests.test_admin_users import ADMIN
from tests.test_moment_places import degraded
from tests.test_moments import POST, SEVEN, START, talked, tick, timeline
from tests.test_world_setting import section, write_world

HIORI_SHEET = """# 人设：風野灯織

## 身份
你是風野灯織。

## 自称
「私」。

## 对他人的称呼
真乃是「真乃」。

## 口癖
「もう……」

## 硬性规则
不说英语。
"""

FACTS = """\
# 人物关系
## 制作人
真乃信赖制作人。
## 風野灯織
同组合的伙伴，真乃叫她「灯織ちゃん」。
## 七草はづき
事务所的事务员。
## 其他偶像
和大家都处得好。
# 兴趣
喜欢在公园晒太阳。
"""

NOWHERE = [*POST, "<place>none</place>"]

LIKED_AND_COMMENTED = [
    *NOWHERE,
    "<likes>hiori, 月岡恋鐘</likes>",
    '<comment from="灯織"><ja>[softly] 真乃、気持ちよさそう</ja><zh>真乃，看起来好舒服</zh></comment>',
    '<comment from="kogane"><ja>うちも行きたか～！</ja><zh>咱也想去～！</zh></comment>',
]


SOMEONE = Character("mano", "櫻木真乃", "", "voice", "sheet", None, "#ffbad6", Birthday(4, 25), 16)


@pytest.fixture
def characters(tmp_path: Path) -> CharacterConfig:
    """Mano, with facts on Hiori and Hazuki; Hiori, in her unit; Kogane, in another; Hazuki,
    the clerk."""
    config = (
        CharacterConfig(tmp_path / "characters")
        .add("mano", "櫻木真乃", MANO_SHEET, birthday="04-25", facts=FACTS)
        .add("hiori", "風野灯織", HIORI_SHEET, birthday="02-02", short_name="灯織")
        .add("kogane", "月岡恋鐘", KOGANE_SHEET, birthday="02-25")
        .add("hazuki", "七草はづき", "# 人设\n你是七草はづき。", birthday="02-03")
    )
    write_world(config)
    return config


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, moments=True, admins=frozenset({ADMIN}))


def circle_of(moment: dict) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Who has liked the moment, and who has commented on it with what, as shown."""
    return moment["likes"], [(c["character_id"], c["ja"], c["zh"]) for c in moment["comments"]]


async def test_she_is_told_of_her_circle_what_her_facts_say_of_each_and_how_each_speaks(
    make_client: ClientFactory, settings: Settings
):
    client, llm, clock, _ = await talked(make_client, LIKED_AND_COMMENTED)

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    posting = llm.prompts[-1]
    told = context_of(posting)
    circle = section(told, "# 圈子成员")
    assert told.index("# 圈子成员") < told.index("# 地点候选")
    assert "挑 1 到 6 位来赞，0 到 3 位来评论" in circle
    assert "## kogane：月岡恋鐘" in circle and "## hiori：風野灯織" in circle
    hiori = circle[circle.index("## hiori") :]
    assert "同组合的伙伴，真乃叫她「灯織ちゃん」。" in hiori
    assert "「私」。" in hiori and "真乃是「真乃」。" in hiori and "「もう……」" in hiori
    assert "你是風野灯織" not in circle and "不说英语" not in circle
    assert "hazuki" not in circle  # the clerk, though Mano's facts are on her
    assert POST_RULES in posting[0].content


async def test_likes_and_comments_show_on_the_timeline_as_their_times_come(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, _ = await talked(make_client, LIKED_AND_COMMENTED)
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    shown: list[tuple[list[str], list[tuple[str, str, str]]]] = []
    second = timedelta(seconds=1)
    for after in (timedelta(), timedelta(minutes=5) - second, timedelta(minutes=5),
                  timedelta(minutes=15) - second, timedelta(minutes=15)):
        clock.now = SEVEN + after
        [moment] = await timeline(client)
        shown.append(circle_of(moment))

    assert shown[:4] == [([], []), ([], []), (["hiori", "kogane"], []), (["hiori", "kogane"], [])]
    assert shown[4] == (["hiori", "kogane"], [
        ("hiori", "真乃、気持ちよさそう", "真乃，看起来好舒服"),
        ("kogane", "うちも行きたか～！", "咱也想去～！"),
    ])
    assert degraded(settings.database_path) == [None]


def comment(by: str, ja: str = "いいね", zh: str | None = "不错") -> str:
    subtitle = f"<zh>{zh}</zh>" if zh is not None else ""
    return f'<comment from="{by}"><ja>{ja}</ja>{subtitle}</comment>'


@pytest.mark.parametrize(
    ("written", "likes", "comments", "made_do_without"),
    [
        ("<likes>hiori、hazuki、めぐる</likes>", ["hiori"], [], {"liker": 2}),
        ("<likes>none</likes>", [], [], None),
        (comment("hiori"), [], ["hiori"], {"likes": 1}),
        ("<likes>kogane</likes>" + comment("hiori", zh=None) + comment("kogane"),
         ["kogane"], ["kogane"], {"comment": 1}),
        ("<likes>kogane</likes>" + comment("hazuki") + comment("hiori", ja=""),
         ["kogane"], [], {"comment": 2}),
        ("<likes>kogane</likes>" + comment("hiori") + comment("kogane", "よか") * 3,
         ["kogane"], ["hiori", "kogane", "kogane"], {"comments_over": 1}),
    ],
)
async def test_those_not_in_her_circle_broken_comments_and_as_many_over_are_left_out(
    make_client: ClientFactory,
    settings: Settings,
    written: str,
    likes: list[str],
    comments: list[str],
    made_do_without: dict | None,
):
    client, _, clock, _ = await talked(make_client, [*NOWHERE, written])
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    clock.now = SEVEN + timedelta(minutes=15)
    [moment] = await timeline(client)

    shown_likes, shown_comments = circle_of(moment)
    assert (shown_likes, [by for by, *_ in shown_comments]) == (likes, comments)
    assert degraded(settings.database_path) == [made_do_without]


async def test_on_her_birthday_more_are_in_her_circle_and_may_comment(
    make_client: ClientFactory, settings: Settings, characters: CharacterConfig
):
    """Mano's birthday, April 25 in Tokyo: of her circle of 8, as many as there are, all
    may like, and 6 comment."""
    for i in range(6):
        characters.add(f"idol{i}", f"偶像{i}", "# 人设", birthday="01-01")
    write_world(characters, [
        ("櫻木真乃", "illumination STARS", "関根瞳"),
        ("風野灯織", "illumination STARS", "近藤玲奈"),
        ("月岡恋鐘", "L'Antica", "礒部花凜"),
        *((f"偶像{i}", "L'Antica", "") for i in range(6)),
    ])
    start = START.replace(month=4, day=24)
    seven = SEVEN.replace(month=4, day=24)
    everyone = ["hiori", "kogane", *(f"idol{i}" for i in range(6))]
    written = f"<likes>{','.join(everyone)}</likes>" + comment("hiori") * 7
    client, llm, clock, _ = await talked(make_client, [*NOWHERE, written], at=start)

    await tick(client, clock, start)
    await tick(client, clock, seven)
    clock.now = seven + timedelta(minutes=15)
    [moment] = await timeline(client)

    circle = section(context_of(llm.prompts[-1]), "# 圈子成员")
    assert "挑 1 到 10 位来赞，0 到 6 位来评论" in circle
    assert sorted(moment["likes"]) == sorted(everyone)
    assert len(moment["comments"]) == 6
    assert degraded(settings.database_path) == [{"comments_over": 1}]


def test_likes_over_as_many_as_are_kept_are_left_out_the_last_first():
    """Not met with on a moment, her circle as many as may like it but on the parts of a
    group photo yet to come; read as the eval reads it."""
    circle = [
        Member(replace(SOMEONE, id=f"idol{i}", name=f"偶像{i}")) for i in range(LIKES + 1)
    ]
    material = PostMaterial(SOMEONE, None, ProducerProfile(), [], False, [], None, [],
                            circle=circle)
    written = "".join(NOWHERE) + f"<likes>{','.join(m.character.id for m in circle)}</likes>"

    post = parse_post(written, material)

    assert post is not None
    assert post.likes == [f"idol{i}" for i in range(LIKES)]
    assert post.degraded == {LIKES_OVER: 1}
