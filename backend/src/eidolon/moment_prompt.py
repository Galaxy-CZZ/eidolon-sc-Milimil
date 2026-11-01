"""What she is asked as she posts a moment (GLOSSARY.md「朋友圈」「动态」), and what is read of
what she writes: from material put together beforehand, reading nothing, so that the
background loop, which reads it from the database, and the eval, which has it written,
take the same prompt and the same parser.

The prompt is laid out as a turn's (ADR-0020): her character sheet and the world setting as
every turn has them, word for word, the turn's format replaced with how to post
(`POST_RULES`); who the producer is; no history; then, in a system message of its own, what
she is to know as she posts (`PostMaterial`); and where the user's words would be, that she
wants to post (`WANTS_TO_POST`).

She writes the whole of it before it is read, not streamed: her post, in Japanese with its
Chinese subtitle, `<post><ja>…</ja><zh>…</zh></post>`. Either missing, it fails. Delivery
cues are left out of both, but for what else is in brackets: her kaomoji are hers to post.
Then where she is, `<place>…</place>`: one of the places she was given (`PostMaterial.places`)
by its identifier, or none. One she was not given, or none written where she was given any,
is made do without: the moment has no place, none drawn in its stead, and it is told
(`Post.degraded`, `PLACE`).

She is told of her circle (`PostMaterial.circle`), those who may like and comment on her
moment: each by identifier and name, what her facts say of her, and how she speaks (her
sheet's sections in `SPEAKS`). She writes who likes it, `<likes>…</likes>`, and each comment,
in the order they show, `<comment from="…"><ja>…</ja><zh>…</zh></comment>`, naming them by
identifier, though their names and short names will do. Each part is made do without on its
own, and told: a list of likes not written is no one's (`NO_LIKES`); one not in her circle
is left out (`OUTSIDE_LIKER`), as is a comment by one, or without its Japanese or its subtitle
(`BROKEN_COMMENT`); those over as many as `LIKES` and `COMMENTS`, or on her birthday
`BIRTHDAY_LIKES` and `BIRTHDAY_COMMENTS`, are left out, the last first (`LIKES_OVER`,
`COMMENTS_OVER`).

Where her moment may have a picture (GLOSSARY.md「配图」), she is told last in what compositions
(`PostMaterial.compositions`, `COMPOSITIONS_OPENING`), and writes it as a photo tag is written,
`<image>…</image>`, its composition among its fields, and a note in Chinese of what is in it,
never sent to NovelAI (GPT Image is sent it, `gpt_image_prompt`): kept with the moment, what her latest moments are recalled by (`recalled`). One
not written, in a composition she was not given, of an object with nothing in it, or that
cannot be read, is made do without: the moment is posted without a picture, and it is told
(`IMAGE`). One she writes where she was not told she may is not read. A framing not of its
composition is not made do without: it is from the waist up.

Where it may be a group photo, she is told which of her circle may be in it with her (those
with photo tags, `GROUP_MARK`), and names them in `with`. One with no one named, or one not of
them, is a posed photo of her alone instead, and it is told (`WITH`). Whoever is in it with her
likes her moment, written so or not, and is never one of those over as many as are kept.

Her reply to the producer's comment on her moment is asked as her reaching out is
(`reply_prompt`): her character sheet and the world setting; who the producer is; the latest
turns of her current conversation; then, in a system message of its own, what she knows of
now on the `moments` occasion, replying, the memories she replies with, her moment, the likes
and comments of her circle that have shown, whether he has liked it, and how to reply
(`REPLY_RULES`); and where the user's words would be, his comment, as he wrote it
(`COMMENTED`): they are his words. She writes one Japanese line with its subtitle,
`<ja>…</ja><zh>…</zh>`, delivery cues left out (`parse_reply`); either missing, it fails."""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from eidolon.characters import Character, parse_facts
from eidolon.delivery_cues import without_written_cues
from eidolon.llm import ChatMessage
from eidolon.photo_prompt import Composition, PictureTag, read_picture, tag_fields
from eidolon.place_pool import Place
from eidolon.producer import ProducerProfile, producer_prompt
from eidolon.today import always_known

POST_RULES = """# 发朋友圈
你在发一条朋友圈动态，事务所的同伴、朋友和制作人都看得到。
- 用日语写一到三句、最多一百字左右，像随手发的一条近况，再附上中文字幕。
- 表情和颜文字按你自己的性格：平时爱用就用，不爱用就不用。
- 不用 # 话题标签，不用 @，不加语气提示。
- 有「今天做完的工作」时，把这几项串成一条写；「日常的素材」可用可不用。
- 换个话题，别和「你最近发的朋友圈」重复。
- 关于制作人的记忆只能隐约呼应，不要复述；他私下告诉你的事不要点明。
- 可以提到「プロデューサーさん」，但关系再亲近也不写成情侣的口吻。
- 「此刻」里没写天气时，正文别提天气和冷热。
- 地点只能从「地点候选」里挑一个，写它的 id；在家、在宿舍，或者候选里没有合适的，写 none。
- 正文里提不提地名随你，要提就用日语自然地写。
- 标了「你的卡面在这里拍过」的候选，只借那里的景，不说「这是我那张卡拍的地方」。
- 「圈子成员」里的人会来赞、来评论，人数照那一节说的；名单里只写她们的 id。
- 每条评论用评论的人自己的口吻（照她的自称、称呼和口癖），一两句、最多四十字左右，日语加中文字幕。
- 评论只回应正文和配图里写出来的东西（配图看你写的 note），以及她和你之间的关系；没写的事不提，不对制作人说话。
- 评论按出现的先后写，后面的可以顺着前面的接一句。
- 有「这次允许的构图」时带一张配图。正文不依赖配图，配图没发出来也读得通。
- 工作那条从做完的几项里挑一项来配图。
- 写街景时写站在地面能看到的东西（sidewalk、power lines、vending machine、storefront、crosswalk 一类），只写 street, dusk 会画成从高处俯瞰。
- 风景、食物、物品的 action 写景物、食物或物品，不是动作；outfit、framing 不用写。
- 摆拍和抓拍可以选 wide shot：人小景大，适合在名胜、街景前。
- 合照想拍成自拍，就在 action 里写 selfie；不写就是别人帮你们拍。
- 只输出下面的格式，不写别的：
<post><ja>日语正文</ja><zh>中文字幕</zh></post>
<image>配图标签</image>（只在有「这次允许的构图」时写）
<place>候选的 id 或 none</place>
<likes>来赞的人的 id，用逗号隔开</likes>
<comment from="评论的人的 id"><ja>日语</ja><zh>中文字幕</zh></comment>（一条评论一个，没人评论就不写）"""
"""How she is to post, in place of the turn's format."""

WANTS_TO_POST = "（你想发一条朋友圈。）"
"""Where the user's words would be as she posts."""

REPLY_RULES = """# 回评论
制作人在你这条朋友圈下面评论了，你在评论区回他一句。
- 用日语写一两句，评论区里随手回的口吻，再附上中文字幕。
- 别重复别人评论里已经说过的话。
- 评论区大家都看得到：关系再亲近也不写成情侣的口吻，他私下告诉你的事不要点明。
- 不发照片，也不说要给他发照片。
- 不加语气提示。
- 只输出下面的格式，不写别的：
<ja>日语</ja><zh>中文字幕</zh>"""
"""How she is to reply to the producer's comment on her moment, told her last."""

COMMENTED = "（制作人在你这条动态下面评论：）"
"""Where the user's words would be as she replies to his comment, before them."""

REPLIED_MOMENT = "# 你这条朋友圈"
REPLIED_CIRCLE = "# 大家的赞和评论"
NO_ONE_YET = "还没有别人赞或评论。"
LIKED_BY = "赞："
PRODUCER_LIKED = "制作人赞了这条。"
PRODUCER_NOT_LIKED = "制作人没有赞这条。"

HER_BIRTHDAY = "今天是你的生日，这条围绕你的生日写。"
"""What she is told on her birthday, in Tokyo, beside what the day tells her."""

JOBS_OPENING = "# 今天做完的工作\n制作人今天给你排的、你都做完了："
SEEDS_OPENING = "# 日常的素材\n下面是你资料里的几条，可以拿来当由头，也可以不用："
RECENT_OPENING = "# 你最近发的朋友圈\n最新的在前："
CIRCLE_OPENING = "# 圈子成员\n下面这几位会看到这条动态。挑 1 到 {likes} 位来赞，0 到 {comments} 位来评论："
NO_CIRCLE = "# 圈子成员\n这次没有人会来，<likes> 留空，不写 <comment>。"
PLACES_OPENING = "# 地点候选\n你这会儿可能在下面某一处，也可能哪儿都没去："
NO_PLACES = "# 地点候选\n这次没有候选，写 none。"
COMPOSITIONS_OPENING = """\
# 这次允许的构图
这条动态带一张配图，写在 <post> 后面，一行一栏，比如：
<image>
composition: posed
framing: upper body
place: park, autumn leaves, outdoors, day
outfit: coat, scarf
action: peace sign, smile
note: 在公园的银杏树下请人帮我拍的
</image>
- composition 只能从下面选一个："""
_FRAMING = "- framing：只在有你的构图里写。selfie 选 portrait 或 upper body；posed、candid 选 portrait、upper body、cowboy shot、full body、wide shot{group}。"
_FIELDS = """\
- place：1–4 个英文 tag，写地点、室内还是室外、时段或天气、光线。
- outfit：1–4 个英文 tag，写一套衣服，只写这个景别里看得见的{group}。
- action：有你的构图写 2–4 个英文 tag，一个动作、一两个表情，抓拍写正在做的事；没有人的构图写 1–3 个景物、食物或物品。"""
_LAST = """\
- note：一句中文，写这张图拍了什么。
- 画面里只有你一个人，或者没有人{group}；不写发色、瞳色、发型、身材，也不写画风或画师。全年龄，和发照片的规矩一样。"""
COMPOSITIONS_CLOSING = "\n".join(
    (_FRAMING.format(group=""), _FIELDS.format(group=""), _LAST.format(group=""))
)
GROUP_CLOSING = "\n".join((
    _FRAMING.format(group="；group 自拍选 portrait 或 upper body，别人帮你们拍选 upper body 或 cowboy shot"),
    _FIELDS.format(group="；group 里大家穿这一套"),
    "- with：只在 group 里写，「圈子成员」里标了「能一起合照」的 1–2 位的 id，用逗号隔开。",
    _LAST.format(group="；group 里是你和 with 里的人"),
))
"""What she is told of the picture her moment may have, after its compositions: without a
group photo among them, and with one."""

COMPOSITION_NAMES: dict[Composition, str] = {
    "scenery": "风景，没有人",
    "food": "食物，没有人",
    "object": "物品，没有人",
    "selfie": "你的自拍",
    "posed": "别人帮你拍，你看着镜头",
    "candid": "别人趁你不注意抓拍，你不看镜头",
    "group": "和圈子里的一两位合照，自拍或者别人帮你们拍",
}
"""What each composition is, as she is told."""

GROUP_MARK = "（能一起合照）"
"""What marks one of her circle she may be in a group photo with."""

RELATION = "你资料里关于她的："
"""What opens what her facts say of one of her circle."""

SPEAKS = (("自称", "她的自称："), ("对他人的称呼", "她对他人的称呼："), ("口癖", "她的口癖："))
"""The sections of the sheet of one of her circle she is told, by heading, and what opens
each."""

LIKES, COMMENTS = 6, 3
"""How many likes and comments are kept at most."""

BIRTHDAY_LIKES, BIRTHDAY_COMMENTS = 10, 6
"""How many likes and comments are kept at most on her birthday."""

HOLY_SITE = "（你的卡面在这里拍过）"
"""What marks a place she is given that is her holy site."""

NONE = "none"
"""What she writes for being at none of the places."""

PLACE = "place"
"""What `Post.degraded` names a place made do without by."""

IMAGE = "image"
"""What `Post.degraded` names a picture made do without by."""

WITH = "with"
"""What `Post.degraded` names a group photo made a photo of her alone by."""

NO_LIKES = "likes"
"""What `Post.degraded` names a list of likes not written by."""

OUTSIDE_LIKER = "liker"
"""What `Post.degraded` names one liking it who is not in her circle by."""

BROKEN_COMMENT = "comment"
"""What `Post.degraded` names a comment by one not in her circle, or broken, by."""

LIKES_OVER, COMMENTS_OVER = "likes_over", "comments_over"
"""What `Post.degraded` names likes and comments over as many as are kept by."""

PICTURE_FALLBACK = "picture_fallback"
"""What a moment's record names, beside `Post.degraded`, a picture no one is in that GPT
Image did not generate by, image generation tried instead (`moments`)."""


@dataclass(frozen=True)
class Member:
    """One of her circle, and what her facts say of her, the section on her without its
    heading (None for none)."""

    character: Character
    relation: str | None = None


@dataclass(frozen=True)
class PostMaterial:
    """What she posts a moment with: her sheet and the world setting (`world_prompt`, None
    without one); the producer's profile; what she knows of now (`HerNow.lines`, on the
    `moments` occasion); whether it is her birthday; the entries of her facts drawn for her
    everyday (`seeds`); the memories she posts with, as their prompt section
    (`Memories.for_reaching_out`, None for none); her latest moments, the latest first,
    as she recalls them (`recalled`); the places she may be at; of her work moment, her
    jobs done that day, each its name and what it is, in the order done, in place of seeds;
    her circle; and the compositions her moment's picture may be in, none for no picture."""

    character: Character
    world_prompt: str | None
    profile: ProducerProfile
    now: Sequence[str]
    birthday: bool
    seeds: Sequence[str]
    memories: str | None
    recent: Sequence[str]
    places: Sequence[Place] = ()
    jobs: Sequence[str] = ()
    circle: Sequence[Member] = ()
    compositions: Sequence[Composition] = ()


@dataclass(frozen=True)
class ReplyMaterial:
    """What she replies to the producer's comment on her moment with: her sheet and the world
    setting (`world_prompt`, None without one); the producer's profile; the latest turns of her
    current conversation, as the chat model reads them; what she knows of now (`HerNow.lines`,
    on the `moments` occasion, replying); the memories she replies with, as their prompt
    section (None for none); her moment, as she recalls it (`recalled`); who of her circle has
    liked it so far, by name, in the order they showed, and their comments, each its name and
    Japanese; whether he has liked it; and his comment, as he wrote it."""

    character: Character
    world_prompt: str | None
    profile: ProducerProfile
    history: Sequence[ChatMessage]
    now: Sequence[str]
    memories: str | None
    moment: str
    likes: Sequence[str]
    comments: Sequence[tuple[str, str]]
    liked: bool
    comment: str


@dataclass(frozen=True)
class Picture:
    """The picture she wrote for her moment: as read, the fields she wrote it in, as she
    wrote them, its composition among them as read, and its note."""

    tag: PictureTag
    written: Mapping[str, str]
    note: str


@dataclass(frozen=True)
class Comment:
    """A comment on her moment by one of her circle, delivery cues left out: in Japanese,
    and its subtitle."""

    character_id: str
    ja: str
    zh: str


@dataclass(frozen=True)
class Post:
    """What she wrote to post, delivery cues left out: in Japanese, and its subtitle; the
    place she was at, of those given, None for none; who of her circle likes it, by
    identifier; the comments on it, in the order they show; its picture, None for none; and
    which parts of what she wrote were made do without, and how many of each."""

    ja: str
    zh: str
    place: Place | None = None
    likes: Sequence[str] = ()
    comments: Sequence[Comment] = ()
    picture: Picture | None = None
    degraded: Mapping[str, int] = field(default_factory=dict)


def recalled(ja: str, note: str | None) -> str:
    """One of her latest moments, as she recalls it: her Japanese, and what its picture is,
    if it had one with a note."""
    return f"{ja}（配图：{note}）" if note else ja


def post_prompt(material: PostMaterial) -> list[ChatMessage]:
    """The prompt she posts a moment with, from `material`."""
    shared = [*always_known(material.character, material.world_prompt), POST_RULES]
    told = ["\n".join(material.now)]
    if material.birthday:
        told.append(HER_BIRTHDAY)
    if material.jobs:
        told.append("\n".join([JOBS_OPENING, *(f"- {job}" for job in material.jobs)]))
    if material.seeds:
        told.append("\n".join([SEEDS_OPENING, *(f"- {seed}" for seed in material.seeds)]))
    if material.memories:
        told.append(material.memories)
    if material.recent:
        told.append("\n".join([RECENT_OPENING, *(f"- {ja}" for ja in material.recent)]))
    group = "group" in material.compositions
    told.append(_circle(material.circle, material.birthday, group))
    told.append(
        "\n".join([PLACES_OPENING, *(_candidate(p, material.character.id) for p in material.places)])
        if material.places else NO_PLACES
    )
    if material.compositions:
        told.append("\n".join([
            COMPOSITIONS_OPENING,
            *(f"  - {c}：{COMPOSITION_NAMES[c]}" for c in material.compositions),
            GROUP_CLOSING if group else COMPOSITIONS_CLOSING,
        ]))
    return [
        ChatMessage("system", "\n\n".join(shared), cache_breakpoint=True),
        ChatMessage("system", producer_prompt(material.profile)),
        ChatMessage("system", "\n\n".join(told)),
        ChatMessage("user", WANTS_TO_POST),
    ]


def reply_prompt(material: ReplyMaterial) -> list[ChatMessage]:
    """The prompt she replies to the producer's comment on her moment with, from `material`."""
    shown = [REPLIED_CIRCLE]
    if material.likes:
        shown.append(LIKED_BY + "、".join(material.likes))
    shown += [f"- {name}：{ja}" for name, ja in material.comments]
    if len(shown) == 1:
        shown.append(NO_ONE_YET)
    told = [
        "\n".join(material.now),
        *([material.memories] if material.memories else []),
        "\n".join([REPLIED_MOMENT, material.moment]),
        "\n".join(shown),
        PRODUCER_LIKED if material.liked else PRODUCER_NOT_LIKED,
        REPLY_RULES,
    ]
    return [
        ChatMessage(
            "system", "\n\n".join(always_known(material.character, material.world_prompt)),
            cache_breakpoint=True,
        ),
        ChatMessage("system", producer_prompt(material.profile)),
        *material.history,
        ChatMessage("system", "\n\n".join(told)),
        ChatMessage("user", COMMENTED + material.comment),
    ]


_REPLY = re.compile(r"<ja>(.*?)</ja>\s*<zh>(.*?)</zh>", re.DOTALL)


def parse_reply(written: str) -> tuple[str, str] | None:
    """Her reply, read from the whole of `written`: the first Japanese line with its subtitle,
    delivery cues left out; None if either is missing."""
    found = _REPLY.search(written)
    if found is None:
        return None
    ja, zh = (without_written_cues(part) for part in found.groups())
    return (ja, zh) if ja and zh else None


def _circle(circle: Sequence[Member], birthday: bool, group: bool) -> str:
    """Her circle as she is told it, and how many of them may like and comment; where her
    picture may be a `group` photo, those who may be in it with her marked."""
    if not circle:
        return NO_CIRCLE
    likes, comments = _most(birthday)
    lines = [CIRCLE_OPENING.format(likes=likes, comments=comments)]
    for member in circle:
        mark = GROUP_MARK if group and member.character.photographed else ""
        lines.append(f"## {member.character.id}：{member.character.name}{mark}")
        if member.relation:
            lines += [RELATION, member.relation]
        sections = sheet_sections(member.character.sheet)
        for heading, opening in SPEAKS:
            if heading in sections:
                lines += [opening, sections[heading]]
    return "\n".join(lines)


def sheet_sections(sheet: str) -> dict[str, str]:
    """What is under each heading of `sheet`, by the heading alone."""
    return {fact.headings[-1]: fact.body for fact in parse_facts(sheet) if fact.headings}


def _candidate(place: Place, character_id: str) -> str:
    """A place she may be at, as she is told it: marked if it is her holy site."""
    holy = HOLY_SITE if place.source is not None and character_id in place.idols else ""
    return f"- {place.id}：{place.name}（{place.area}）{place.note}{holy}"


def _most(birthday: bool) -> tuple[int, int]:
    """How many likes and comments are kept at most, on her birthday or not."""
    return (BIRTHDAY_LIKES, BIRTHDAY_COMMENTS) if birthday else (LIKES, COMMENTS)


_POST = re.compile(r"<post>\s*<ja>(.*?)</ja>\s*<zh>(.*?)</zh>\s*</post>", re.DOTALL)
_PLACE = re.compile(r"<place>(.*?)</place>", re.DOTALL)
_LIKES = re.compile(r"<likes>(.*?)</likes>", re.DOTALL)
_BETWEEN_NAMES = re.compile(r"[\s,，、`]+")
_COMMENT = re.compile(
    r"""<comment\s+from\s*=\s*["']?([^"'>]*?)["']?\s*>(.*?)</comment>""", re.DOTALL
)
_JA = re.compile(r"<ja>(.*?)</ja>", re.DOTALL)
_ZH = re.compile(r"<zh>(.*?)</zh>", re.DOTALL)
_IMAGE = re.compile(r"<image>(.*?)</image>", re.DOTALL)
_WRITTEN = ("composition", "framing", "place", "outfit", "action", "with", "note")
"""The fields of her picture that are kept as she wrote them."""


def parse_post(written: str, material: PostMaterial) -> Post | None:
    """What she wrote to post, read from the whole of `written`, as she was told `material`:
    the places she was given, her circle, whether it is her birthday, the compositions her
    picture may be in. None if it has no post, in Japanese and its subtitle both."""
    found = _POST.search(written)
    if found is None:
        return None
    ja, zh = (without_written_cues(part) for part in found.groups())
    if not ja or not zh:
        return None
    degraded: Counter[str] = Counter()
    at = _PLACE.search(written)
    chosen = at[1].strip() if at else None
    place = next((p for p in material.places if p.id == chosen), None)
    if place is None and chosen != NONE and (chosen is not None or bool(material.places)):
        degraded[PLACE] += 1
    known = {
        name: m.character.id
        for m in material.circle
        for name in (m.character.id, m.character.name, m.character.short_name) if name
    }
    likes: list[str] = []
    listed = _LIKES.search(written)
    if listed is None:
        degraded[NO_LIKES] += 1
    else:
        for name in _BETWEEN_NAMES.split(listed[1]):
            if name in known:
                if known[name] not in likes:
                    likes.append(known[name])
            elif name and name != NONE:
                degraded[OUTSIDE_LIKER] += 1
    comments: list[Comment] = []
    for by, body in _COMMENT.findall(written):
        said = [without_written_cues(f[1]) if (f := tag.search(body)) else "" for tag in (_JA, _ZH)]
        if by.strip() in known and all(said):
            comments.append(Comment(known[by.strip()], *said))
        else:
            degraded[BROKEN_COMMENT] += 1
    picture = None
    if material.compositions:
        idols = [
            m.character.photo_tag for m in (Member(material.character), *material.circle)
            if m.character.photo_tag
        ]
        pictured = [m.character for m in material.circle if m.character.photographed]
        picture = _picture(written, material.compositions, idols, pictured)
        if picture is None:
            degraded[IMAGE] += 1
        elif picture.tag.alone_instead:
            degraded[WITH] += 1
    with_her = [each.id for each in picture.tag.others] if picture is not None else []
    likes += [id for id in with_her if id not in likes]
    most_likes, most_comments = _most(material.birthday)
    if len(likes) > most_likes:
        over = len(likes) - most_likes
        degraded[LIKES_OVER] = over
        cut = [id for id in likes if id not in with_her][-over:]
        likes = [id for id in likes if id not in cut]
    if len(comments) > most_comments:
        degraded[COMMENTS_OVER] = len(comments) - most_comments
    return Post(ja, zh, place, likes, comments[:most_comments], picture, dict(degraded))


def _picture(
    written: str,
    compositions: Sequence[Composition],
    idols: Sequence[str],
    pictured: Sequence[Character],
) -> Picture | None:
    """The picture `written` has, in one of `compositions`, `idols` the character tags of
    those who may be in it, `pictured` those who may be in a group photo with her; None for
    none."""
    found = _IMAGE.search(written)
    if found is None:
        return None
    fields = tag_fields(found[1])
    tag = read_picture(fields, compositions, idols, pictured)
    if tag is None:
        return None
    kept = {name: fields[name] for name in _WRITTEN if name in fields}
    return Picture(tag, {**kept, "composition": tag.composition}, fields.get("note", ""))
