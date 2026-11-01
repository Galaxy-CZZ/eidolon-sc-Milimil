"""The draws behind moments (GLOSSARY.md「朋友圈」): given what they go by and a random
source, what comes of them, reading nothing and writing nothing, so that the background loop
and the eval alike take them as they are.

The day's plan (`plan_day`): each character eligible is drawn for once, by her tier
(`CHANCES`); on her birthday, in Tokyo, she posts whatever is drawn. Over as many as the user
may have a day, those whose birthday it is are kept first, the rest drawn among. One with jobs
the producer scheduled her that are done that day in Tokyo posts of them (`work`), within
`AFTER_WORK` after the last is done (`work_time`); one planned after that is over, and the
others, of their everyday (`daily`), each given a time in Tokyo after the moment planned at: a part of the day drawn by its weight
(`PARTS`), then a time in it, at least `APART` from the user's others; one there is no time
left for posts nothing that day.

Her everyday moment's seeds (`draw_seeds`): `SEEDS` entries of her facts, but for those of
the people she knows (`RELATIONS`), each as likely.

Her places (`draw_places`): as many as `CANDIDATES`, for her to say she was at one or at
none, of the places right for the season and the time of day she posts at in Tokyo, and none
the user's moments were at within the last `KEPT_APART`; in rain, snow or thunder, only those
under a roof. A venue is one only on a day she stood on it in a year before, and is then hers
before any is drawn; the rest are drawn by weight, one of a kind she likes weighing `LIKED`
times as much, her holy site `HOLY` times. Of her work moment, only of the kinds of place her
jobs take her to, each as likely.

Her circle (`draw_circle`), those who may like and comment on her moment: as many as `CIRCLE`
(`BIRTHDAY_CIRCLE` on her birthday), those she knows whose birthday it is first; then, now
and then (`STRANGER`), one of the others; then those she knows drawn by weight, her unit mates
weighing `MATE`, those of a section of her facts `RELATED`; then, should they be too few, the
others. When each like and comment shows (`draw_shown`): each like within `LIKES_AFTER` of the
moment, on its own; as many times within `COMMENTS_AFTER` drawn as there are comments, and
given them in order.

Her picture (`draw_compositions`): where there is image generation, `PICTURED` of her
moments have one, in any composition, or only those no one is in where she has no photo tags;
a group photo only in NovelAI's own format, with one of her circle who has photo tags.

When she replies to the producer's comment on her moment (`draw_reply`): within
`REPLY_AFTER` it by her tier, the closer the sooner, never in a tier below trust.

Every draw asks the random source for a number below `PLACES`, so that one giving the same
number each time draws alike wherever it is asked."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from eidolon.affinity import Tier
from eidolon.characters import Fact
from eidolon.job_list import Slot
from eidolon.photo_prompt import COMPOSITIONS, UNPEOPLED, Composition
from eidolon.place_pool import INDOOR, NEARBY, SEASONS, Place, Season
from eidolon.randomness import Random
from eidolon.today import TOKYO

CHANCES: dict[Tier, float] = {"intimate": 0.8, "close": 0.5, "trust": 0.25}
"""How likely she is to post on a day, by her tier; none in the tiers not here."""

PARTS: tuple[tuple[time, time, int], ...] = (
    (time(7), time(9), 2),
    (time(12), time(13), 2),
    (time(18), time(0), 4),
    (time(0), time(2), 1),
)
"""The parts of the day in Tokyo her everyday moment is posted in, from the first to the
second (midnight ending the day), and how much each weighs: the morning, lunch, after work,
late at night."""

AFTER_WORK = (timedelta(minutes=30), timedelta(hours=2))
"""How long after her last job of the day is done her work moment is, at least and at most."""

APART = timedelta(hours=1)
"""How far apart one user's moments of a day are at least."""

PLACES = 1000
"""How many numbers each draw asks the random source for."""

SEEDS = 3
"""How many entries of her facts her everyday moment is seeded with."""

RELATIONS = "人物关系"
"""The heading of the section of her facts on the people she knows, drawn from for no seed."""

CANDIDATES = 4
"""How many places she is given to choose from at most, besides none."""

LIKED = 3
"""How much more a place of a kind she likes weighs."""

HOLY = 4
"""How much more a place weighs whose `idols` she is of: her holy site."""

KEPT_APART = timedelta(days=30)
"""How long a place one of the user's moments was at is not drawn again for them."""

CIRCLE = (4, 6)
"""How many are in her circle, at least and at most."""

BIRTHDAY_CIRCLE = (8, 10)
"""How many are in her circle on her birthday, at least and at most."""

MATE = 3
"""How much one of her unit mates weighs in drawing her circle."""

RELATED = 1
"""How much one of a section of her facts on the people she knows weighs in drawing her
circle."""

STRANGER = 0.25
"""How likely one of another unit is in her circle."""

LIKES_AFTER = (timedelta(minutes=5), timedelta(hours=3))
"""How long after the moment shows each like shows, at least and at most."""

COMMENTS_AFTER = (timedelta(minutes=15), timedelta(hours=6))
"""How long after the moment shows each comment shows, at least and at most."""

REPLY_AFTER: dict[Tier, tuple[timedelta, timedelta]] = {
    "intimate": (timedelta(minutes=5), timedelta(minutes=30)),
    "close": (timedelta(minutes=15), timedelta(hours=1)),
    "trust": (timedelta(minutes=30), timedelta(hours=2)),
}
"""How long after the producer comments on her moment she replies, at least and at most, by
her tier; she replies in none of the tiers not here."""

PICTURED = 2 / 3
"""How likely her moment is to have a picture, where there is image generation."""

_SEASONS: dict[int, Season] = {
    month: season
    for season, months in zip(SEASONS, ((3, 4, 5), (6, 7, 8), (9, 10, 11), (12, 1, 2)), strict=True)
    for month in months
}
"""The season of each month in Tokyo."""


Kind = Literal["daily", "work"]
"""Whether a moment is of her everyday or of her jobs done that day."""


@dataclass(frozen=True)
class Eligible:
    """A character the user may have a moment of today: her tier (trust where affinity is
    off), whether it is her birthday in Tokyo, and when the last of her jobs done that day in
    Tokyo is done, None without any."""

    character_id: str
    tier: Tier
    birthday: bool
    last_done: datetime | None = None


@dataclass(frozen=True)
class Planned:
    """A moment planned: whose, when it is due, whether on her birthday, and of what."""

    character_id: str
    due_at: datetime
    birthday: bool
    kind: Kind = "daily"


def plan_day(
    eligible: Sequence[Eligible], day: date, after: datetime, per_day: int, random: Random
) -> list[Planned]:
    """The moments of the user's `day` in Tokyo, planned at `after`, as many as `per_day` at
    most, the earliest first: of the `eligible`, in their order, each drawn for, those kept,
    and a time drawn for each."""
    posting = [e for e in eligible if e.birthday or _draw(random) < CHANCES[e.tier]]
    kept = [e for e in posting if e.birthday][:per_day]
    rest = [e for e in posting if not e.birthday]
    if len(kept) + len(rest) <= per_day:
        kept += rest
    else:
        while len(kept) < per_day:
            kept.append(rest.pop(_index(random, len(rest))))
    planned: list[Planned] = []
    daily: list[Eligible] = []
    for each in kept:
        at = work_time(each.last_done, after, random) if each.last_done is not None else None
        if at is None:
            daily.append(each)
        else:
            planned.append(Planned(each.character_id, at, each.birthday, "work"))
    for each in daily:
        at = _time(day, after, [p.due_at for p in planned], random)
        if at is not None:
            planned.append(Planned(each.character_id, at, each.birthday))
    return sorted(planned, key=lambda p: p.due_at)


def work_time(last_done: datetime, after: datetime, random: Random) -> datetime | None:
    """When her work moment is, her last job of the day done at `last_done`: drawn within
    `AFTER_WORK` after it, of what is left of that after `after`; None if nothing is."""
    least, most = AFTER_WORK
    start, end = max(last_done + least, after), last_done + most
    if start >= end:
        return None
    return start + timedelta(seconds=int((end - start).total_seconds() * _draw(random)))


def draw_seeds(facts: Sequence[Fact], random: Random) -> list[Fact]:
    """`SEEDS` of `facts`, or all if fewer, but for those under `RELATIONS`, in the order
    drawn."""
    left = [f for f in facts if f.headings[:1] != [RELATIONS]]
    return [left.pop(_index(random, len(left))) for _ in range(min(SEEDS, len(left)))]


def draw_places(
    places: Sequence[Place],
    character_id: str,
    likes: Collection[str] | None,
    venues: Collection[str],
    at: datetime,
    used: Collection[str],
    random: Random,
    roofed: bool = False,
    within: Collection[str] | None = None,
) -> list[Place]:
    """As many as `CANDIDATES` of `places` for her to choose from as she posts `at`: those
    right for its season and its slot in Tokyo (one with slots none late at night, before 6),
    none of `used` (by identifier), and only those under a roof if `roofed` (for rain, snow
    or thunder; `INDOOR`); a venue only if `venues` (where her lives on this day in a
    year before were) names it, and then first. The rest are drawn by weight: `LIKED` for
    a kind she `likes`, `HOLY` for one whose `idols` are hers. Of her work moment, only those
    of the kinds `within` names, or with `NEARBY` there, any in the outskirts; each as likely."""
    local = at.astimezone(TOKYO)
    season, slot = _SEASONS[local.month], _slot(local.hour)
    left = [
        p for p in places
        if p.id not in used
        and (not roofed or p.category in INDOOR)
        and (within is None or p.category in within or (NEARBY in within and p.nearby))
        and (p.seasons is None or season in p.seasons)
        and (p.slots is None or (slot is not None and slot in p.slots))
    ]
    drawn = [p for p in left if any(name in venues for name in p.venue_names)][:CANDIDATES]
    left = [p for p in left if p.category != "venue"]
    weights = [
        1 if within is not None else
        (LIKED if likes and p.category in likes else 1) * (HOLY if character_id in p.idols else 1)
        for p in left
    ]
    while left and len(drawn) < CANDIDATES:
        index = _weighted(random, weights)
        drawn.append(left.pop(index))
        weights.pop(index)
    return drawn


def draw_circle(
    mates: Sequence[str],
    related: Sequence[str],
    others: Sequence[str],
    birthdays: Collection[str],
    her_birthday: bool,
    random: Random,
) -> list[str]:
    """Her circle, of her unit `mates`, those a section of her facts is on (`related`) and
    the `others`, none of them twice: those of `mates` and `related` whose birthday it is
    (`birthdays`) first, then the others drawn for, as many as `CIRCLE`, or
    `BIRTHDAY_CIRCLE` on `her_birthday`, in the order drawn."""
    least, most = BIRTHDAY_CIRCLE if her_birthday else CIRCLE
    size = least + _index(random, most - least + 1)
    known = [*mates, *related]
    circle = [each for each in known if each in birthdays]
    strangers = list(others)
    if strangers and len(circle) < size and _draw(random) < STRANGER:
        circle.append(strangers.pop(_index(random, len(strangers))))
    left = [each for each in known if each not in circle]
    weights = [MATE if each in mates else RELATED for each in left]
    while left and len(circle) < size:
        index = _weighted(random, weights)
        circle.append(left.pop(index))
        weights.pop(index)
    while strangers and len(circle) < size:
        circle.append(strangers.pop(_index(random, len(strangers))))
    return circle


def draw_compositions(
    generating: bool, photographed: bool, random: Random, group: bool
) -> tuple[Composition, ...]:
    """The compositions her moment's picture may be in, none for no picture: none without
    image generation (`generating`), drawn for nothing; else `PICTURED` of the time every one
    but a group photo, that too where `group` (NovelAI's own format, one of her circle
    with photo tags), or only those no one is in (`UNPEOPLED`) where she has no photo tags
    (`photographed`)."""
    if not generating or _draw(random) >= PICTURED:
        return ()
    if not photographed:
        return UNPEOPLED
    return COMPOSITIONS if group else tuple(c for c in COMPOSITIONS if c != "group")


def draw_shown(
    posted_at: datetime, likes: int, comments: int, random: Random
) -> tuple[list[datetime], list[datetime]]:
    """When each of as many `likes` and `comments` on a moment posted at `posted_at` shows:
    the likes', each drawn within `LIKES_AFTER`; the comments', as many drawn within
    `COMMENTS_AFTER`, the earliest first."""
    return (
        [_within(posted_at, LIKES_AFTER, random) for _ in range(likes)],
        sorted(_within(posted_at, COMMENTS_AFTER, random) for _ in range(comments)),
    )


def draw_reply(commented_at: datetime, tier: Tier | None, random: Random) -> datetime | None:
    """When she replies to the producer's comment made at `commented_at`, in `tier`: within
    `REPLY_AFTER` it, by night as by day; None in a tier she does not reply in, or for None, in
    a cooldown."""
    if tier not in REPLY_AFTER:
        return None
    return _within(commented_at, REPLY_AFTER[tier], random)


def _within(
    start: datetime, after: tuple[timedelta, timedelta], random: Random
) -> datetime:
    """A time after `start` by at least the first of `after` and at most the second."""
    least, most = after
    return start + least + timedelta(seconds=int((most - least).total_seconds() * _draw(random)))


def _slot(hour: int) -> Slot | None:
    """The slot an hour in Tokyo is in; None late at night, before 6."""
    return None if hour < 6 else "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"


def _time(
    day: date, after: datetime, taken: Sequence[datetime], random: Random
) -> datetime | None:
    """A time in `day`'s parts, after `after`, `APART` from each `taken`; None if none is."""
    free = [(spans, weight) for start, end, weight in PARTS
            if (spans := _free(_span(day, start, end), after, taken))]
    if not free:
        return None
    weighed = _draw(random) * sum(weight for _, weight in free)
    for spans, weight in free:  # the last, should rounding leave it past them all
        if weighed < weight:
            break
        weighed -= weight
    length = sum((end - start for start, end in spans), timedelta())
    into = timedelta(seconds=int(length.total_seconds() * _draw(random)))
    for start, end in spans:
        if into < end - start:
            return start + into
        into -= end - start
    raise AssertionError("drew a time past the spans")


def _span(day: date, start: time, end: time) -> tuple[datetime, datetime]:
    """The part of `day` in Tokyo from `start` to `end`, midnight ending the day."""
    ends = day + timedelta(days=1) if end == time(0) else day
    return datetime.combine(day, start, TOKYO), datetime.combine(ends, end, TOKYO)


def _free(
    span: tuple[datetime, datetime], after: datetime, taken: Sequence[datetime]
) -> list[tuple[datetime, datetime]]:
    """What is left of `span` after `after`, and `APART` from each `taken`."""
    spans = [(max(span[0], after), span[1])]
    for at in taken:
        spans = [
            piece
            for start, end in spans
            for piece in ((start, min(end, at - APART)), (max(start, at + APART), end))
        ]
    return [(start, end) for start, end in spans if start < end]


def _draw(random: Random) -> float:
    """A number from 0 up to 1."""
    return random(PLACES) / PLACES


def _weighted(random: Random, weights: Sequence[int]) -> int:
    """One of as many places as `weights`, each as likely as it weighs."""
    weighed = _draw(random) * sum(weights)
    for i, weight in enumerate(weights):
        if weighed < weight:
            return i
        weighed -= weight
    return len(weights) - 1  # the last, should rounding leave it past them all


def _index(random: Random, length: int) -> int:
    """One of the first `length` places, each as likely."""
    return random(PLACES) * length // PLACES
