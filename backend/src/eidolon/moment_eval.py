"""`eidolon eval moments`: her moments and her replies to the producer's comments on them
(GLOSSARY.md「朋友圈」), written by the chat model for the scenarios of the moments eval set
(`eval/moments.toml`), for the maintainer to read.

Each scenario writes all she is given, made up rather than of the story (ADR-0003): no
database is read or made. A moment's scenario has her, her tier, where her cycle has her, the
time, what the day is in Tokyo (`today_lines`, as written), the weather, her jobs done or
three entries of her facts, her memories, her latest moments, her circle, the places she may
be at, and the compositions her picture may be in, if it may have one, on NovelAI or not.
A reply's has the moment, its note, the comments of her circle shown, whether he liked it,
the latest turns, and his comment. Both are asked and read as the background loop asks and
reads them (`moment_prompt`); a picture is never generated, its prompt is written out
instead, cleaned as it would be sent; of one no one is in, GPT Image's too
(`gpt_image_prompt`), at the scenario's time, weather and place, any missing left out.

Nothing passes or fails: what can be counted is marked for the reader (`PostRun.flags`, the
parts made do without and why; `PostRun.over`, what is longer than she is told), and summed
up on one line (`summary_line`); whether it reads as her is the reader's to say."""

import asyncio
import html
import re
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, get_args
from zoneinfo import ZoneInfo

from eidolon.affinity import Tier, affinity_prompt
from eidolon.characters import Character
from eidolon.cycles import cycle_lines
from eidolon.her_cycle import HerDay, Period, Premenstrual
from eidolon.llm import ChatLLM, ChatMessage
from eidolon.memory import Memory, posting_memories_prompt
from eidolon.moment_prompt import (
    BROKEN_COMMENT,
    COMMENTS_OVER,
    COMPOSITION_NAMES,
    IMAGE,
    LIKES_OVER,
    NO_LIKES,
    NONE,
    OUTSIDE_LIKER,
    PLACE,
    WITH,
    Member,
    Post,
    PostMaterial,
    ReplyMaterial,
    parse_post,
    parse_reply,
    post_prompt,
    recalled,
    reply_prompt,
)
from eidolon.config import DEFAULT_GPT_IMAGE_STYLE
from eidolon.gpt_image_prompt import GptPrompt, gpt_picture_prompt
from eidolon.moments import relations, said_to_chat, written_whole
from eidolon.photo_prompt import (
    UNPEOPLED,
    Composition,
    ImagePrompt,
    picture_prompt,
    read_picture,
    tag_fields,
)
from eidolon.place_pool import Place
from eidolon.producer import (
    Birthday,
    ProducerProfile,
    effective_timezone,
    is_day_of_the_year,
    is_timezone,
    local_date,
    posting_now_prompt,
)
from eidolon.store import Message, Segment
from eidolon.weather import Kind, Weather
from eidolon.world import World

POSTING_TIERS: tuple[Tier, ...] = ("trust", "close", "intimate")
"""The tiers she posts and replies in."""

TIER_NAMES: dict[Tier, str] = {"trust": "信任", "close": "亲近", "intimate": "亲密"}

POST_MOST, COMMENT_MOST = 100, 40
"""How many characters her moment, and a comment on it, are told to keep within."""

AT_A_TIME = 4
"""How many scenarios are asked at once."""

DEGRADED = {
    PLACE: "地点写坏了，不带地名",
    IMAGE: "配图写坏了，改发纯文字",
    WITH: "合照的人不对，降成她一个人的摆拍",
    NO_LIKES: "没写赞的名单，当没人赞",
    OUTSIDE_LIKER: "赞的名单里有 {n} 个不在圈子里，丢掉了",
    BROKEN_COMMENT: "{n} 条评论坏了（缺字幕，或者作者不在圈子里），丢掉了",
    LIKES_OVER: "赞多写了 {n} 个，截掉了",
    COMMENTS_OVER: "评论多写了 {n} 条，截掉了",
}
"""How each part made do without is marked, by how `Post.degraded` names it."""


class MomentEvalError(RuntimeError):
    """The eval set is missing or wrongly written."""


@dataclass(frozen=True)
class PostCase:
    """A moment's scenario: what it is about, and all she is given."""

    id: str
    about: str
    tier: Tier
    material: PostMaterial
    novelai: bool
    at: datetime | None = None
    """When she posts, for GPT Image's prompt."""
    weather: Weather | None = None


@dataclass(frozen=True)
class ReplyCase:
    """A reply's scenario: what it is about, and all she is given."""

    id: str
    about: str
    tier: Tier
    material: ReplyMaterial


@dataclass(frozen=True)
class MomentEval:
    posts: tuple[PostCase, ...]
    replies: tuple[ReplyCase, ...]


def load_moment_eval(
    path: Path,
    characters: Mapping[str, Character],
    places: Sequence[Place],
    world: World | None,
) -> MomentEval:
    """The set at `path`, its characters and places checked against `characters` and
    `places`, the world setting as `world` has it (None for none)."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise MomentEvalError(f"找不到朋友圈评测集 {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise MomentEvalError(f"朋友圈评测集 {path} 格式有误：{e}") from None
    if unknown := data.keys() - {"post", "reply"}:
        raise MomentEvalError(f"朋友圈评测集里有不认识的项 {'、'.join(sorted(unknown))}")
    ids: set[str] = set()
    by_id = {p.id: p for p in places}
    posts = tuple(
        _post(_Scenario(entry, _POST_FIELDS, ids, characters, world), entry, by_id)
        for entry in _list(data, "post", "朋友圈评测集")
    )
    replies = tuple(
        _reply(_Scenario(entry, _REPLY_FIELDS, ids, characters, world), entry)
        for entry in _list(data, "reply", "朋友圈评测集")
    )
    return MomentEval(posts, replies)


_SHARED = {"id", "about", "character", "tier", "at", "producer", "cycle", "today", "memories"}
_POST_FIELDS = _SHARED | {
    "weather", "birthday", "jobs", "seeds", "recent", "circle", "places", "compositions",
    "novelai",
}
_REPLY_FIELDS = _SHARED | {"history", "moment", "likes", "comments", "liked", "comment"}


class _Scenario:
    """What moments' and replies' scenarios have in common, read and checked."""

    def __init__(
        self,
        entry: Any,
        fields: set[str],
        ids: set[str],
        characters: Mapping[str, Character],
        world: World | None,
    ) -> None:
        if not isinstance(entry, dict):
            raise MomentEvalError("朋友圈评测集的每个场景应为一张表")
        self.id = _text(entry, "id", "朋友圈评测集的场景")
        self.where = f"场景 {self.id} "
        if self.id in ids:
            raise MomentEvalError(f"场景 {self.id} 重复")
        ids.add(self.id)
        if unknown := entry.keys() - fields:
            raise MomentEvalError(f"{self.where}里有不认识的项 {'、'.join(sorted(unknown))}")
        self.about = _text(entry, "about", self.where)
        self.characters = characters
        self.character = self.idol(_text(entry, "character", self.where), "character")
        tier = entry.get("tier", "trust")
        if tier not in POSTING_TIERS:
            raise MomentEvalError(
                f"{self.where}的 tier 只能是 {'、'.join(POSTING_TIERS)}，而不是 {tier}"
            )
        self.tier: Tier = tier
        at = entry.get("at")
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise MomentEvalError(f"{self.where}的 at 应为带时区的时间，例如 2026-11-03T19:40:00+09:00")
        self.at = at
        self.profile = self._profile(entry.get("producer", {}))
        self.timezone = effective_timezone(self.profile, None)
        self.world_prompt = (
            world.prompt(self.character.name, local_date(at, self.timezone))
            if world is not None else None
        )
        self.her_day = self._her_day(entry.get("cycle"))
        self.today = _strings(entry, "today", self.where)
        self.memories = self._memories(entry)

    def idol(self, id: Any, field: str) -> Character:
        if not isinstance(id, str) or id not in self.characters:
            raise MomentEvalError(f"{self.where}的 {field} 里的角色 {id} 不在角色配置里")
        return self.characters[id]

    def now(self, weather: Weather | None, replying: bool) -> list[str]:
        """What she knows of now, as `HerNow.lines` gives it on the `moments` occasion."""
        felt = affinity_prompt(self.tier, None)
        return [
            posting_now_prompt(self.profile, self.at, self.timezone, felt, weather, replying),
            *self.today,
            *cycle_lines(self.her_day),
        ]

    def _profile(self, entry: Any) -> ProducerProfile:
        where = f"{self.where}的 producer"
        if not isinstance(entry, dict):
            raise MomentEvalError(f"{where}应为一张表")
        if unknown := entry.keys() - {"address", "gender", "birthday", "timezone"}:
            raise MomentEvalError(f"{where}里有不认识的项 {'、'.join(sorted(unknown))}")
        birthday = None
        if (written := entry.get("birthday")) is not None:
            found = re.fullmatch(r"(\d\d)-(\d\d)", written) if isinstance(written, str) else None
            if found is None or not is_day_of_the_year(int(found[1]), int(found[2])):
                raise MomentEvalError(f"{where}的 birthday 应写成 MM-DD，而不是 {written}")
            birthday = Birthday(int(found[1]), int(found[2]))
        gender = entry.get("gender")
        if gender not in (None, "male", "female"):
            raise MomentEvalError(f"{where}的 gender 只能是 male 或 female")
        timezone = entry.get("timezone")
        if timezone is not None and not (isinstance(timezone, str) and is_timezone(timezone)):
            raise MomentEvalError(f"{where}的 timezone {timezone} 不是时区")
        address = entry.get("address")
        if address is not None and not isinstance(address, str):
            raise MomentEvalError(f"{where}的 address 应为字符串")
        return ProducerProfile(address or None, gender, timezone, birthday)

    def _her_day(self, cycle: Any) -> HerDay:
        if cycle is None:
            return None
        if cycle == "period":
            return Period(1, 5, self.at.date())
        if cycle == "premenstrual":
            return Premenstrual(2)
        raise MomentEvalError(f"{self.where}的 cycle 只能是 period 或 premenstrual，而不是 {cycle}")

    def _memories(self, entry: dict) -> str | None:
        memories = []
        for i, m in enumerate(_list(entry, "memories", self.where)):
            if not isinstance(m, dict) or m.keys() != {"text", "on"} or not isinstance(
                m["on"], date
            ) or isinstance(m["on"], datetime):
                raise MomentEvalError(
                    f"{self.where}的 memories 每一条应为 {{ text = \"…\", on = 2026-10-20 }}"
                )
            text = _text(m, "text", f"{self.where}的记忆")
            # Told that day where the producer is, as the prompt dates it.
            told = datetime.combine(m["on"], datetime.min.time(), ZoneInfo(self.timezone))
            memories.append(Memory(
                i, "eval", self.character.id, self.character.name, text, told.isoformat()
            ))
        return (
            posting_memories_prompt(memories, self.character, self.timezone) if memories else None
        )


def _post(scenario: _Scenario, entry: dict, places: Mapping[str, Place]) -> PostCase:
    where = scenario.where
    weather = None
    if (written := entry.get("weather")) is not None:
        if (
            not isinstance(written, dict) or written.keys() != {"kind", "temperature"}
            or written["kind"] not in get_args(Kind)
            or not isinstance(written["temperature"], int)
        ):
            raise MomentEvalError(
                f"{where}的 weather 应为 {{ kind = \"rain\", temperature = 12 }}，"
                f"kind 是 {'、'.join(get_args(Kind))} 之一"
            )
        weather = Weather(written["kind"], written["temperature"])
    birthday = entry.get("birthday", False)
    novelai = entry.get("novelai", True)
    if not isinstance(birthday, bool) or not isinstance(novelai, bool):
        raise MomentEvalError(f"{where}的 birthday 和 novelai 应为 true 或 false")
    jobs, seeds = _strings(entry, "jobs", where), _strings(entry, "seeds", where)
    if bool(jobs) == bool(seeds):
        raise MomentEvalError(f"{where}要写 jobs（工作那条）或 seeds（日常那条），只写一样")
    recent = []
    for r in _list(entry, "recent", where):
        if not isinstance(r, dict) or not r.keys() <= {"ja", "note"} or "ja" not in r:
            raise MomentEvalError(f"{where}的 recent 每一条应为 {{ ja = \"…\", note = \"…\" }}")
        recent.append(recalled(_text(r, "ja", where), r.get("note")))
    circle = [scenario.idol(id, "circle") for id in _strings(entry, "circle", where)]
    if scenario.character in circle or len({c.id for c in circle}) < len(circle):
        raise MomentEvalError(f"{where}的 circle 里有她自己，或者有人写了两次")
    related = relations(scenario.character, {c.id: c for c in circle})
    candidates = []
    for id in _strings(entry, "places", where):
        if id not in places:
            raise MomentEvalError(f"{where}的地点 {id} 不在地点池里")
        candidates.append(places[id])
    compositions = _strings(entry, "compositions", where)
    for c in compositions:
        if c not in COMPOSITION_NAMES:
            raise MomentEvalError(
                f"{where}的构图 {c} 不认识，只能是 {'、'.join(COMPOSITION_NAMES)}"
            )
    if not scenario.character.photographed and set(compositions) - set(UNPEOPLED):
        raise MomentEvalError(f"{where}：{scenario.character.id} 没配外貌，只能写无人的构图")
    if "group" in compositions and not (novelai and any(c.photographed for c in circle)):
        raise MomentEvalError(
            f"{where}：合照只在 NovelAI 形态、圈子里有人配齐了外貌时允许"
        )
    material = PostMaterial(
        scenario.character, scenario.world_prompt, scenario.profile,
        scenario.now(weather, replying=False), birthday, seeds, scenario.memories, recent,
        candidates, jobs, [Member(c, related.get(c.id)) for c in circle],
        compositions,  # pyright: ignore[reportArgumentType]  # checked above
    )
    return PostCase(
        scenario.id, scenario.about, scenario.tier, material, novelai, scenario.at, weather
    )


def _reply(scenario: _Scenario, entry: dict) -> ReplyCase:
    where = scenario.where
    history: list[ChatMessage] = []
    for i, said in enumerate(_list(entry, "history", where)):
        if isinstance(said, dict) and said.keys() == {"user"} and isinstance(said["user"], str):
            message = Message(i, "user", said["user"], None, None, "")
        elif (
            isinstance(said, dict) and said.keys() == {"ja", "zh"}
            and all(isinstance(v, str) and v for v in said.values())
        ):
            ja, zh = said["ja"], said["zh"]
            message = Message(i, "character", None, ja, zh, "", [Segment(ja, zh)])
        else:
            raise MomentEvalError(
                f"{where}的 history 每一条应为 {{ user = \"…\" }} 或 {{ ja = \"…\", zh = \"…\" }}"
            )
        history.append(said_to_chat(message))
    moment = entry.get("moment")
    if not isinstance(moment, dict) or not moment.keys() <= {"ja", "note"} or "ja" not in moment:
        raise MomentEvalError(f"{where}的 moment 应为 {{ ja = \"…\", note = \"…\" }}")
    likes = [scenario.idol(id, "likes").name for id in _strings(entry, "likes", where)]
    comments = []
    for c in _list(entry, "comments", where):
        if not isinstance(c, dict) or c.keys() != {"from", "ja"}:
            raise MomentEvalError(f"{where}的 comments 每一条应为 {{ from = \"…\", ja = \"…\" }}")
        comments.append((scenario.idol(c["from"], "comments").name, _text(c, "ja", where)))
    liked = entry.get("liked", False)
    if not isinstance(liked, bool):
        raise MomentEvalError(f"{where}的 liked 应为 true 或 false")
    material = ReplyMaterial(
        scenario.character, scenario.world_prompt, scenario.profile, history,
        scenario.now(None, replying=True), scenario.memories,
        recalled(_text(moment, "ja", where), moment.get("note")), likes, comments, liked,
        _text(entry, "comment", where),
    )
    return ReplyCase(scenario.id, scenario.about, scenario.tier, material)


def _text(entry: dict, field: str, where: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MomentEvalError(f"{where}缺少 {field}")
    return value


def _list(entry: dict, field: str, where: str) -> list:
    value = entry.get(field, [])
    if not isinstance(value, list):
        raise MomentEvalError(f"{where}的 {field} 应为列表")
    return value


def _strings(entry: dict, field: str, where: str) -> list[str]:
    value = _list(entry, field, where)
    if not all(isinstance(v, str) and v.strip() for v in value):
        raise MomentEvalError(f"{where}的 {field} 应为字符串列表")
    return value


@dataclass(frozen=True)
class PostRun:
    """One run of a moment's scenario: what the model wrote (None if it failed, `error`
    saying why), what was read of it (None for nothing to post), its picture's prompts as they
    would be sent (None for no picture), GPT Image's for one no one is in (None for none), the
    parts made do without and why (`flags`), and what is longer than she is told (`over`)."""

    written: str | None
    error: str | None = None
    post: Post | None = None
    image: ImagePrompt | None = None
    flags: tuple[str, ...] = ()
    over: tuple[str, ...] = ()
    gpt: GptPrompt | None = None

    @property
    def failed(self) -> bool:
        return self.post is None


@dataclass(frozen=True)
class ReplyRun:
    """One run of a reply's scenario: what the model wrote (None if it failed, `error` saying
    why), and her reply read from it (None for none)."""

    written: str | None
    error: str | None = None
    said: tuple[str, str] | None = None

    @property
    def failed(self) -> bool:
        return self.said is None


@dataclass(frozen=True)
class MomentResults:
    posts: tuple[tuple[PostCase, tuple[PostRun, ...]], ...]
    replies: tuple[tuple[ReplyCase, tuple[ReplyRun, ...]], ...]


async def evaluate(
    moment_eval: MomentEval,
    llm: ChatLLM,
    runs: int = 1,
    style: str = "",
    progress: Callable[[str], None] = lambda _: None,
    at_a_time: int = AT_A_TIME,
    gpt_style: str = DEFAULT_GPT_IMAGE_STYLE,
) -> MomentResults:
    """Every scenario of `moment_eval` asked of `llm` `runs` times, `at_a_time` at once, its
    pictures' prompts in the art style `style`, GPT Image's in `gpt_style`; `progress` told
    each scenario's id as it is done."""
    turns = asyncio.Semaphore(at_a_time)

    async def written(prompt: list[ChatMessage]) -> tuple[str | None, str | None]:
        async with turns:
            try:
                return await written_whole(llm.stream(prompt)), None
            except Exception as e:
                return None, f"{type(e).__name__}: {e}"

    async def post(case: PostCase) -> tuple[PostCase, tuple[PostRun, ...]]:
        prompt = post_prompt(case.material)
        done = await asyncio.gather(*(written(prompt) for _ in range(runs)))
        progress(case.id)
        return case, tuple(
            check_post(text, case.material, style, case, gpt_style) if text is not None
            else PostRun(None, error)
            for text, error in done
        )

    async def reply(case: ReplyCase) -> tuple[ReplyCase, tuple[ReplyRun, ...]]:
        prompt = reply_prompt(case.material)
        done = await asyncio.gather(*(written(prompt) for _ in range(runs)))
        progress(case.id)
        return case, tuple(
            ReplyRun(text, error, parse_reply(text) if text is not None else None)
            for text, error in done
        )

    posts = await asyncio.gather(*(post(case) for case in moment_eval.posts))
    replies = await asyncio.gather(*(reply(case) for case in moment_eval.replies))
    return MomentResults(tuple(posts), tuple(replies))


_IMAGE = re.compile(r"<image>(.*?)</image>", re.DOTALL)
_LIKES = re.compile(r"<likes>(.*?)</likes>", re.DOTALL)
_PLACE = re.compile(r"<place>(.*?)</place>", re.DOTALL)


def check_post(
    written: str,
    material: PostMaterial,
    style: str = "",
    case: PostCase | None = None,
    gpt_style: str = DEFAULT_GPT_IMAGE_STYLE,
) -> PostRun:
    """What `written` posts as she was given `material`, read as the background loop reads it,
    its picture's prompts in the art style `style`, and marked for the reader; of a picture no
    one is in, GPT Image's prompt in `gpt_style` too, at the time and weather of `case`."""
    post = parse_post(written, material)
    if post is None:
        return PostRun(written, flags=("没有能发的正文（缺 <post>、日语或字幕）",))
    names = _names(material)
    likes = _LIKES.search(written)
    listed = [n for n in re.split(r"[\s,，、`]+", likes[1] if likes else "") if n]
    flags: list[str] = []
    for name, count in post.degraded.items():
        flag = DEGRADED[name].format(n=count)
        if name == PLACE:
            at = _PLACE.search(written)
            flag += f"（写的是 {at[1].strip()}）" if at else "（没写 <place>）"
        if name == IMAGE:
            flag += f"（{_why_no_picture(written, material)}）"
        if name == OUTSIDE_LIKER:
            flag += f"（{'、'.join(n for n in listed if n not in names and n != NONE)}）"
        flags.append(flag)
    image = _IMAGE.search(written)
    if not material.compositions and image is not None:
        flags.append("这次不带图，却写了 <image>（没读）")
    picture = gpt = None
    if post.picture is not None:
        picture = picture_prompt(material.character, post.picture.tag, style)
        if post.picture.tag.composition in UNPEOPLED and case is not None and case.at:
            gpt = gpt_picture_prompt(
                post.picture.tag, post.picture.note, post.place, case.at, case.weather, gpt_style
            )
        written_likes = {names.get(name, name) for name in listed}
        for other in post.picture.tag.others:
            if other.id not in written_likes:
                flags.append(f"合照里的 {other.name} 没写进赞（补上了）")
    over = []
    if len(post.ja) > POST_MOST:
        over.append(f"正文 {len(post.ja)} 字，超过 {POST_MOST}")
    for comment in post.comments:
        if len(comment.ja) > COMMENT_MOST:
            name = _member_name(material, comment.character_id)
            over.append(f"{name}的评论 {len(comment.ja)} 字，超过 {COMMENT_MOST}")
    return PostRun(written, None, post, picture, tuple(flags), tuple(over), gpt)


def _names(material: PostMaterial) -> dict[str, str]:
    """Each name of her circle may be written by, to the identifier."""
    return {
        name: m.character.id
        for m in material.circle
        for name in (m.character.id, m.character.name, m.character.short_name) if name
    }


def _member_name(material: PostMaterial, id: str) -> str:
    return next((m.character.name for m in material.circle if m.character.id == id), id)


def _why_no_picture(written: str, material: PostMaterial) -> str:
    image = _IMAGE.search(written)
    if image is None:
        return "没写 <image>"
    fields = tag_fields(image[1])
    written = fields.get("composition", "").strip()
    if not written:
        return "没写 composition"
    # Read as if every composition were allowed, by the same parser: one it reads is one
    # not allowed this time; one it does not, unknown, or an object with nothing in it.
    read = read_picture(fields, tuple(COMPOSITION_NAMES))
    if read is None:
        return f"构图写的是 {written}：不认识，或者物品的 action 是空的"
    composition = "group" if read.alone_instead else read.composition
    if composition not in material.compositions:
        return f"构图 {composition} 不在这次允许的里"
    return "读不了"


def summary_line(results: MomentResults) -> str:
    """The one line the run is summed up in."""
    posts = [run for _, runs in results.posts for run in runs]
    replies = [run for _, runs in results.replies for run in runs]
    return (
        f"发动态 {len(posts)} 条：失败 {sum(r.failed for r in posts)}，"
        f"有降级 {sum(bool(r.post.degraded) for r in posts if r.post is not None)}，"
        f"超字数 {sum(bool(r.over) for r in posts)}；"
        f"回评论 {len(replies)} 条：失败 {sum(r.failed for r in replies)}"
    )


def render_html(results: MomentResults, model: str, runs: int, at: datetime) -> str:
    """The page the maintainer reads the run on: each scenario, what she was given, and each
    run's moment or reply, the parts made do without marked."""
    page = [
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
        "<title>朋友圈评测</title><style>", _STYLE, "</style></head><body>",
        "<h1>朋友圈评测</h1>",
        f"<p class=\"meta\">模型 {_e(model)} · 每个场景 {runs} 遍 · {at:%Y-%m-%d %H:%M}</p>",
        f"<p class=\"summary\">{_e(summary_line(results))}</p>",
        "<h2>发动态</h2>",
    ]
    for case, post_runs in results.posts:
        page.append(_post_section(case, post_runs))
    page.append("<h2>回评论</h2>")
    for case, reply_runs in results.replies:
        page.append(_reply_section(case, reply_runs))
    page.append("</body></html>")
    return "\n".join(page)


_STYLE = """
body { font-family: system-ui, sans-serif; max-width: 920px; margin: 2em auto; padding: 0 1em;
  line-height: 1.6; color: #222; }
section { border-top: 2px solid #ccc; margin-top: 2em; padding-top: .5em; }
.meta { color: #666; font-size: .9em; }
.summary { font-weight: bold; }
.run { margin: 1em 0 1em 1em; padding-left: 1em; border-left: 3px solid #e3e3e3; }
.ja { font-size: 1.1em; margin: .2em 0; }
.zh { color: #555; margin: .2em 0; }
.flags li, .flag { color: #b00020; }
pre { white-space: pre-wrap; background: #f6f6f6; padding: .6em; font-size: .85em; }
ul.comments { list-style: none; padding-left: 0; }
ul.comments li { margin: .4em 0; }
"""


def _post_section(case: PostCase, runs: Sequence[PostRun]) -> str:
    material = case.material
    picture = (
        "带图：" + "、".join(material.compositions)
        + ("（NovelAI 形态）" if case.novelai else "（OpenAI 形态）")
        if material.compositions else "纯文字"
    )
    told = post_prompt(material)[2].content
    parts = [
        f"<section id=\"{_e(case.id)}\"><h3>{_e(case.id)} · {_e(case.about)}</h3>",
        f"<p class=\"meta\">{_e(material.character.name)} · {TIER_NAMES[case.tier]}"
        f" · {_e(picture)} · 圈子 {len(material.circle)} 人 · 地点候选 {len(material.places)} 个</p>",
        f"<details><summary>给她的素材</summary><pre>{_e(told)}</pre></details>",
    ]
    for i, run in enumerate(runs, 1):
        parts.append(f"<div class=\"run\"><h4>第 {i} 遍</h4>")
        if run.written is None:
            parts.append(f"<p class=\"flag\">模型出错：{_e(run.error or '')}</p></div>")
            continue
        post = run.post
        if post is not None:
            parts += [
                f"<p class=\"ja\">{_e(post.ja)}</p><p class=\"zh\">{_e(post.zh)}</p>",
                f"<p class=\"meta\">{len(post.ja)} 字 · 地点："
                + (_e(f"{post.place.name}（{post.place.id}）") if post.place else "不带地名")
                + "</p>",
            ]
            likes = "、".join(_member_name(material, id) for id in post.likes) or "没人"
            parts.append(f"<p>赞：{_e(likes)}</p>")
            if post.comments:
                parts.append("<ul class=\"comments\">")
                for c in post.comments:
                    parts.append(
                        f"<li><b>{_e(_member_name(material, c.character_id))}</b>"
                        f"（{len(c.ja)} 字） {_e(c.ja)}<br><span class=\"zh\">{_e(c.zh)}</span></li>"
                    )
                parts.append("</ul>")
            if post.picture is not None and run.image is not None:
                composition: Composition = post.picture.tag.composition
                parts.append(
                    f"<p>配图：{_e(composition)}（{_e(COMPOSITION_NAMES[composition])}）"
                    f"· {run.image.size[0]}×{run.image.size[1]} · note：{_e(post.picture.note)}</p>"
                    f"<pre>{_e(run.image.positive)}</pre>"
                )
                for box in run.image.characters:
                    parts.append(f"<pre>角色框：{_e(box)}</pre>")
                if run.gpt is not None:
                    parts.append(
                        f"<p>GPT Image 提示词 · {run.gpt.size[0]}×{run.gpt.size[1]}</p>"
                        f"<pre class=\"gpt\">{_e(run.gpt.text)}</pre>"
                    )
        if run.flags or run.over:
            parts.append(
                "<ul class=\"flags\">" + "".join(f"<li>{_e(f)}</li>" for f in (*run.flags, *run.over))
                + "</ul>"
            )
        parts.append(
            f"<details><summary>模型原文</summary><pre>{_e(run.written)}</pre></details></div>"
        )
    parts.append("</section>")
    return "\n".join(parts)


def _reply_section(case: ReplyCase, runs: Sequence[ReplyRun]) -> str:
    material = case.material
    turns = "\n".join(
        f"{'制作人' if m.role == 'user' else material.character.name}：{m.content}"
        for m in material.history
    )
    told = f"# 最后几个回合\n{turns}\n\n{reply_prompt(material)[-2].content}"
    parts = [
        f"<section id=\"{_e(case.id)}\"><h3>{_e(case.id)} · {_e(case.about)}</h3>",
        f"<p class=\"meta\">{_e(material.character.name)} · {TIER_NAMES[case.tier]}"
        f" · 历史 {len(material.history)} 条</p>",
        f"<p>他的评论：{_e(material.comment)}</p>",
        f"<details><summary>给她的素材</summary><pre>{_e(told)}</pre></details>",
    ]
    for i, run in enumerate(runs, 1):
        parts.append(f"<div class=\"run\"><h4>第 {i} 遍</h4>")
        if run.written is None:
            parts.append(f"<p class=\"flag\">模型出错：{_e(run.error or '')}</p></div>")
            continue
        if run.said is not None:
            ja, zh = run.said
            parts.append(
                f"<p class=\"ja\">{_e(ja)}</p><p class=\"zh\">{_e(zh)}</p>"
                f"<p class=\"meta\">{len(ja)} 字</p>"
            )
        else:
            parts.append("<ul class=\"flags\"><li>没有能发的回复（缺日语或字幕）</li></ul>")
        parts.append(
            f"<details><summary>模型原文</summary><pre>{_e(run.written)}</pre></details></div>"
        )
    parts.append("</section>")
    return "\n".join(parts)


def _e(text: str) -> str:
    return html.escape(text, quote=True)

