"""Moments (GLOSSARY.md「朋友圈」「动态」): what the characters post to each user's own
moments, of their days, for that user alone to read.

Only where the deployer turns them on (`LiveConfig.moments`), on the deployer's chat model.
Every `TICK` the backend runs what is due (`run_due`): first each user active and not yet
planned for today in Tokyo is planned for, then each moment whose time has come is posted, one
after another in the order of their times.

A user is active who has been in touch with any character within `ACTIVE`: a turn recorded,
or a call that connected ending (`store.read_in_touch`); gifts are not being in touch. Not a
banned user, nor one an admin lets take no turns on the deployer's keys, nor one who has
switched moments off by their own switch (`switch`), on by default. Planned for at the
first tick of the day in Tokyo they are active at, from the rest of the day
(`moment_draws.plan_day`): of the characters they have had a turn with, in trust or above and
not in a cooldown (trust where affinity is off), each drawn for once; as many as the deployer
sets a day at most. One with jobs in the user's schedule done that day in Tokyo, done already
or not yet, posts of them, after the last is done; the others, and one planned too long after
that, of their everyday (`kind`); all of their everyday while schedules are off. Once planned, a user is not again that day: a
character first talked to, or come up to trust, that day waits for the next. The plan is
kept, and read again after a restart.

While the deployer has moments off, nothing is planned nor posted; turned on again, what was
planned is forgotten, and each user planned for anew from what is left of the day. A user
who switches their own off is left as they are planned, and planned for, once on again, as
any other: what is not due yet is posted, and one not yet planned for that day is planned
for from what is left of it. While either has them off, the user's moments are refused them
(`MomentsOff`), kept as they are.

As a moment's time comes, it is looked at again: the deployer still has moments on; the user
is still active, not banned, nor let take no turns; she is in trust or above and not in a
cooldown; the user has had fewer moments of its day than the deployer sets. If not, it is
passed over, for good. One whose time came before the backend started is passed over too,
not made up for. Each is taken off the plan once posted or passed over. One of her jobs whose
time comes as she is still at one, the producer having scheduled her more since, is put off
till after the last as it was planned, past midnight if so, still of the day planned for.

She posts on the deployer's chat model as text turns use it, whoever's LLM the user brings,
held only while she does: nothing counts towards the user's limits. Her prompt is put
together from what is read beforehand (`moment_prompt.PostMaterial`): what she knows of now on
the `moments` occasion; her jobs done that day, each its name and what it is, or else
`SEEDS` entries of her facts; the memories she was told herself, found with the last turn of
her current conversation (`Memories.for_reaching_out`); her latest `RECENT` moments; as many
as `moment_draws.CANDIDATES` places of the pool for her to say she was at one of
(`moment_draws.draw_places`), of her jobs only of the kinds they take her to, only those
under a roof in rain, snow or thunder; Tokyo's weather as she posts (`weather`), kept with the
moment, none if it cannot be had; and, where there is image generation, the compositions her
picture may be in (`moment_draws.draw_compositions`), a group photo among them only in
NovelAI's own format, with those of her circle who have photo tags. Each has an activity record of its own (`moment`), on the
deployer's keys, its service calls under it, and what of it was made do without
(`moment_prompt.Post.degraded`); one the model fails, or writes nothing to post in, is
recorded failed, and not tried again. Her picture is generated first, on the deployer's image
generation, behind every photo waiting (`Photos.picture`), by `PICTURE_TIME_LIMIT` at the
latest, waiting its turn included; one that fails or takes too long is no picture, the moment
posted all the same, and recorded a success. One no one is in is asked of GPT Image first where
the deployer has it besides (`Photos.gpt_picture`), by `GPT_TIME_LIMIT` at the latest; one it
does not give is generated as any other in what time is left, the moment's record saying so
(`moment_prompt.PICTURE_FALLBACK`). What she posts is posted as it is written: that
is when it shows.

She posts it with her circle (`moment_draws.draw_circle`), of the other idols, the office's
staff in no one's: her unit mates, as the world setting has them; those a section of her
facts on the people she knows is on, by their names in its heading (but for those on the
producer and on the other idols, `NOT_ONE`); and the others. Of those she writes like it and
comment on it, each shows at a time of its own (`moment_draws.draw_shown`), whatever comes of
her affinity or her cooldowns after.

The timeline (`timeline`) is the user's moments of the last `KEPT`, the latest first, each
place with a link to it on the map the deployer chooses (`map_link`), each with the likes
and comments of her circle that have shown, in the order they did, and where its picture is
(`picture`): the user's alone to read, as their photos are. Reading it opens the user's
moments; whether a moment, or her reply to his comment, has shown since (`unseen`) lights the
dot on 「朋友圈」, her circle's likes and comments not counted. One who has never opened them
is counted from when first planned for. A moment is kept no longer than `KEPT`: as the backend
tidies up (`forget_old`), it is deleted with its picture, her circle's likes and comments, and
the producer's like and comment, her reply with it, shown or not, whether moments are on or
off; so are the moments planned and missed, once the day they were of in Tokyo is the day
before yesterday. Deleting the user deletes all of their moments (`database.USER_DATA`);
deleting a past conversation none; none goes into a data package.

The producer may like a moment on his timeline, and no longer (`like`): only whether he does
now is kept, she never knows what was. He may comment on it once (`comment`), from 1 to
`COMMENT_LENGTH` characters but for the spaces around them, kept as he wrote it, and delete it (`uncomment`), her
reply with it, then comment again, a comment as any other. As he comments, she is to reply in
her tier, within `moment_draws.REPLY_AFTER` (`draw_reply`), trust where affinity is off; never,
cold to him, distant, or in a cooldown. As her time comes, with the moments due, in the order
of their times, it is looked at again: the deployer and the user still have moments on; she
is not cold, distant or in a cooldown; it did not come before the backend started; she has replied to
fewer of his comments that day in Tokyo than the deployer lets her (`MomentSettings.replies_per_day`), counted by the records of her replies
(`moment_reply`) that succeeded, as a reply deleted with its comment counts still. If not, she
does not, for good, unrecorded. She replies on the deployer's chat model, whoever's LLM the user
brings (`moment_prompt.reply_prompt`), with the memories she was told herself; one the model
fails, or writes no reply in, is recorded failed, and not tried again. Her reply shows as it is
written, unless his comment was deleted meanwhile, when it is recorded rejected. Neither a like,
a comment nor a reply changes her affinity, is remembered, or is being in touch."""

import asyncio
import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import TypeVar
from urllib.parse import quote, urlencode

from eidolon.activity import ActivityLog, read_replied_between
from eidolon.affinity import Affinities, Status, Tier, tier_prompt
from eidolon.characters import Character
from eidolon.clock import Clock
from eidolon.config import MapSite
from eidolon.data_access import Database
from eidolon.engine import chat_history
from eidolon.her_now import HerNow
from eidolon.housekeeping import in_batches
from eidolon.live_config import LiveConfig
from eidolon.llm import ChatMessage, Streamed
from eidolon.memory import Memories, last_turn_query
from eidolon.moment_draws import (
    CHANCES,
    KEPT_APART,
    RELATIONS,
    Eligible,
    Kind,
    Planned,
    draw_circle,
    draw_compositions,
    draw_places,
    draw_reply,
    draw_seeds,
    draw_shown,
    plan_day,
    work_time,
)
from eidolon.gpt_image_prompt import gpt_picture_prompt
from eidolon.image_generation import GPT_TIME_LIMIT, ImageFailed
from eidolon.moment_prompt import (
    PICTURE_FALLBACK,
    Comment,
    Member,
    Picture,
    PostMaterial,
    ReplyMaterial,
    parse_post,
    parse_reply,
    post_prompt,
    recalled,
    reply_prompt,
)
from eidolon.photo_prompt import UNPEOPLED
from eidolon.photos import Photos
from eidolon.place_pool import Place
from eidolon.producer import ProducerProfile, effective_timezone, is_birthday, local_date
from eidolon.randomness import Random
from eidolon.recent_moments import picture_note, read_switched_on
from eidolon.reply_format import format_reply
from eidolon.schedule import DayJob, Schedules
from eidolon.store import (
    Conversation,
    InTouch,
    Message,
    read_current_conversation,
    read_in_touch,
    read_profile,
    read_record,
)
from eidolon.today import TOKYO, tokyo_date, venues_on_this_day
from eidolon.usage import read_user_limits
from eidolon.weather import ALL_KINDS, Weather, Weathers
from eidolon.world import World

log = logging.getLogger(__name__)

_T = TypeVar("_T")

_LIKE, _COMMENT = "like", "comment"
"""The kinds of what `moment_circle` keeps: a like, a comment."""

TICK = timedelta(minutes=1)
"""How often it is looked whose time has come."""

ACTIVE = timedelta(days=7)
"""How recently a user must have been in touch with a character to have moments."""

RECENT = 5
"""How many of her latest moments she is told of, not to post the same again."""

KEPT = timedelta(days=30)
"""How long moments show on the timeline."""

PICTURE_TIME_LIMIT = timedelta(minutes=10)
"""The longest her moment's picture may take, waiting its turn included."""

COMMENT_LENGTH = 140
"""How many characters the producer's comment may have at most, but for the spaces around it."""

NOT_ONE = ("制作人", "プロデューサー", "其他偶像")
"""What is in the heading of a section of her facts on the people she knows that is on no
one of her circle."""

_SCHEMA = """
-- What she posted to a user's moments (GLOSSARY.md「动态」), as shown, delivery cues left out.
-- `image` is how she wrote its picture, as JSON; `place_*` is a copy of the place she was
-- at, so that it shows as it was should the place pool change; `weather` is Tokyo's as she
-- posted it, one of seven, and `temperature` in whole degrees: each NULL without. `day` is
-- the day in Tokyo it was planned for, `posted_at` when it shows.
CREATE TABLE IF NOT EXISTS moments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    character_id TEXT NOT NULL,
    ja TEXT NOT NULL,
    zh TEXT NOT NULL,
    image TEXT,
    place_id TEXT,
    place_name TEXT,
    place_lat REAL,
    place_lon REAL,
    weather TEXT,
    temperature INTEGER,
    day TEXT NOT NULL,
    posted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS moments_by_user ON moments(user_id, posted_at);

-- The moments planned, each till it is posted or passed over: whose, the day in Tokyo it is
-- of, when it is due, whether of her jobs done that day (`work`) or her everyday (`daily`),
-- and whether on her birthday.
CREATE TABLE IF NOT EXISTS moment_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    character_id TEXT NOT NULL,
    day TEXT NOT NULL,
    due_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    birthday INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS moment_plans_by_time ON moment_plans(due_at);

-- Each user's moments as a whole: the latest day in Tokyo planned for, and when they last
-- opened their moments.
CREATE TABLE IF NOT EXISTS moment_users (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    planned_day TEXT,
    opened_at TEXT
);

-- The likes and comments of her circle on a moment (GLOSSARY.md「动态」): whose, a like
-- (`like`) or a comment (`comment`, `kind`), a comment's Japanese and subtitle (NULL for a like), where it is in
-- what she wrote (`position`, from 0, likes and comments each on their own), and when it shows.
CREATE TABLE IF NOT EXISTS moment_circle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    moment_id INTEGER NOT NULL REFERENCES moments(id),
    character_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    ja TEXT,
    zh TEXT,
    position INTEGER NOT NULL,
    shown_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS moment_circle_by_moment ON moment_circle(moment_id, shown_at);

-- The picture of a moment (GLOSSARY.md「配图」), one at most: WebP, nothing but its pixels
-- (ADR-0024).
CREATE TABLE IF NOT EXISTS moment_images (
    moment_id INTEGER PRIMARY KEY REFERENCES moments(id),
    image BLOB NOT NULL
);

-- The producer's like of a moment, while he likes it: none once he no longer does.
CREATE TABLE IF NOT EXISTS moment_likes (
    moment_id INTEGER PRIMARY KEY REFERENCES moments(id)
);

-- The producer's comment on a moment, one at most: what he wrote, when, and her reply to it:
-- when it is due, or showed once written (`reply_at`, NULL where she does not reply), and its
-- Japanese and subtitle, written as it shows.
CREATE TABLE IF NOT EXISTS moment_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    moment_id INTEGER NOT NULL UNIQUE REFERENCES moments(id),
    text TEXT NOT NULL,
    commented_at TEXT NOT NULL,
    reply_at TEXT,
    reply_ja TEXT,
    reply_zh TEXT
);
CREATE INDEX IF NOT EXISTS moment_comments_by_reply ON moment_comments(reply_at);

-- The users who have turned moments off, by their own switch; on for all the others.
CREATE TABLE IF NOT EXISTS moments_off (
    user_id TEXT PRIMARY KEY REFERENCES users(id)
);
"""


class MomentsOff(Exception):
    """The deployer has moments off, or the user their own switch for them."""


class NoMoment(Exception):
    """There is no such moment on the user's timeline: another's, not shown yet, or gone."""


class AlreadyCommented(Exception):
    """The producer has commented on the moment already."""


class CommentInvalid(Exception):
    """The producer's comment is empty, or longer than `COMMENT_LENGTH`."""


@dataclass(frozen=True)
class ShownPlace:
    """A moment's copy of the place she was at: its name and where it is, in WGS-84."""

    name: str
    lat: float
    lon: float


def map_link(site: MapSite, place: ShownPlace) -> str:
    """Where `place` is on the map of `site`, marked, its coordinates as they are (WGS-84):
    none of them needs a key."""
    lat, lon = place.lat, place.lon
    if site == "google":  # Maps URLs
        return "https://www.google.com/maps/search/?" + urlencode(
            {"api": 1, "query": f"{lat},{lon}"}
        )
    if site == "amap":
        return (
            f"https://uri.amap.com/marker?position={lon},{lat}"
            f"&name={quote(place.name)}&coordinate=wgs84"
        )
    return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}"


@dataclass(frozen=True)
class ProducerComment:
    """The producer's comment on a moment: what he wrote, and when, as the database has it."""

    text: str
    commented_at: str

    def shown(self) -> dict:
        return {"text": self.text, "commented_at": self.commented_at}


@dataclass(frozen=True)
class Moment:
    """A moment as the timeline shows it: whose, what she posted, when it showed, where she
    was, as it was then (None for nowhere), Tokyo's weather then (None for none known), who
    of her circle has liked it and commented on it so far, in the order they showed, and
    whether it has a picture; whether the producer likes it, his comment on it (None for
    none), and her reply to that, once it has shown, in Japanese and its subtitle (None
    till then, and for none)."""

    id: int
    character_id: str
    ja: str
    zh: str
    posted_at: str
    place: ShownPlace | None = None
    weather: Weather | None = None
    likes: tuple[str, ...] = ()
    comments: tuple[Comment, ...] = ()
    pictured: bool = False
    liked: bool = False
    producer_comment: ProducerComment | None = None
    reply: tuple[str, str] | None = None

    def shown(self, map_site: MapSite) -> dict:
        """As the browser is told it, its place linked to on `map_site`, its picture by where
        it is read (None for none)."""
        place = (
            {"name": self.place.name, "map": map_link(map_site, self.place)}
            if self.place is not None else None
        )
        return {
            "id": self.id, "character_id": self.character_id, "ja": self.ja, "zh": self.zh,
            "image": f"/api/moments/{self.id}/image" if self.pictured else None, "place": place,
            "weather": self.weather.shown() if self.weather is not None else None,
            "posted_at": self.posted_at,
            "likes": list(self.likes),
            "comments": [
                {"character_id": c.character_id, "ja": c.ja, "zh": c.zh} for c in self.comments
            ],
            "producer_liked": self.liked,
            "producer_comment": (
                self.producer_comment.shown() if self.producer_comment is not None else None
            ),
            "reply": (
                {"ja": self.reply[0], "zh": self.reply[1]} if self.reply is not None else None
            ),
        }


@dataclass(frozen=True)
class _Plan:
    """A moment planned, as `moment_plans` keeps it."""

    id: int
    user_id: str
    character_id: str
    day: date
    due_at: datetime
    birthday: bool
    kind: Kind = "daily"


@dataclass(frozen=True)
class _DueReply:
    """Her reply to the producer's comment, as `moment_comments` keeps it: which comment, on
    whose moment, and when it is due."""

    comment_id: int
    user_id: str
    character_id: str
    due_at: datetime


@dataclass(frozen=True)
class _BeforeReply:
    """What she replies to the producer's comment with, read beforehand in one read: whether
    she is to (whether he has his own switch for moments on; her affinity, None while it is
    off; how many of his comments she has replied to that day); the producer, her current conversation and its messages; her moment, its
    Japanese and its picture as she wrote it (None for none); whether he likes it; and his
    comment."""

    switched_on: bool
    status: Status | None
    replied: int
    profile: ProducerProfile
    conversation: Conversation | None
    messages: list[Message]
    moment_id: int
    ja: str
    image: str | None
    liked: bool
    comment: str


@dataclass(frozen=True)
class _Standing:
    """What is read of a user, at one moment, to tell whether they have moments: whether
    they are active, let take turns and have their own switch on; and her tier with each character they have had a turn
    with, None for one she would post nothing in (in a cooldown, or below trust)."""

    active: bool
    tiers: dict[str, Tier | None]


@dataclass(frozen=True)
class _Before:
    """What she posts a moment with, read beforehand in one read: the producer, her current
    conversation and its messages, her latest moments as she recalls them, the latest first,
    and the places the user's moments were at within `KEPT_APART`, by identifier."""

    profile: ProducerProfile
    conversation: Conversation | None
    messages: list[Message]
    recent: list[str]
    used: set[str]


class Moments:
    """Her moments, in `db`, on the deployer's models of `config`, each recorded in
    `activity`; `random` draws who posts and when. A time that came before `clock` says it is
    as they begin is missed. She posts in Tokyo's weather as `weathers` has it, of her jobs in
    the user's schedule, as `schedules` has them, and may be at one of `places`; her pictures
    are generated by `photos`."""

    def __init__(
        self,
        db: Database,
        characters: Mapping[str, Character],
        config: LiveConfig,
        affinities: Affinities,
        activity: ActivityLog,
        memory: Memories,
        her_now: HerNow,
        clock: Clock,
        random: Random,
        weathers: Weathers,
        schedules: Schedules,
        photos: Photos,
        world: World | None = None,
        places: Sequence[Place] = (),
    ) -> None:
        self._db = db
        self._characters = characters
        self._config = config
        self._affinities = affinities
        self._activity = activity
        self._memory = memory
        self._her_now = her_now
        self._clock = clock
        self._random = random
        self._world = world
        self._places = places
        self._weathers = weathers
        self._schedules = schedules
        self._photos = photos
        self._started = clock()
        self._was_off = False
        db.prepare(_open)

    async def keep_posting(self) -> None:
        """`run_due` at every `TICK`, until cancelled."""
        while True:
            await asyncio.sleep(TICK.total_seconds())
            try:
                await self.run_due()
            except Exception:
                log.exception("posting moments failed")

    async def run_due(self) -> None:
        """Plan for each user active and not yet planned for today in Tokyo, then post each
        moment and reply whose time has come, one after another in the order of their times;
        one going wrong keeps none of the others from it. Nothing while the deployer has
        moments off, or has no chat model; turned on again, what was planned is forgotten,
        each user planned for anew, and the replies whose time came meanwhile are not made."""
        now = self._clock()
        if not self._on:
            self._was_off = True
            return
        if self._was_off:  # turned on again: planned anew, from what is left of the day
            await self._db.write(_forget_plans, now.astimezone(UTC).isoformat())
            self._was_off = False
        await self._plan(now)
        at = now.astimezone(UTC).isoformat()
        due: list[_Plan | _DueReply] = [
            *await self._db.read(_due, at),
            *await self._db.read(_due_replies, at, (now - KEPT).astimezone(UTC).isoformat()),
        ]
        for each in sorted(due, key=lambda each: each.due_at):
            try:
                if isinstance(each, _Plan):
                    await self._post(each)
                else:
                    await self._reply(each)
            except Exception:
                log.exception("a moment or reply to user %s failed", each.user_id)
                # not tried again
                if isinstance(each, _Plan):
                    await self._db.write(_drop_plan, each.id)
                else:
                    await self._db.write(_no_reply, each.comment_id)

    async def forget_old(self) -> None:
        """Delete everyone's moments that showed `KEPT` ago or longer, with their pictures,
        her circle's likes and comments, and the producer's like and comment, her reply with
        it, shown or not; whether moments are on or off. And the moments planned and missed:
        those of the day before yesterday in Tokyo or earlier. In batches
        (`housekeeping.in_batches`)."""
        now = self._clock()
        at = (now - KEPT).astimezone(UTC).isoformat()
        for table in _WITH_A_MOMENT:  # each a batch of rows, a picture one among them
            await in_batches(self._db, _forget_with_moments_before, table, at)
        await in_batches(self._db, _forget_moments_before, at)
        yesterday = tokyo_date(now) - timedelta(days=1)
        await in_batches(self._db, _forget_plans_before, yesterday.isoformat())

    async def liked_or_commented_share(self) -> float | None:
        """Of everyone's moments that have shown within `KEPT`, the share the producer likes or
        has commented on, as he does now; None of none."""
        now = self._clock()
        shown, liked_or_commented = await self._db.read(
            _liked_or_commented, (now - KEPT).astimezone(UTC).isoformat(),
            now.astimezone(UTC).isoformat(),
        )
        return liked_or_commented / shown if shown else None

    async def switch_of(self, user_id: str) -> bool | None:
        """Whether the user has their own switch for moments on, as it is by default; None
        where the deployer has them off."""
        if not self._config.moments.enabled:
            return None
        return await self._db.read(read_switched_on, user_id)

    async def switch(self, user_id: str, on: bool) -> None:
        """Switch the user's own switch on or off, from the next tick; raise `MomentsOff`
        where the deployer has moments off."""
        if not self._config.moments.enabled:
            raise MomentsOff
        await self._db.write(_switch, user_id, on)

    async def timeline(self, user_id: str) -> list[Moment]:
        """The user's moments that have shown within `KEPT`, the latest first, of the
        characters there are, as are the likes and comments on them, the user counted as
        opening their moments now; raise `MomentsOff` where the deployer or the user has them
        off."""
        await self._require_on(user_id)
        now = self._clock()
        await self._db.write(_opened, user_id, now.astimezone(UTC).isoformat())
        moments = await self._db.read(
            _timeline, user_id, (now - KEPT).astimezone(UTC).isoformat(),
            now.astimezone(UTC).isoformat(),
        )
        return [
            replace(
                m,
                likes=tuple(id for id in m.likes if id in self._characters),
                comments=tuple(c for c in m.comments if c.character_id in self._characters),
            )
            for m in moments if m.character_id in self._characters
        ]

    async def unseen(self, user_id: str) -> bool:
        """Whether a moment on the user's timeline, of a character there is, or her reply on
        it, has shown since they last opened their moments, reading the timeline; for one who
        never has, since they were first planned for. Her circle's likes and comments are not
        counted. Raise `MomentsOff` where the deployer or the user has them off."""
        await self._require_on(user_id)
        now = self._clock()
        whose = await self._db.read(
            _unseen, user_id, (now - KEPT).astimezone(UTC).isoformat(),
            now.astimezone(UTC).isoformat(),
        )
        return not whose.isdisjoint(self._characters)

    async def picture(self, user_id: str, moment_id: int) -> bytes | None:
        """The picture of the user's moment, if it has one and is on their timeline, as WebP;
        None for none, or another's; raise `MomentsOff` where the deployer or the user has
        them off."""
        await self._require_on(user_id)
        now = self._clock()
        return await self._db.read(
            _read_picture, user_id, moment_id, (now - KEPT).astimezone(UTC).isoformat(),
            now.astimezone(UTC).isoformat(),
        )

    async def like(self, user_id: str, moment_id: int, liked: bool) -> None:
        """Have the producer like the moment on his timeline, or no longer, however he did;
        raise `NoMoment` for one not on it, `MomentsOff` where the deployer or the user has
        them off."""
        await self._on_timeline(user_id, moment_id)
        await self._db.write(_set_liked, moment_id, liked)

    async def comment(self, user_id: str, moment_id: int, text: str) -> ProducerComment:
        """Have the producer comment `text` on the moment on his timeline, kept as he wrote
        it, and have her reply as her tier has her, if it does; what is kept of it. Raise
        `CommentInvalid` for a comment with none, or over `COMMENT_LENGTH`, characters but for
        the spaces around them; `AlreadyCommented` if he has already; `NoMoment` for one not
        on it; `MomentsOff` where the deployer or the user has them off."""
        if not 1 <= len(text.strip()) <= COMMENT_LENGTH:
            raise CommentInvalid
        character_id = await self._on_timeline(user_id, moment_id)
        now = self._clock()
        reply_at = draw_reply(
            now, _tier(await self._affinities.status(user_id, character_id)), self._random
        )
        kept = ProducerComment(text, now.astimezone(UTC).isoformat())
        if not await self._db.write(
            _add_comment, moment_id, kept,
            reply_at.astimezone(UTC).isoformat() if reply_at is not None else None,
        ):
            raise AlreadyCommented
        return kept

    async def uncomment(self, user_id: str, moment_id: int) -> None:
        """Delete the producer's comment on the moment on his timeline, if any, her reply to
        it with it, shown or not; raise `NoMoment` for one not on it, `MomentsOff` where the
        deployer or the user has them off."""
        await self._on_timeline(user_id, moment_id)
        await self._db.write(_delete_comment, moment_id)

    async def _on_timeline(self, user_id: str, moment_id: int) -> str:
        """The character whose moment on the user's timeline it is; raise `NoMoment` for one
        not on it, `MomentsOff` where the deployer or the user has them off."""
        await self._require_on(user_id)
        now = self._clock()
        character_id = await self._db.read(
            _whose, user_id, moment_id, (now - KEPT).astimezone(UTC).isoformat(),
            now.astimezone(UTC).isoformat(),
        )
        if character_id is None or character_id not in self._characters:
            raise NoMoment
        return character_id

    async def _require_on(self, user_id: str) -> None:
        """Raise `MomentsOff` where the deployer or the user has moments off."""
        if await self.switch_of(user_id) is not True:
            raise MomentsOff

    @property
    def map_site(self) -> MapSite:
        """The map the places on the timeline link to now."""
        return self._config.moments.map

    @property
    def _on(self) -> bool:
        return self._config.moments.enabled and self._config.has_service("chat_llm")

    async def _plan(self, now: datetime) -> None:
        """Plan today's moments for each user active and not yet planned for today; one
        going wrong keeps none of the others from it."""
        day = tokyo_date(now)
        affinity_on = self._affinities.on
        unplanned = await self._db.read(self._unplanned, day, now, affinity_on)
        for user_id, tiers in unplanned.items():
            try:
                jobs = await self._schedules.done_on(user_id, day)
                eligible = [
                    Eligible(
                        id, tier, is_birthday(self._characters[id].birthday, day),
                        jobs[id][-1].done_at if id in jobs else None,
                    )
                    for id, tier in tiers.items() if tier is not None
                ]
                planned = plan_day(
                    eligible, day, now, self._config.moments.per_day, self._random
                )
                await self._db.write(
                    _keep_plan, user_id, day.isoformat(), planned, now.astimezone(UTC).isoformat()
                )
            except Exception:
                log.exception("planning moments for user %s failed", user_id)

    def _unplanned(
        self, db: sqlite3.Connection, day: date, now: datetime, affinity_on: bool
    ) -> dict[str, dict[str, Tier | None]]:
        """Each user active and not planned for `day`, with her tier with each character,
        read through `db`."""
        in_touch: dict[str, list[InTouch]] = {}
        for each in read_in_touch(db):
            in_touch.setdefault(each.user_id, []).append(each)
        planned = {
            user_id
            for (user_id,) in db.execute(
                "SELECT user_id FROM moment_users WHERE planned_day = ?", (day.isoformat(),)
            )
        }
        unplanned: dict[str, dict[str, Tier | None]] = {}
        for user_id in in_touch.keys() - planned:
            standing = self._standing(db, user_id, now, affinity_on, in_touch[user_id])
            if standing.active:
                unplanned[user_id] = standing.tiers
        return unplanned

    def _standing(
        self,
        db: sqlite3.Connection,
        user_id: str,
        now: datetime,
        affinity_on: bool,
        in_touch: Sequence[InTouch] | None = None,
    ) -> _Standing:
        """What is read of the user at `now`, through `db`: from `in_touch` if read
        already; her affinity only while it is `affinity_on`."""
        if in_touch is None:
            in_touch = read_in_touch(db, user_id)
        limits = read_user_limits(db, user_id)
        contacts = [t.last_contact for t in in_touch if t.last_contact is not None]
        active = (
            bool(contacts) and now - max(contacts) <= ACTIVE
            and (limits is None or limits.turns_per_hour != 0)
            and read_switched_on(db, user_id)
        )
        tiers: dict[str, Tier | None] = {
            t.character_id: _tier(
                self._affinities.read_status(db, user_id, t.character_id)
                if affinity_on else None
            )
            for t in in_touch if t.has_turns and t.character_id in self._characters
        }
        return _Standing(active, tiers)

    async def _post(self, plan: _Plan) -> None:
        """Post the moment planned, unless it is to be passed over, or is of her jobs while
        she is still at one, then put off till after the last, and looked at again then;
        posted or passed over, take it off the plan."""
        if plan.due_at < self._started or not await self._still(plan):
            await self._db.write(_drop_plan, plan.id)
            return
        now = self._clock()
        jobs: list[DayJob] = []
        if plan.kind == "work":
            jobs = (await self._schedules.done_on(plan.user_id, plan.day)).get(
                plan.character_id, []
            )
            if jobs and jobs[-1].done_at > now:  # scheduled more since it was planned
                due = work_time(jobs[-1].done_at, now, self._random)
                assert due is not None  # the last is done after now
                await self._db.write(_put_off, plan.id, due.astimezone(UTC).isoformat())
                return
        character = self._characters[plan.character_id]
        weather = await self._weathers.at(now)
        material = await self._material(plan, character, now, weather, jobs)
        recording = self._activity.begin(
            "moment", plan.user_id, plan.character_id, own_llm=False, exempt=False
        )
        lease = self._config.lease()
        try:
            with recording.current():
                written = await written_whole(lease.keys.chat_llm.stream(post_prompt(material)))
        except Exception as e:
            # Not logged with what was raised: a service's error may repeat what it was asked.
            log.warning("posting a moment to user %s failed: %s", plan.user_id,
                        type(e).__name__)
            await self._db.write(_drop_plan, plan.id)
            await recording.finish("failed")
            return
        finally:
            lease.release()
        post = parse_post(written, material)
        if post is None:
            log.warning("posting a moment to user %s failed: nothing to post", plan.user_id)
            await self._db.write(_drop_plan, plan.id)
            await recording.finish("failed")
            return
        degraded = dict(post.degraded)
        image = None
        if post.picture is not None:
            with recording.current():
                image = await self._picture(
                    plan, character, post.picture, post.place, now, weather, degraded
                )
        recording.degraded = degraded or None
        posted_at = self._clock()
        likes_at, comments_at = draw_shown(
            posted_at, len(post.likes), len(post.comments), self._random
        )
        await self._db.write(
            _add_moment, plan, post.ja, post.zh, post.place, weather,
            posted_at.astimezone(UTC).isoformat(),
            _when(post.likes, likes_at), _when(post.comments, comments_at),
            post.picture, image,
        )
        await recording.finish("success")

    async def _picture(
        self,
        plan: _Plan,
        character: Character,
        picture: Picture,
        place: Place | None,
        at: datetime,
        weather: Weather | None,
        degraded: dict[str, int],
    ) -> bytes | None:
        """Her moment's picture, she at `place` posting `at` in `weather`, generated by
        `PICTURE_TIME_LIMIT` from now; None if it fails or takes too long. One no one is in
        is had from GPT Image first, if on, by `GPT_TIME_LIMIT`; failing there, from the
        deployer's image generation in what time is left, and it is told in `degraded`."""
        loop = asyncio.get_running_loop()
        until = loop.time() + PICTURE_TIME_LIMIT.total_seconds()
        stripped = None
        if picture.tag.composition in UNPEOPLED and self._photos.gpt_on:
            prompt = gpt_picture_prompt(
                picture.tag, picture.note, place, at, weather,
                self._config.gpt_image_style,
            )
            try:
                return await self._photos.gpt_picture(
                    prompt, min(until, loop.time() + GPT_TIME_LIMIT), picture.tag.stripped
                )
            except ImageFailed as e:
                log.warning("GPT Image did not generate the picture of a moment to user %s: %s;"
                            " trying image generation", plan.user_id, e.reason)
                stripped = ()  # counted with the request GPT Image was sent
            except TimeoutError:
                log.warning("the picture of a moment to user %s waited its turn at GPT Image"
                            " too long; trying image generation", plan.user_id)
            except Exception:
                log.exception("generating the picture of a moment to user %s at GPT Image"
                              " failed; trying image generation", plan.user_id)
            degraded[PICTURE_FALLBACK] = 1
        try:
            return await self._photos.picture(character, picture.tag, until, stripped)
        except ImageFailed as e:
            log.warning("the picture of a moment to user %s was not generated: %s",
                        plan.user_id, e.reason)
        except TimeoutError:
            log.warning("the picture of a moment to user %s waited its turn too long",
                        plan.user_id)
        except Exception:
            log.exception("generating the picture of a moment to user %s failed", plan.user_id)
        return None

    async def _still(self, plan: _Plan) -> bool:
        """Whether the moment planned is to be posted, as it is now."""
        if not self._on or plan.character_id not in self._characters:
            return False
        standing, posted = await self._db.read(
            self._standing_then, plan, self._clock(), self._affinities.on
        )
        return (
            standing.active and standing.tiers.get(plan.character_id) is not None
            and posted < self._config.moments.per_day
        )

    async def _reply(self, due: _DueReply) -> None:
        """Reply to the producer's comment, unless she is not to now, or its time came before
        the backend started, then for good, as her record says how it turned out."""
        now = self._clock()
        day = tokyo_date(now)
        start = datetime.combine(day, time(), TOKYO)
        before = await self._db.read(
            self._before_reply, due, self._affinities.on, start, start + timedelta(days=1)
        )
        if (
            due.due_at < self._started or before is None
            or due.character_id not in self._characters
            or not before.switched_on or _tier(before.status) is None
            or before.replied >= self._config.moments.replies_per_day
        ):
            await self._db.write(_no_reply, due.comment_id)
            return
        material = await self._reply_material(due, before, now)
        recording = self._activity.begin(
            "moment_reply", due.user_id, due.character_id, own_llm=False, exempt=False
        )
        lease = self._config.lease()
        try:
            with recording.current():
                written = await written_whole(lease.keys.chat_llm.stream(reply_prompt(material)))
        except Exception as e:
            # Not logged with what was raised: a service's error may repeat what it was asked.
            log.warning("replying to user %s failed: %s", due.user_id, type(e).__name__)
            await self._db.write(_no_reply, due.comment_id)
            await recording.finish("failed")
            return
        finally:
            lease.release()
        said = parse_reply(written)
        if said is None:
            log.warning("replying to user %s failed: nothing to reply", due.user_id)
            await self._db.write(_no_reply, due.comment_id)
            await recording.finish("failed")
            return
        shown = await self._db.write(
            _add_reply, due.comment_id, *said, self._clock().astimezone(UTC).isoformat()
        )
        await recording.finish("success" if shown else "rejected")

    def _before_reply(
        self,
        db: sqlite3.Connection,
        due: _DueReply,
        affinity_on: bool,
        start: datetime,
        end: datetime,
    ) -> _BeforeReply | None:
        """What she replies to the producer's comment with, read through `db`, her affinity
        only while it is `affinity_on`, counting her replies between `start` and `end`; None
        if the comment is gone, or replied to."""
        found = db.execute(
            "SELECT m.id, m.ja, m.image, c.text,"
            " EXISTS (SELECT 1 FROM moment_likes l WHERE l.moment_id = m.id)"
            " FROM moment_comments c JOIN moments m ON m.id = c.moment_id"
            " WHERE c.id = ? AND c.reply_ja IS NULL",
            (due.comment_id,),
        ).fetchone()
        if found is None:
            return None
        moment_id, ja, image, text, liked = found
        replied = read_replied_between(db, due.user_id, start, end)
        conversation = read_current_conversation(db, due.user_id, due.character_id)
        messages = (
            [e for e in read_record(db, conversation.id) if isinstance(e, Message)]
            if conversation is not None else []
        )
        return _BeforeReply(
            read_switched_on(db, due.user_id),
            self._affinities.read_status(db, due.user_id, due.character_id)
            if affinity_on else None,
            replied, read_profile(db, due.user_id), conversation, messages,
            moment_id, ja, image, bool(liked), text,
        )

    async def _reply_material(
        self, due: _DueReply, before: _BeforeReply, now: datetime
    ) -> ReplyMaterial:
        """What she replies to the producer's comment with, read now, of what was `before`."""
        character = self._characters[due.character_id]
        known = await self._her_now.read(due.user_id, due.character_id, None, "moments")
        timezone = effective_timezone(before.profile, None)
        memories = (
            await self._memory.for_reaching_out(
                before.conversation, timezone, last_turn_query(before.messages), posting=True
            )
            if before.conversation is not None else None
        )
        likes, comments = await self._db.read(
            _circle_shown, before.moment_id, now.astimezone(UTC).isoformat()
        )
        characters = self._characters
        return ReplyMaterial(
            character,
            self._world.prompt(character.name, local_date(now, timezone)) if self._world else None,
            before.profile,
            [said_to_chat(m) for m in chat_history(before.messages, self._config.history_turns)],
            self._her_now.lines(
                known, "moments", now, timezone, before.profile, None,
                tier_prompt(before.status), replying=True,
            ),
            memories,
            recalled(before.ja, picture_note(before.image)),
            [characters[id].name for id in likes if id in characters],
            [(characters[c.character_id].name, c.ja) for c in comments
             if c.character_id in characters],
            before.liked,
            before.comment,
        )

    def _standing_then(
        self, db: sqlite3.Connection, plan: _Plan, now: datetime, affinity_on: bool
    ) -> tuple[_Standing, int]:
        """The user's standing at `now`, and how many moments they have had of the plan's
        day, read through `db`."""
        [posted] = db.execute(
            "SELECT COUNT(*) FROM moments WHERE user_id = ? AND day = ?",
            (plan.user_id, plan.day.isoformat()),
        ).fetchone()
        return self._standing(db, plan.user_id, now, affinity_on), posted

    async def _material(
        self,
        plan: _Plan,
        character: Character,
        now: datetime,
        weather: Weather | None,
        jobs: Sequence[DayJob],
    ) -> PostMaterial:
        """What she posts the moment planned with, read now, in `weather` (None for none
        known): of `jobs`, her jobs done that day, if any, else of her everyday. Of her jobs,
        her places are of the kinds they take her to, none if none takes her anywhere."""
        known = await self._her_now.read(plan.user_id, plan.character_id, None, "moments")
        before = await self._db.read(
            _before, plan.user_id, plan.character_id,
            (now - KEPT_APART).astimezone(UTC).isoformat(),
        )
        status = await self._affinities.status(plan.user_id, plan.character_id)
        timezone = effective_timezone(before.profile, None)
        memories = (
            await self._memory.for_reaching_out(
                before.conversation, timezone, last_turn_query(before.messages), posting=True
            )
            if before.conversation is not None else None
        )
        kinds = {kind for each in jobs for kind in each.places or ()}
        places = (
            draw_places(
                self._places, character.id, None if jobs else character.place_likes,
                venues_on_this_day(now, character, self._world), now, before.used,
                self._random, roofed=weather is not None and weather.wet,
                within=kinds if jobs else None,
            )
            if kinds or not jobs else []
        )
        seeds = [] if jobs else [_seed(f.text) for f in draw_seeds(character.facts, self._random)]
        circle = self._circle(character, tokyo_date(now), plan.birthday)
        image = self._config.image_settings
        compositions = draw_compositions(
            image is not None, character.photographed, self._random,
            group=image is not None and image.api_format == "novelai"
            and any(m.character.photographed for m in circle),
        )
        return PostMaterial(
            character,
            self._world.prompt(character.name, local_date(now, timezone)) if self._world else None,
            before.profile,
            self._her_now.lines(
                known, "moments", now, timezone, before.profile, None,
                tier_prompt(status), weather,
            ),
            plan.birthday,
            seeds,
            memories,
            before.recent,
            places,
            [f"{each.job.name}：{each.job.note}" for each in jobs],
            circle,
            compositions,
        )

    def _circle(self, character: Character, day: date, birthday: bool) -> list[Member]:
        """Her circle on `day` in Tokyo, on her `birthday` or not, as drawn."""
        world = self._world
        others = {
            id: each for id, each in self._characters.items()
            if id != character.id and not (world is not None and world.is_staff(each.name))
        }
        related_by = relations(character, others)
        unit = set(world.unit_mates(character.name)) if world is not None else set()
        mates = [id for id, each in others.items() if each.name in unit]
        related = [id for id in related_by if id not in mates]
        strangers = [id for id in others if id not in mates and id not in related_by]
        birthdays = {id for id, each in others.items() if is_birthday(each.birthday, day)}
        drawn = draw_circle(mates, related, strangers, birthdays, birthday, self._random)
        return [Member(others[id], related_by.get(id)) for id in drawn]


async def written_whole(stream: AsyncIterator[Streamed]) -> str:
    """The whole of what the model wrote, its text alone."""
    chunks: list[str] = []
    try:
        async for item in stream:
            if isinstance(item, str):
                chunks.append(item)
    finally:
        if (close := getattr(stream, "aclose", None)) is not None:
            await close()
    return "".join(chunks)


def _when(shown: Sequence[_T], at: Sequence[datetime]) -> list[tuple[_T, str]]:
    """Each of `shown` with when it shows, as the database writes it."""
    return [(each, when.astimezone(UTC).isoformat()) for each, when in zip(shown, at, strict=True)]


def relations(character: Character, others: Mapping[str, Character]) -> dict[str, str]:
    """What a section of her facts on the people she knows says of each of `others` whose
    name is in its heading, but for sections whose headings have `NOT_ONE` in them, without
    their headings: the first for one in two."""
    found: dict[str, str] = {}
    for fact in character.facts:
        headings = fact.headings
        if headings[:1] != [RELATIONS] or len(headings) < 2:
            continue
        if any(word in headings[-1] for word in NOT_ONE):
            continue
        for id, each in others.items():
            if each.name in headings[-1]:
                found.setdefault(id, fact.body)
    return found


def _seed(text: str) -> str:
    """An entry of her facts as a seed: its heading, then what is under it, on one line."""
    return text.replace("\n", "：", 1).replace("\n", " ")


def _tier(status: Status | None) -> Tier | None:
    """The tier she posts by, trust where affinity is off (`status` None); None if she is
    not to, in a cooldown or below trust."""
    if status is None:
        return "trust"
    if status.cooling or status.tier not in CHANCES:
        return None
    return status.tier


def _open(db: sqlite3.Connection) -> None:
    db.executescript(_SCHEMA)


def _switch(db: sqlite3.Connection, user_id: str, on: bool) -> None:
    if on:
        db.execute("DELETE FROM moments_off WHERE user_id = ?", (user_id,))
    else:
        db.execute("INSERT OR IGNORE INTO moments_off (user_id) VALUES (?)", (user_id,))


def _keep_plan(
    db: sqlite3.Connection, user_id: str, day: str, planned: Sequence[Planned], now: str
) -> None:
    """Keep the user's plan for `day`, and that they are planned for it; first planned for
    `now`, they are counted as having opened their moments then."""
    db.executemany(
        "INSERT INTO moment_plans (user_id, character_id, day, due_at, kind, birthday)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [(user_id, p.character_id, day, p.due_at.astimezone(UTC).isoformat(), p.kind,
          int(p.birthday))
         for p in planned],
    )
    db.execute(
        "INSERT INTO moment_users (user_id, planned_day, opened_at) VALUES (?, ?, ?)"
        " ON CONFLICT (user_id) DO UPDATE SET planned_day = excluded.planned_day,"
        " opened_at = COALESCE(opened_at, excluded.opened_at)",
        (user_id, day, now),
    )


def _opened(db: sqlite3.Connection, user_id: str, now: str) -> None:
    """Keep that the user opened their moments `now`."""
    db.execute(
        "INSERT INTO moment_users (user_id, opened_at) VALUES (?, ?)"
        " ON CONFLICT (user_id) DO UPDATE SET opened_at = excluded.opened_at",
        (user_id, now),
    )


def _unseen(db: sqlite3.Connection, user_id: str, since: str, now: str) -> set[str]:
    """Whose moments on the user's timeline, or replies on it, have shown since they last
    opened their moments, by `now`; none for one who has never been planned for nor opened
    them."""
    opened = db.execute(
        "SELECT opened_at FROM moment_users WHERE user_id = ?", (user_id,)
    ).fetchone()
    if opened is None or opened[0] is None:
        return set()
    return {
        character_id
        for (character_id,) in db.execute(
            "SELECT m.character_id FROM moments m"
            " WHERE m.user_id = :user AND m.posted_at > :since AND m.posted_at <= :now"
            " AND m.posted_at > :opened"
            " UNION"
            " SELECT m.character_id FROM moments m JOIN moment_comments c ON c.moment_id = m.id"
            " WHERE m.user_id = :user AND m.posted_at > :since AND m.posted_at <= :now"
            " AND c.reply_ja IS NOT NULL AND c.reply_at > :opened AND c.reply_at <= :now",
            {"user": user_id, "since": since, "now": now, "opened": opened[0]},
        )
    }


def _liked_or_commented(db: sqlite3.Connection, since: str, now: str) -> tuple[int, int]:
    """How many moments showed after `since` up to `now`, and how many of them the producer
    likes or has commented on."""
    shown, liked_or_commented = db.execute(
        "SELECT COUNT(*), COALESCE(SUM("
        " EXISTS (SELECT 1 FROM moment_likes l WHERE l.moment_id = m.id)"
        " OR EXISTS (SELECT 1 FROM moment_comments c WHERE c.moment_id = m.id)), 0)"
        " FROM moments m WHERE m.posted_at > ? AND m.posted_at <= ?",
        (since, now),
    ).fetchone()
    return shown, liked_or_commented


def _forget_plans(db: sqlite3.Connection, now: str) -> None:
    """Forget every moment planned, and that anyone was planned for, and every reply whose
    time came by `now`."""
    db.execute("DELETE FROM moment_plans")
    db.execute("UPDATE moment_users SET planned_day = NULL")
    db.execute(
        "UPDATE moment_comments SET reply_at = NULL WHERE reply_ja IS NULL AND reply_at <= ?",
        (now,),
    )


_WITH_A_MOMENT = ("moment_images", "moment_circle", "moment_likes", "moment_comments")
"""The tables of what goes with a moment, each by `moment_id`."""


def _forget_with_moments_before(db: sqlite3.Connection, table: str, at: str, batch: int) -> int:
    """Delete `batch` at most of the rows in `table`, one of `_WITH_A_MOMENT`, of everyone's
    moments that showed by `at`: how many it deleted."""
    return db.execute(
        f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} WHERE moment_id IN"
        " (SELECT id FROM moments WHERE posted_at <= ?) LIMIT ?)",
        (at, batch),
    ).rowcount


def _forget_moments_before(db: sqlite3.Connection, at: str, batch: int) -> int:
    """Delete `batch` at most of everyone's moments that showed by `at`, what goes with them
    deleted first: how many it deleted."""
    return db.execute(
        "DELETE FROM moments WHERE id IN (SELECT id FROM moments WHERE posted_at <= ? LIMIT ?)",
        (at, batch),
    ).rowcount


def _forget_plans_before(db: sqlite3.Connection, day: str, batch: int) -> int:
    """Delete `batch` at most of the moments planned for the days before `day`: how many it
    deleted."""
    return db.execute(
        "DELETE FROM moment_plans WHERE id IN (SELECT id FROM moment_plans WHERE day < ? LIMIT ?)",
        (day, batch),
    ).rowcount


def _due_replies(db: sqlite3.Connection, now: str, since: str) -> list[_DueReply]:
    """Her replies whose time has come by `now`, to comments on moments shown after `since`,
    the earliest first."""
    return [
        _DueReply(id, user_id, character_id, datetime.fromisoformat(reply_at))
        for id, user_id, character_id, reply_at in db.execute(
            "SELECT c.id, m.user_id, m.character_id, c.reply_at"
            " FROM moment_comments c JOIN moments m ON m.id = c.moment_id"
            " WHERE c.reply_ja IS NULL AND c.reply_at <= ? AND m.posted_at > ?"
            " ORDER BY c.reply_at, c.id",
            (now, since),
        )
    ]


def _no_reply(db: sqlite3.Connection, comment_id: int) -> None:
    """Have her not reply to the comment after all."""
    db.execute(
        "UPDATE moment_comments SET reply_at = NULL WHERE id = ? AND reply_ja IS NULL",
        (comment_id,),
    )


def _add_reply(db: sqlite3.Connection, comment_id: int, ja: str, zh: str, at: str) -> bool:
    """Show her reply to the comment from `at`; False if the comment is gone."""
    return db.execute(
        "UPDATE moment_comments SET reply_ja = ?, reply_zh = ?, reply_at = ?"
        " WHERE id = ? AND reply_ja IS NULL",
        (ja, zh, at, comment_id),
    ).rowcount == 1


def _whose(
    db: sqlite3.Connection, user_id: str, moment_id: int, since: str, now: str
) -> str | None:
    """The character whose moment on the user's timeline it is, shown after `since` and by
    `now`; None for none."""
    found = db.execute(
        "SELECT character_id FROM moments"
        " WHERE id = ? AND user_id = ? AND posted_at > ? AND posted_at <= ?",
        (moment_id, user_id, since, now),
    ).fetchone()
    return found[0] if found is not None else None


def _set_liked(db: sqlite3.Connection, moment_id: int, liked: bool) -> None:
    if liked:
        db.execute("INSERT OR IGNORE INTO moment_likes (moment_id) VALUES (?)", (moment_id,))
    else:
        db.execute("DELETE FROM moment_likes WHERE moment_id = ?", (moment_id,))


def _add_comment(
    db: sqlite3.Connection, moment_id: int, comment: ProducerComment, reply_at: str | None
) -> bool:
    """Keep the producer's comment, her reply due at `reply_at` (None for none); False if he
    has commented already."""
    return db.execute(
        "INSERT OR IGNORE INTO moment_comments (moment_id, text, commented_at, reply_at)"
        " VALUES (?, ?, ?, ?)",
        (moment_id, comment.text, comment.commented_at, reply_at),
    ).rowcount == 1


def _delete_comment(db: sqlite3.Connection, moment_id: int) -> None:
    db.execute("DELETE FROM moment_comments WHERE moment_id = ?", (moment_id,))


def _circle_shown(
    db: sqlite3.Connection, moment_id: int, now: str
) -> tuple[list[str], list[Comment]]:
    """Who of her circle has liked the moment by `now`, and their comments, in the order they
    showed."""
    likes: list[str] = []
    comments: list[Comment] = []
    for character_id, kind, ja, zh in db.execute(
        "SELECT character_id, kind, ja, zh FROM moment_circle"
        " WHERE moment_id = ? AND shown_at <= ? ORDER BY shown_at, position",
        (moment_id, now),
    ):
        if kind == _LIKE:
            likes.append(character_id)
        else:
            comments.append(Comment(character_id, ja, zh))
    return likes, comments


def said_to_chat(message: Message) -> ChatMessage:
    """A message of her conversation as the chat model reads it as she replies: the user's
    words, or her reply as she wrote it, without the photo she sent with it."""
    if message.role == "user":
        return ChatMessage("user", message.text or "")
    return ChatMessage("assistant", format_reply(message.segments))


def _due(db: sqlite3.Connection, now: str) -> list[_Plan]:
    """The moments planned whose time has come by `now`, the earliest first."""
    return [
        _Plan(id, user_id, character_id, date.fromisoformat(day),
              datetime.fromisoformat(due_at), bool(birthday), kind)
        for id, user_id, character_id, day, due_at, birthday, kind in db.execute(
            "SELECT id, user_id, character_id, day, due_at, birthday, kind FROM moment_plans"
            " WHERE due_at <= ? ORDER BY due_at, id",
            (now,),
        )
    ]


def _put_off(db: sqlite3.Connection, plan_id: int, due_at: str) -> None:
    db.execute("UPDATE moment_plans SET due_at = ? WHERE id = ?", (due_at, plan_id))


def _drop_plan(db: sqlite3.Connection, plan_id: int) -> None:
    db.execute("DELETE FROM moment_plans WHERE id = ?", (plan_id,))


def _add_moment(
    db: sqlite3.Connection,
    plan: _Plan,
    ja: str,
    zh: str,
    place: Place | None,
    weather: Weather | None,
    posted_at: str,
    likes: Sequence[tuple[str, str]],
    comments: Sequence[tuple[Comment, str]],
    picture: Picture | None = None,
    image: bytes | None = None,
) -> None:
    """Post the moment planned, at a copy of `place`, in `weather`, with the `likes` and
    `comments` of her circle, each with when it shows, and the `picture` she wrote, as she
    wrote it, its `image` if it was generated; taking it off the plan."""
    written = json.dumps(dict(picture.written), ensure_ascii=False) if picture else None
    moment_id = db.execute(
        "INSERT INTO moments (user_id, character_id, ja, zh, image, place_id, place_name,"
        " place_lat, place_lon, weather, temperature, day, posted_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (plan.user_id, plan.character_id, ja, zh, written,
         *((place.id, place.name, place.lat, place.lon) if place else (None,) * 4),
         *((weather.kind, weather.temperature) if weather else (None, None)),
         plan.day.isoformat(), posted_at),
    ).lastrowid
    db.executemany(
        "INSERT INTO moment_circle (moment_id, character_id, kind, ja, zh, position, shown_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(moment_id, id, _LIKE, None, None, i, at) for i, (id, at) in enumerate(likes)]
        + [(moment_id, c.character_id, _COMMENT, c.ja, c.zh, i, at)
           for i, (c, at) in enumerate(comments)],
    )
    if image is not None:
        db.execute(
            "INSERT INTO moment_images (moment_id, image) VALUES (?, ?)", (moment_id, image)
        )
    _drop_plan(db, plan.id)


def _before(db: sqlite3.Connection, user_id: str, character_id: str, since: str) -> _Before:
    conversation = read_current_conversation(db, user_id, character_id)
    messages = (
        [e for e in read_record(db, conversation.id) if isinstance(e, Message)]
        if conversation is not None else []
    )
    recent = [
        recalled(ja, picture_note(image))
        for ja, image in db.execute(
            "SELECT ja, image FROM moments WHERE user_id = ? AND character_id = ?"
            " ORDER BY posted_at DESC, id DESC LIMIT ?",
            (user_id, character_id, RECENT),
        )
    ]
    used = {
        place_id for (place_id,) in db.execute(
            "SELECT place_id FROM moments WHERE user_id = ? AND posted_at > ?"
            " AND place_id IS NOT NULL",
            (user_id, since),
        )
    }
    return _Before(read_profile(db, user_id), conversation, messages, recent, used)


def _read_picture(
    db: sqlite3.Connection, user_id: str, moment_id: int, since: str, now: str
) -> bytes | None:
    found = db.execute(
        "SELECT i.image FROM moment_images i JOIN moments m ON m.id = i.moment_id"
        " WHERE i.moment_id = ? AND m.user_id = ? AND m.posted_at > ? AND m.posted_at <= ?",
        (moment_id, user_id, since, now),
    ).fetchone()
    return found[0] if found is not None else None


def _timeline(db: sqlite3.Connection, user_id: str, since: str, now: str) -> list[Moment]:
    likes: dict[int, list[str]] = {}
    comments: dict[int, list[Comment]] = {}
    for moment_id, character_id, kind, ja, zh in db.execute(
        "SELECT c.moment_id, c.character_id, c.kind, c.ja, c.zh"
        " FROM moment_circle c JOIN moments m ON m.id = c.moment_id"
        " WHERE m.user_id = ? AND m.posted_at > ? AND c.shown_at <= ?"
        " ORDER BY c.shown_at, c.position",
        (user_id, since, now),
    ):
        if kind == _LIKE:
            likes.setdefault(moment_id, []).append(character_id)
        else:
            comments.setdefault(moment_id, []).append(Comment(character_id, ja, zh))
    return [
        Moment(id, character_id, ja, zh, posted_at,
               ShownPlace(name, lat, lon) if name is not None else None,
               Weather(kind, temperature) if kind in ALL_KINDS else None,
               tuple(likes.get(id, ())), tuple(comments.get(id, ())), bool(pictured),
               bool(liked),
               ProducerComment(text, commented_at) if text is not None else None,
               (reply_ja, reply_zh) if reply_ja is not None and reply_at <= now else None)
        for (id, character_id, ja, zh, posted_at, name, lat, lon, kind, temperature, pictured,
             liked, text, commented_at, reply_at, reply_ja, reply_zh)
        in db.execute(
            "SELECT m.id, m.character_id, m.ja, m.zh, m.posted_at, m.place_name, m.place_lat,"
            " m.place_lon, m.weather, m.temperature,"
            " EXISTS (SELECT 1 FROM moment_images i WHERE i.moment_id = m.id),"
            " EXISTS (SELECT 1 FROM moment_likes l WHERE l.moment_id = m.id),"
            " c.text, c.commented_at, c.reply_at, c.reply_ja, c.reply_zh"
            " FROM moments m LEFT JOIN moment_comments c ON c.moment_id = m.id"
            " WHERE m.user_id = ? AND m.posted_at > ? AND m.posted_at <= ?"
            " ORDER BY m.posted_at DESC, m.id DESC",
            (user_id, since, now),
        )
    ]
