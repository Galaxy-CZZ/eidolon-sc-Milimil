"""`eidolon eval moments`: the moments eval set's scenarios written by the chat model as the
background loop has her write them, from what each scenario gives her, no database read; each
run's moment or reply, its picture's prompt as it would be sent, and the parts made do
without, marked, written into a page for the maintainer to read, and summed up on one line.
Nothing passes or fails: only the command going wrong exits non-zero."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from eidolon.characters import Character, load_characters
from eidolon.llm import LLMError
from eidolon.moment_eval import (
    MomentEval,
    MomentEvalError,
    evaluate,
    load_moment_eval,
    render_html,
    summary_line,
)
from eidolon.moment_prompt import JOBS_OPENING, WANTS_TO_POST
from eidolon.place_pool import load_place_pool, places_path
from tests.conftest import KOGANE_SHEET, MANO_PHOTO, MANO_SHEET, Admin, CharacterConfig
from tests.fakes import FakeLLM
from tests.test_moment_group_photos import HIORI_BOX, HIORI_PHOTO, MANO_BOX
from tests.test_moments import FACTS

REPO = Path(__file__).parents[2]

EVAL = """
[[post]]
id = "work-with-hiori"
about = "工作那条，允许合照"
character = "mano"
tier = "close"
at = 2026-11-03T19:40:00+09:00
producer = { address = "P さん", birthday = "11-03", timezone = "Asia/Tokyo" }
today = ["今天是日本的节假日：文化の日。制作人提起再说，不用主动提。"]
weather = { kind = "rain", temperature = 12 }
jobs = ["杂志拍摄：秋季特辑的外景", "广播录音：和灯织一起的节目"]
memories = [{ text = "制作人最近在学做饭", on = 2026-10-28 }]
recent = [{ ja = "公園でひなたぼっこ", note = "公园的长椅" }]
circle = ["hiori", "kogane"]
places = ["koenji-azuma-dori", "shibuya-center-gai"]
compositions = ["scenery", "posed", "group"]

[[post]]
id = "everyday-kogane"
about = "日常那条，纯文字"
character = "kogane"
at = 2026-11-04T12:10:00+09:00
seeds = ["家人：长崎的老家", "兴趣：做饭", "学校：已经毕业"]
memories = [{ text = "制作人周末回了趟老家", on = 2026-11-02 }]
circle = ["mano"]

[[reply]]
id = "kawaii"
about = "他只写了「かわいい」"
character = "mano"
tier = "intimate"
at = 2026-11-03T21:00:00+09:00
history = [{ user = "今天辛苦了" }, { ja = "[softly]ありがとうございます", zh = "谢谢您" }]
moment = { ja = "今日は撮影でした", note = "和灯织在咖啡店" }
likes = ["hiori"]
comments = [{ from = "kogane", ja = "真乃、よかね！" }]
liked = true
comment = "かわいい"
"""

GOOD = """\
<post><ja>[happily]撮影とラジオ、ほわっ…がんばりました</ja><zh>拍摄和广播，都努力了</zh></post>
<image>
composition: group
with: hiori
framing: upper body
place: cafe, indoors
outfit: coat
action: smile
note: 和灯织在咖啡店
</image>
<place>shibuya-center-gai</place>
<likes>kogane</likes>
<comment from="hiori"><ja>おつかれさま、真乃</ja><zh>辛苦了，真乃</zh></comment>
"""

LONG = "あ" * 101
CHATTY = "い" * 41
BAD = f"""\
<post><ja>{LONG}</ja><zh>很长</zh></post>
<image>
composition: candid
place: street
action: walking
note: 走在路上
</image>
<place>harajuku</place>
<likes>kogane, rin</likes>
<comment from="kogane"><ja>{CHATTY}</ja><zh>很长的评论</zh></comment>
<comment from="hiori"><ja>おつかれ</ja></comment>
"""


@pytest.fixture
def characters(tmp_path: Path) -> CharacterConfig:
    """Mano, her facts on Hiori among them, and Hiori, both with photo tags; Kogane, without."""
    return (
        CharacterConfig(tmp_path / "characters")
        .add("mano", "櫻木真乃", MANO_SHEET, birthday="04-25", facts=FACTS, photo=MANO_PHOTO)
        .add("hiori", "風野灯織", "# 人设\n你是風野灯織。\n# 口癖\n「真乃」", birthday="02-02",
             photo=HIORI_PHOTO)
        .add("kogane", "月岡恋鐘", KOGANE_SHEET, birthday="02-25")
    )


@pytest.fixture
def config(characters: CharacterConfig) -> dict[str, Character]:
    return load_characters(characters.path)


def write(tmp_path: Path, text: str, name: str = "moments.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def load(tmp_path: Path, config: dict[str, Character], characters: CharacterConfig, text: str):
    places = load_place_pool(places_path(characters.path), config)
    return load_moment_eval(write(tmp_path, text), config, places, None)


async def test_each_scenario_is_asked_as_the_background_loop_asks_and_marked_for_the_reader(
    tmp_path: Path, config: dict[str, Character], characters: CharacterConfig
):
    moment_eval = load(tmp_path, config, characters, EVAL)
    llm = FakeLLM(
        [GOOD], [BAD],  # her work moment, twice
        LLMError("对话模型返回 502"), ["<post><ja>よかね</ja></post>"],  # Kogane's
        ["<ja>[softly]えへへ…ありがとうございます</ja><zh>嘿嘿……谢谢您</zh>"], ["好的"],  # the reply
    )
    done: list[str] = []

    results = await evaluate(moment_eval, llm, runs=2, progress=done.append, at_a_time=1)

    # What she is given is the scenario's, asked as the background loop asks it.
    work = llm.prompts[0]
    told = work[2].content
    assert "现在是 2026年11月3日（星期二）19:40（东京时间）" in told
    assert "东京这会儿的天气：雨，12°C。" in told and "文化の日" in told
    assert JOBS_OPENING in told and "- 杂志拍摄：秋季特辑的外景" in told
    assert "- 制作人最近在学做饭（2026年10月28日，制作人对你说的）" in told
    assert "公園でひなたぼっこ（配图：公园的长椅）" in told
    # Dated where the producer is, Asia/Shanghai when the scenario does not say.
    assert "- 制作人周末回了趟老家（2026年11月2日，制作人对你说的）" in llm.prompts[2][2].content
    assert "## hiori：風野灯織（能一起合照）" in told
    assert "illumination STARS 的伙伴" in told  # what her facts say of Hiori
    assert "- koenji-azuma-dori：" in told and "group" in told
    assert work[-1].content == WANTS_TO_POST and len(work) == 4
    assert "制作人的生日是11月3日" in work[1].content
    reply = llm.prompts[4]
    assert reply[-1].content.endswith("かわいい")
    assert [m.content for m in reply[2:4]] == [
        "今天辛苦了", "<ja>[softly]ありがとうございます</ja><zh>谢谢您</zh>"
    ]
    assert "赞：風野灯織" in reply[-2].content and "- 月岡恋鐘：真乃、よかね！" in reply[-2].content
    assert sorted(done) == ["everyday-kogane", "kawaii", "work-with-hiori"]

    [(_, (good, bad)), (_, (failed, unread))] = results.posts
    assert good.post is not None and good.post.ja == "撮影とラジオ、ほわっ…がんばりました"
    assert good.post.place is not None and good.post.place.id == "shibuya-center-gai"
    assert good.post.likes == ["kogane", "hiori"]
    assert good.flags == ("合照里的 風野灯織 没写进赞（补上了）",) and good.over == ()
    assert good.image is not None and good.image.size == (1216, 832)
    assert good.image.positive.startswith("2girls, idolmaster shiny colors, side-by-side")
    assert good.image.characters == (MANO_BOX, HIORI_BOX)

    assert bad.post is not None and bad.post.place is None and bad.image is None
    assert set(bad.flags) == {
        "地点写坏了，不带地名（写的是 harajuku）",
        "配图写坏了，改发纯文字（构图 candid 不在这次允许的里）",
        "赞的名单里有 1 个不在圈子里，丢掉了（rin）",
        "1 条评论坏了（缺字幕，或者作者不在圈子里），丢掉了",
    }
    assert set(bad.over) == {"正文 101 字，超过 100", "月岡恋鐘的评论 41 字，超过 40"}

    assert failed.failed and failed.error is not None and "502" in failed.error
    assert unread.failed and unread.flags == ("没有能发的正文（缺 <post>、日语或字幕）",)
    [(_, (replied, nothing))] = results.replies
    assert replied.said == ("えへへ…ありがとうございます", "嘿嘿……谢谢您")
    assert nothing.failed

    assert summary_line(results) == (
        "发动态 4 条：失败 2，有降级 1，超字数 1；回评论 2 条：失败 1"
    )
    page = render_html(results, "deepseek-flash", 2, datetime(2026, 11, 5, 10, 0))
    assert "deepseek-flash" in page and "每个场景 2 遍" in page
    assert "撮影とラジオ、ほわっ…がんばりました" in page and "辛苦了，真乃" in page
    assert "side-by-side" in page and f"角色框：{HIORI_BOX}" in page
    assert "构图 candid 不在这次允许的里" in page and "正文 101 字，超过 100" in page
    assert "502" in page and "えへへ…ありがとうございます" in page
    assert "没有能发的回复" in page
    assert "&lt;post&gt;" in page  # what the model wrote, as it wrote it, escaped


async def test_a_moment_with_no_picture_to_have_says_so_of_one_written(
    tmp_path: Path, config: dict[str, Character], characters: CharacterConfig
):
    moment_eval = load(tmp_path, config, characters, EVAL)
    plain = moment_eval.posts[1]
    llm = FakeLLM([
        "<post><ja>よかね</ja><zh>不错</zh></post>\n<image>composition: food</image>\n"
        "<place>none</place><likes>櫻木真乃</likes>"
    ])

    results = await evaluate(
        MomentEval((plain,), ()), llm, progress=lambda _: None
    )

    [(_, (run,))] = results.posts
    assert run.post is not None and run.post.likes == ["mano"] and run.image is None
    assert run.flags == ("这次不带图，却写了 <image>（没读）",)
    assert "<image>" not in llm.prompts[0][2].content


async def test_a_picture_no_one_is_in_shows_gpt_images_prompt_beside_its_tags(
    tmp_path: Path, config: dict[str, Character], characters: CharacterConfig
):
    moment_eval = load(tmp_path, config, characters, EVAL)
    work = moment_eval.posts[0]
    llm = FakeLLM(["""\
<post><ja>雨の渋谷</ja><zh>下雨的涩谷</zh></post>
<image>
composition: scenery
place: street, rain
action: umbrella, crosswalk
note: 雨里的中心街
</image>
<place>shibuya-center-gai</place><likes>kogane</likes>"""])

    results = await evaluate(
        MomentEval((work,), ()), llm, progress=lambda _: None, gpt_style="Cel style."
    )
    page = render_html(results, "m", 1, datetime(2026, 11, 3, tzinfo=UTC))

    [(_, (run,))] = results.posts
    assert run.image is not None and run.gpt is not None
    assert run.gpt.size == (1216, 832)
    lines = run.gpt.text.splitlines()
    assert lines[0] == "Cel style." and lines[1].startswith("Subject: scenery")
    assert "What the picture shows (follow this): 雨里的中心街" in run.gpt.text
    assert "Details: street, rain, umbrella, crosswalk" in run.gpt.text
    assert "When: November, night, rainy." in run.gpt.text  # 19:40 in Tokyo
    assert "GPT Image 提示词 · 1216×832" in page
    assert "Cel style." in page


SCENARIO = """
[[post]]
id = "a"
about = "日常"
character = "mano"
at = 2026-11-04T12:10:00+09:00
seeds = ["兴趣：公园"]
"""


@pytest.mark.parametrize(
    "text, error",
    [
        (SCENARIO + SCENARIO, "场景 a 重复"),
        (SCENARIO.replace('character = "mano"', 'character = "rin"'), "rin"),
        (SCENARIO.replace('seeds = ["兴趣：公园"]', ""), "jobs"),
        (SCENARIO + 'jobs = ["拍摄：外景"]\n', "只写一样"),
        (SCENARIO + 'tier = "cold"\n', "tier"),
        (SCENARIO.replace("+09:00", ""), "时区"),
        (SCENARIO + 'places = ["nowhere"]\n', "nowhere"),
        (SCENARIO + 'circle = ["mano"]\n', "她自己"),
        (SCENARIO + 'compositions = ["portrait"]\n', "portrait"),
        (SCENARIO + 'compositions = ["group"]\ncircle = ["kogane"]\n', "合照"),
        (SCENARIO + 'compositions = ["group"]\ncircle = ["hiori"]\nnovelai = false\n', "合照"),
        (SCENARIO.replace('character = "mano"', 'character = "kogane"')
         + 'compositions = ["selfie"]\n', "无人"),
        (SCENARIO + 'weather = { kind = "hail", temperature = 3 }\n', "weather"),
        (SCENARIO + 'cycle = "late"\n', "cycle"),
        (SCENARIO + 'producer = { birthday = "13-01" }\n', "MM-DD"),
        (SCENARIO + 'memories = [{ text = "x" }]\n', "memories"),
        (SCENARIO + 'mood = "happy"\n', "mood"),
        ("[[reply]]\nid = \"b\"\nabout = \"x\"\ncharacter = \"mano\"\n"
         "at = 2026-11-04T12:10:00+09:00\ncomment = \"かわいい\"\n", "moment"),
        ("[[post", "格式"),
    ],
)
def test_a_malformed_set_is_refused(
    tmp_path: Path, config: dict[str, Character], characters: CharacterConfig,
    text: str, error: str,
):
    with pytest.raises(MomentEvalError, match=error):
        load(tmp_path, config, characters, text)


def test_the_committed_set_has_the_scenarios_the_maintainer_reads():
    """Twelve moments and six replies, of five or six idols, on the repository's characters,
    place pool and world setting."""
    from eidolon.world import load_world, world_path

    characters_path = REPO / "characters" / "characters.toml"
    characters = load_characters(characters_path)
    moment_eval = load_moment_eval(
        REPO / "backend" / "eval" / "moments.toml", characters,
        load_place_pool(places_path(characters_path), characters),
        load_world(world_path(characters_path)),
    )

    assert len(moment_eval.posts) == 12 and len(moment_eval.replies) == 6
    idols = {c.material.character.id for c in (*moment_eval.posts, *moment_eval.replies)}
    assert len(idols) >= 5
    assert any("group" in c.material.compositions for c in moment_eval.posts)
    assert any(c.material.jobs for c in moment_eval.posts)
    assert any(not c.material.compositions for c in moment_eval.posts)


def deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.setenv("CHAT_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("CHAT_LLM_MODEL", "deepseek-chat")
    monkeypatch.delenv("NOVELAI_API_KEY", raising=False)


def test_the_command_writes_the_page_and_sums_the_run_up_on_one_line(
    tmp_path: Path, characters: CharacterConfig, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    deployed(monkeypatch)
    llm = FakeLLM([BAD])
    opened: list[str] = []

    def open_llm(settings):
        opened.append(settings.model)
        return llm

    monkeypatch.setattr("eidolon.llm.providers.open_llm", open_llm)
    scenarios = write(tmp_path, EVAL[: EVAL.index("[[post]]\nid = \"everyday")])
    page = tmp_path / "moments.html"
    admin = Admin(tmp_path / "eidolon.db", capsys)

    out = admin.run(
        "eval", "moments", "--html", str(page), "--file", str(scenarios),
        "--characters", str(characters.path), "--model", "deepseek-flash",
    )

    # Made do without and too long, it still exits 0: nothing passes or fails.
    assert "发动态 1 条：失败 0，有降级 1，超字数 1；回评论 0 条：失败 0" in out
    assert str(page) in out
    assert opened == ["deepseek-flash"]
    assert "构图 candid 不在这次允许的里" in page.read_text(encoding="utf-8")
    assert not (tmp_path / "eidolon.db").exists()


def test_the_command_fails_only_when_it_cannot_run(
    tmp_path: Path, characters: CharacterConfig, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    deployed(monkeypatch)
    admin = Admin(tmp_path / "eidolon.db", capsys)
    page = str(tmp_path / "moments.html")
    scenarios = str(write(tmp_path, SCENARIO))

    assert "场景 a 重复" in admin.fails(
        "eval", "moments", "--html", page, "--file", str(write(tmp_path, SCENARIO * 2, "twice.toml")),
        "--characters", str(characters.path),
    )
    monkeypatch.delenv("CHAT_LLM_API_KEY")
    assert "CHAT_LLM_API_KEY" in admin.fails(
        "eval", "moments", "--html", page, "--file", scenarios,
        "--characters", str(characters.path),
    )
