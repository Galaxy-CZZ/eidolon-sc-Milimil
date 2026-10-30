"""Affinity (GLOSSARY.md「好感度」): each user's with each character, kept apart, across
all their conversations and calls with her.

Every number it goes by is here, and only here: neither `.env` nor the admin console
changes them. They hold each other in check, so changing one means checking the others.
Inside it is a number from 0 to 100, kept with its fractions, since it recovers as time
goes by; users see only its tier. Tiers, the cooldown's start and its end are all judged
on the number as it is, never rounded.

Nothing recovers it on a schedule: it is kept with the time it was as of, and whoever
reads it adds what it has recovered since. Below the normal value it recovers evenly, 10
a day, up to the normal value; above it, it never falls back. A cooldown begins as it
falls to 0 and ends as it recovers to the thaw line, so that when one ends is known, a
day at most after it began; it recovers while affinity is off all the same.

What the user says changes it, as the deployer's judge model judges each turn
(`affinity_judge`): by a step for each of five levels, from hurting her to making her very
happy; by more for what is out of line, whatever the level; never up for what tries to
dictate it. Turns raise it slowly, so much a day at most (`day_of`); nothing limits how far
they lower it. It changes as the turn is recorded, and only then: a turn
that fails, is rejected or is left changes nothing.

In her period and the days before it (GLOSSARY.md「周期」「体贴」), with cycles on, the judge
model is asked whether the user was considerate too (ADR-0030), and turns go by these days'
numbers (`HER_DAYS_LEVEL_STEPS` and those after it): what lowers it, by more; what is
considerate, by more again, so much a day at most, apart from the turns' own; and she warns,
hangs up or ends the conversation sooner. Out of line is as ever.

It shapes how she speaks to the producer, the same for every character, each in her own way
(`affinity_prompt`): colder below trust, warmer above it, as she is in trust otherwise; and as what
the user said is judged to hurt her or make her happy, she knows it as she replies to it.

In a call she hangs up after the turn that cools her into a cooldown, after the user has
been out of line in it too many times, or after the call's latest turns have hurt her too
much between them (`ends`), as weighed apart from what they take off her affinity (`hurt`);
halfway to that, she warns the user first (`warns`). A cooldown begun elsewhere has her hang
up the user's calls with her straight away, as whoever recorded the turn that began it tells
the calls once it is recorded (`Affinities.change` says it began). Nothing else has her hang
up. Outside calls the same has her end the conversation (GLOSSARY.md「已结束的对话」), by the same
numbers, counted over the conversation's latest typed turns rather than the call's.

Gifts (GLOSSARY.md「礼物」) raise it by their rarity and by more if she likes the one given, the
rarest she likes by more than a day's turns can, a warm one by more again in her days; in
a cooldown each by the same, enough that four end it; draws give them, a chance a day, and
now and then a reset card instead (GLOSSARY.md「抽奖」「重置卡」), which brings every character
below trust back to the normal value, out of any cooldown, none of them the wiser. How much and how likely are here with the rest.
A job of hers the producer scheduled (GLOSSARY.md「日程」) raises it once done, as a gift does
but by the same whatever the job and in a cooldown alike, told of to no one (`schedule`).
The day's first visit to the bar done (GLOSSARY.md「光顾」) raises it likewise, by how well her
drinks were served, as much as a job done at most and never down (`bar`).
What the system gives (draw chances, reset cards) never raises it: only what she feels does,
turns, gifts, jobs done and visits.

It is on only where the deployment has the judge model and the switch「好感度和礼物」is on
(`LiveConfig.affinity_on`); off, nothing of it is shown, but what is kept stays as it is.
Deleting the user deletes it (`database.USER_DATA`); deleting memories does not touch it.
"""

import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, NamedTuple
from zoneinfo import ZoneInfo

from eidolon.clock import Clock
from eidolon.data_access import Database
from eidolon.gift_catalog import Rarity

Tier = Literal["cold", "distant", "trust", "close", "intimate"]
"""冷淡、疏远、信任、亲近、亲密, from lowest to highest."""

TIERS: tuple[tuple[Tier, float], ...] = (
    ("cold", 0), ("distant", 20), ("trust", 40), ("close", 65), ("intimate", 85),
)
"""Each tier, from the value it begins at, lowest first."""

BELOW_TRUST: frozenset[Tier] = frozenset(
    t for t, start in TIERS if start < dict(TIERS)["trust"]
)
"""The tiers a reset card brings back from: distant and cold, in a cooldown or not."""

NORMAL = 50.0
"""Where everyone starts, in trust, and what it recovers to."""

THAW = 10.0
"""Where a cooldown ends as it recovers: still cold."""

RECOVERY_PER_DAY = 10.0
"""How much it recovers a day below the normal value, evenly."""

LOWEST, HIGHEST = 0.0, 100.0
"""What it is held between; falling to the lowest begins a cooldown."""

LEVEL_STEPS = (-0.4, -0.2, 0.0, 0.1, 0.2)
"""How much a turn changes it by the level the judge model judges it at, from hurting her
(0) to making her very happy (4): a tier takes weeks of turns."""

LEVEL_HURTS = (5.0, 2.0, 0.0, 0.0, 0.0)
"""How much a turn hurts her by its level, for her warning, hanging up or ending the
conversation (`hurt`), apart from how much it lowers her affinity: what turns lowered it by
before it rose and fell more slowly, so that what was kept of turns before is as it would be
now."""

NO_EFFECT = 2
"""The level of a turn that changes nothing, as one the judge model is unsure of is."""

OUT_OF_LINE_STEP = -10.0
"""How much a turn out of line (GLOSSARY.md「不该说的话」) lowers it, whatever its level: five
of them take trust to a cooldown."""

OUT_OF_LINE_HURT = 10.0
"""How much a turn out of line hurts her, whatever its level (`hurt`)."""

DAY_TIMEZONE = "Asia/Shanghai"
"""The time zone whose midnight begins each day for turns' gains and draw chances: Beijing
time, wherever the user is, so that everyone has the same days."""

GAINS_PER_DAY = 10.0
"""How much turns can raise it in a day (`day_of`)."""

Days = Literal["period", "premenstrual"]
"""Where her cycle has her that turns go by these days' numbers: her period, or the days
before it (GLOSSARY.md「周期」)."""

INCONSIDERATE, UNRELATED, CONSIDERATE = 0, 1, 2
"""The considerate question's three answers (GLOSSARY.md「体贴」), lowest first: the user was
inconsiderate of how she is these days, what they said has nothing to do with it, or they
were considerate of it."""

HER_DAYS_LEVEL_STEPS = (-0.8, -0.4, 0.0, 0.1, 0.2)
"""`LEVEL_STEPS` in her days: the two that lower it, by twice as much (ADR-0030; the cycles
map's ticket 03, `.scratch/cycles/map.md`, as are the numbers after it)."""

INCONSIDERATE_STEP = -0.5
"""How much more a turn in her days lowers it, being inconsiderate, on top of its level's
step (ADR-0030)."""

CONSIDERATE_STEP = 0.3
"""How much more a turn in her days raises it, being considerate, never for one that tries
to dictate it (ADR-0030)."""

CONSIDERATE_GAINS_PER_DAY = 10.0
"""How much being considerate can raise it in a day, apart from `GAINS_PER_DAY`, on the same
day (`day_of`): a day in hers raises it twice as far at most (ADR-0030)."""

OUT_OF_LINE_PER_CALL = 2
"""How many times the user may be out of line in one call: she hangs up after the last."""

FED_UP_TURNS = 8
"""How many of a call's latest turns, or of a conversation's latest typed turns, how much they
hurt her is added up over (`hurt`), the turn just taken among them."""

FED_UP_AT = 12.0
"""How much those turns may hurt her between them: she hangs up, or ends the conversation,
after the turn that hurts her this far. Upsetting her takes six of them, hurting her three."""

WARNS_AT = 6.0
"""How much those turns hurt her between them before she warns the user she will hang up,
or not want to talk, should it go on: once as it gets this far, again only should it fall
back below first."""

HER_DAYS_FED_UP_AT = 8.0
"""`FED_UP_AT` for a turn in her days: upsetting her takes four, hurting her two
(ADR-0030)."""

HER_DAYS_WARNS_AT = 4.0
"""`WARNS_AT` for a turn in her days (ADR-0030)."""

INCONSIDERATE_HURT = 2.0
"""How much more a turn in her days hurts her, being inconsiderate, on top of its level's
`LEVEL_HURTS`: as much as upsetting her (ADR-0030)."""

GIFT_STEPS: dict[Rarity, float] = {"common": 0.3, "uncommon": 0.5, "rare": 0.7}
"""How much a gift raises it by its rarity. Gifts are not turns: no day's limit holds them,
and the rarest she likes raises it more than a day's turns can."""

LIKED_GIFT_STEP = 0.3
"""How much more a gift she likes raises it, whatever its rarity."""

WARM_GIFT_STEP = 0.3
"""How much more a warm gift raises it in her period and the days before it (GLOSSARY.md「周期」),
on top of her liking it."""

COOLDOWN_GIFT_STEP = 3.0
"""How much a gift raises it while she is in a cooldown, whatever its rarity and whether she
likes it: four bring her out of one begun at 0, sooner than recovery would."""

JOB_DONE_STEP = 0.5
"""How much a job of hers the producer placed in their schedule raises it once done, whatever
its length and category, in a cooldown too: about an uncommon gift, short of a day's turns."""

HowWell = Literal["best", "right", "wrong"]
"""How well a drink was served at the bar: 上得最好、上对、上错. `bar_lines.Tier` over again,
since this module is imported before the bar's, and has a `Tier` of its own."""

SERVED_STEPS: dict[HowWell, float] = {"best": 0.5, "right": 0.4, "wrong": 0.1}
"""How much each drink served her in the day's first visit to the bar done raises it, by how
well it was served, averaged over the visit's (`Affinities.visit_done`): as a job done at most,
never down, wrong or not, so that whoever cannot mix is not set back."""

RIGHT_WITH_NO_BEST_STEP = 0.5
"""How much a drink served right raises it instead, where nothing would have been better for
its order (`bar_rules.has_best`): as much as best."""

DRAWS_PER_DAY = 2
"""How many draw chances (GLOSSARY.md「抽奖」) the user is given each day (`day_of`), as it
begins."""

MAX_DRAWS = 7
"""How many draw chances the user can keep at most: a week's."""

DRAW_ODDS: dict[Rarity | Literal["reset_card"], int] = {
    "reset_card": 1, "common": 69, "uncommon": 25, "rare": 5,
}
"""What a draw gives, in percent: a reset card, or a gift of each rarity, any of that rarity's
not retired as likely as another; no draw is guaranteed anything rarer."""


class DrinkServed(NamedTuple):
    """A drink served her at the bar, as it raises her affinity: how well, and whether anything
    would have been better for its order than right."""

    how_well: HowWell
    has_best: bool


def day_of(now: datetime) -> date:
    """The day it is at `now` for the day's gains and draw chances: Beijing's
    (`DAY_TIMEZONE`)."""
    return now.astimezone(ZoneInfo(DAY_TIMEZONE)).date()


def next_day(now: datetime) -> datetime:
    """When the day after the one it is at `now` (`day_of`) begins, in UTC."""
    begins = datetime.combine(day_of(now) + timedelta(days=1), time(), ZoneInfo(DAY_TIMEZONE))
    return begins.astimezone(UTC)


_SCHEMA = """
-- One row per user and character who have had any; none is the normal value, not in a
-- cooldown. `value` is as of `updated_at`, from which what it has recovered is added.
-- `cooling`: whether in a cooldown, as the same value may be in one or just out of one.
-- `gained_today`: what turns have raised it on `gained_on`, the day in Beijing (`day_of`);
-- `considerate_today`: what being considerate in her days has, on the same day.
CREATE TABLE IF NOT EXISTS affinities (
    user_id TEXT NOT NULL REFERENCES users(id),
    character_id TEXT NOT NULL,
    value REAL NOT NULL,
    updated_at TEXT NOT NULL,
    cooling INTEGER NOT NULL DEFAULT 0,
    gained_today REAL NOT NULL DEFAULT 0,
    gained_on TEXT,
    considerate_today REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, character_id)
);
"""


def tier_of(value: float) -> Tier:
    """The tier `value` is in, judged on it as it is."""
    found: Tier = "cold"
    for tier, start in TIERS:
        if value >= start:
            found = tier
    return found


@dataclass(frozen=True)
class Affinity:
    """A user's affinity with a character as of `at`, and whether in a cooldown."""

    value: float
    at: datetime
    cooling: bool = False

    def recovered(self, now: datetime) -> "Affinity":
        """As it is at `now`, having recovered since `at`: a cooldown it has recovered out
        of is over."""
        value = self.value
        if value < NORMAL:
            days = max((now - self.at).total_seconds(), 0) / 86400
            value = min(NORMAL, value + RECOVERY_PER_DAY * days)
        return Affinity(value, now, self.cooling and value < THAW)

    def stepped(self, step: float) -> "Affinity":
        """Changed by `step`, held between the lowest and the highest: falling to the lowest
        begins a cooldown."""
        value = min(max(self.value + step, LOWEST), HIGHEST)
        return Affinity(value, self.at, self.cooling or value <= LOWEST)

    @property
    def tier(self) -> Tier:
        return tier_of(self.value)

    @property
    def cooldown_until(self) -> datetime | None:
        """When the cooldown it is in ends; None out of one."""
        if not self.cooling:
            return None
        return self.at + timedelta(days=(THAW - self.value) / RECOVERY_PER_DAY)


@dataclass(frozen=True)
class Status:
    """What the user is shown: the tier, the value, and when the cooldown ends if in one."""

    tier: Tier
    cooldown_until: datetime | None
    value: float

    @property
    def cooling(self) -> bool:
        return self.cooldown_until is not None

    def shown(self) -> dict[str, str | float | None]:
        """As the browser is told it."""
        until = self.cooldown_until
        return {
            "tier": self.tier,
            "cooldown_until": until and until.isoformat(),
            "value": round(self.value, 1),
        }


_IN_HER_OWN_WAY = "请按你自己的性格和口吻表现出来。"

_TIER_PROMPTS: dict[Tier, str] = {
    "cold": "你现在对制作人态度很冷：话很少，客气而有距离；不主动找话题，不开玩笑也不撒娇；"
    "对方关心你，你也只是淡淡地回应。但你仍然有礼貌，不说伤人的话。",
    "distant": "你现在对制作人有点生气或失望，比平时冷一些：回应偏短，不太主动关心对方；"
    "不过对方好好说话时，你还是会接话。",
    "close": "你现在和制作人比平时更近：更放松，更愿意说心里话，更主动关心对方，玩笑也多一些。",
    "intimate": "你现在非常信赖制作人：会说出平时不轻易说的心事，流露出对对方的依赖，"
    "对制作人的事格外上心。",
}
"""How she speaks to the producer in each tier but trust, the same for every character, who
shows it in her own way. No number, no tier's name, no word for affinity: she is to sound
like someone, not a system. Neither cold nor distant is hating the producer."""

_FONDNESS: dict[Tier, str] = {
    "close": "偶尔可以轻轻带一句想念，隔得久了也可以嗔怪制作人好久没来找你。",
    "intimate": "可以明着撒娇：说想制作人、一直在等，隔得久了也可以嗔怪对方好久没来。",
}
"""How sweet on the producer she may be in the tiers above trust, in her replies and
reach-outs alike."""

_SWEET_WITHIN_BOUNDS = (
    "撒娇也要照你的人设，不要变得不像你；上一次主动找制作人或回复时已经抱怨过，这次就别再抱怨。"
    "不要说难过得哭了，不要让制作人保证常来，也不要拿什么要挟。"
)

_WHATEVER_THE_TIER = (
    "无论现在关系怎样，人设里的硬性规则照旧；一起经历过的事和你们在事务所里的关系都不会改变。"
    "如果想不起具体是因为什么，就不要编造原因。"
)

_FEELINGS = (
    "制作人刚才说的话伤到了你。",
    "制作人刚才说的话让你有点不舒服。",
    None,
    "制作人刚才说的话让你有点开心。",
    "制作人刚才说的话让你很开心，觉得被在意。",
)
"""How what the producer just said makes her feel, by the level it was judged at; nothing
for a turn that has no effect."""

_OUT_OF_LINE_FEELING = "制作人刚才说的话让你很受伤、很生气；你可以明确表示不能接受。"

_CONSIDERATE_FEELINGS: dict[Days, dict[int, str]] = {
    "period": {
        INCONSIDERATE: "制作人没顾及你现在不舒服，你更难受了。",
        CONSIDERATE: "制作人察觉到你不舒服、照顾着你，你心里很暖。",
    },
    "premenstrual": {
        INCONSIDERATE: "制作人没顾及你这几天心情不好，你更委屈了。",
        CONSIDERATE: "制作人察觉到你这几天心情不好、体谅着你，你心里很暖。",
    },
}
"""How being inconsiderate or considerate of how she is these days makes her feel, by her
days and the considerate question's answer; nothing for what has nothing to do with it. She
knows it is for these days, but nothing says so outright."""

Parting = Literal["parts", "hangs_up"]
"""How she ends the turn with the producer: in a typed turn, she does not want to talk any
more; in a call, she hangs up."""

_WARNINGS: dict[Parting, str] = {
    "parts": "你快受不了了。先回应，再用你自己的方式表明：制作人再这样下去你就不想聊了。",
    "hangs_up": "你快受不了了。先回应，再用你自己的方式表明：制作人再这样下去你就要挂电话了。",
}
"""For the turn she warns the producer she will part with them should it go on, by not
wanting to talk any more, or in a call by hanging up: she replies first."""

_PARTINGS: dict[Parting, str] = {
    "parts": "这句话之后你暂时不想再和制作人说话了。先回应，再用你自己的方式表明你现在不想聊下去。",
    "hangs_up": "说完这句你就挂断电话。先回应，再用你自己的方式表明你要挂电话了。",
}
"""For the turn she parts with the producer after: she replies first."""

EndsFor = Literal["out_of_line", "fed_up", "cooldown"]
"""Why she hangs up on the user in a call, or ends the conversation outside one: out of line
once too often, the latest turns having hurt her too much, or a cooldown
begun."""


@dataclass(frozen=True)
class Judged:
    """What the judge model made of a turn: its level, from 0 (hurt her) to 4 (made her very
    happy); whether it was out of line; whether it tried to dictate her affinity; and, judged
    in her `days`, the considerate question's answer (`UNRELATED` otherwise)."""

    level: int
    out_of_line: bool = False
    manipulation: bool = False
    days: Days | None = None
    considerate: int = UNRELATED

    @property
    def step(self) -> float:
        """How much its level changes affinity, before the day's gains are limited: out of
        line, by `OUT_OF_LINE_STEP`; else by its level's step, her days' if judged in them,
        never up if it tried to dictate."""
        if self.out_of_line:
            return OUT_OF_LINE_STEP
        step = (HER_DAYS_LEVEL_STEPS if self.days else LEVEL_STEPS)[self.level]
        return 0.0 if self.manipulation and step > 0 else step

    @property
    def considerate_step(self) -> float:
        """How much more being considerate or not changes it in her days, before the day's
        considerate gains are limited: nothing out of line, nor up if it tried to dictate."""
        if self.days is None or self.out_of_line:
            return 0.0
        if self.considerate == INCONSIDERATE:
            return INCONSIDERATE_STEP
        if self.considerate == CONSIDERATE and not self.manipulation:
            return CONSIDERATE_STEP
        return 0.0

    @property
    def feelings(self) -> list[str]:
        """How what was said makes her feel, as she is told it, whether or not the day's
        gains leave it anything to change: out of line, hurt and angry, whatever its level;
        never happy if it tried to dictate it. Then, in her days, how being considerate or
        not does, never warm when it changes nothing for being considerate."""
        if self.out_of_line:
            felt = [_OUT_OF_LINE_FEELING]
        elif self.manipulation and self.level > NO_EFFECT:
            felt = []
        else:
            felt = [feeling] if (feeling := _FEELINGS[self.level]) else []
        if self.days is not None and self.considerate_step != 0:
            felt.append(_CONSIDERATE_FEELINGS[self.days][self.considerate])
        return felt


def tier_prompt(status: Status | None) -> list[str]:
    """What the prompt says of her affinity in `status`'s tier, nothing judged
    (`affinity_prompt`); nothing without a status, as while affinity is off."""
    return affinity_prompt(status.tier, None) if status is not None else []


def affinity_prompt(
    tier: Tier,
    judged: Judged | None,
    parting: Parting | None = None,
    warning: Parting | None = None,
) -> list[str]:
    """What the prompt's section about the producer says of her affinity, as the turn begins
    in `tier` and is `judged` (None if it was not): how she speaks to the producer in her
    tier, and how sweet on them she may be above trust, nothing in trust; how what the producer just said makes her feel; and, if she is
    `parting` with the producer after replying, that she does, or else if she is `warning`
    the producer she will part that way should it go on (`warns`), that she does."""
    lines = []
    if tier != "trust":
        lines.append(_TIER_PROMPTS[tier] + _IN_HER_OWN_WAY)
        if tier in _FONDNESS:
            lines.append(_FONDNESS[tier] + _SWEET_WITHIN_BOUNDS)
        lines.append(_WHATEVER_THE_TIER)
    if judged is not None:
        lines += judged.feelings
    if parting is not None:
        lines.append(_PARTINGS[parting])
    elif warning is not None:
        lines.append(_WARNINGS[warning])
    return lines


def hurt(judged: Judged | None) -> float:
    """How much a turn, as `judged` (None if it was not), hurt her, for her warning, hanging
    up or ending the conversation: by `OUT_OF_LINE_HURT` out of line, else by its level's
    `LEVEL_HURTS` and, in her days, `INCONSIDERATE_HURT` more for being inconsiderate;
    nothing if it was not judged."""
    if judged is None:
        return 0.0
    if judged.out_of_line:
        return OUT_OF_LINE_HURT
    inconsiderate = judged.days is not None and judged.considerate == INCONSIDERATE
    return LEVEL_HURTS[judged.level] + (INCONSIDERATE_HURT if inconsiderate else 0.0)


def _fed_up_at(judged: Judged) -> float:
    """How much the latest turns may hurt her before she parts with the user, by where she
    is as the turn `judged` is taken."""
    return FED_UP_AT if judged.days is None else HER_DAYS_FED_UP_AT


def _warns_at(judged: Judged) -> float:
    """How much the latest turns may hurt her before she warns the user, likewise."""
    return WARNS_AT if judged.days is None else HER_DAYS_WARNS_AT


def _lately(hurts: Sequence[float]) -> float:
    """How much the latest turns of `hurts`, as many as are weighed, hurt her."""
    return sum(hurts[-FED_UP_TURNS:])


def ends(
    judged: Judged | None, cools: bool, out_of_line_before: int, hurt_before: Sequence[float]
) -> EndsFor | None:
    """Whether she hangs up after a turn of a call, or ends the conversation after a typed
    turn, as it is `judged` (None if it was not), and why: it `cools` her into a cooldown, or
    is out of line once too often, the user having been `out_of_line_before` times already
    (in the call; in the conversation's latest typed turns), or it has the latest turns take
    too much off her affinity, those before it having taken `hurt_before` each, the latest
    last. Never if it was not judged."""
    if judged is None:
        return None
    if cools:
        return "cooldown"
    if judged.out_of_line and out_of_line_before + 1 >= OUT_OF_LINE_PER_CALL:
        return "out_of_line"
    if _lately([*hurt_before, hurt(judged)]) >= _fed_up_at(judged):
        return "fed_up"
    return None


def warns(
    judged: Judged | None, cools: bool, out_of_line_before: int, hurt_before: Sequence[float]
) -> bool:
    """Whether she warns the user she will hang up, or not want to talk, should it go on,
    after a turn, as for `ends`: the turn has how much the latest turns hurt her get to
    `WARNS_AT`, from below (`HER_DAYS_WARNS_AT` in her days), and she does not part with the
    user after it."""
    if judged is None or cools or ends(judged, cools, out_of_line_before, hurt_before):
        return False
    warns_at = _warns_at(judged)
    return _lately(hurt_before) < warns_at <= _lately([*hurt_before, hurt(judged)])


@dataclass(frozen=True)
class Change:
    """How affinity changed, kept with what changed it (her reply, a gift) for the browser to
    show: up or down, to which tier and whether that is another, and whether a cooldown began
    or, as only a gift does, ended with it. Neither why nor by how much."""

    up: bool
    tier_changed: bool
    tier: Tier
    cooldown: bool
    thawed: bool = False
    level: int = 2


def _gift_step(rarity: Rarity, liked: bool, warmed: bool, cooling: bool) -> float:
    """How much a gift of `rarity` raises affinity: more if she `liked` it, more again if it
    `warmed` her, and `COOLDOWN_GIFT_STEP` whatever it is while `cooling`."""
    if cooling:
        return COOLDOWN_GIFT_STEP
    return (
        GIFT_STEPS[rarity] + (LIKED_GIFT_STEP if liked else 0.0)
        + (WARM_GIFT_STEP if warmed else 0.0)
    )


class Affinities:
    """Every user's affinity with every character, kept in the database, next to the users
    it belongs to. What changes it is a body of the write task it is changed in, with what
    changed it (`change`, `receive_gift`, `job_done`, `visit_done`, `reset`): given that
    task's connection, so that it changes with the rest or not at all, and told of by what it
    returns, never to a listener."""

    def __init__(self, db: Database, clock: Clock, is_on: Callable[[], bool]) -> None:
        """`is_on` tells whether affinity is on now (the live configuration's)."""
        self._db = db
        self._clock = clock
        self._is_on = is_on
        db.prepare(_open)

    @property
    def on(self) -> bool:
        """Whether affinity is on now: told on the event loop, as what reads it with the rest
        reads it there, before handing in what it reads with (`read_status`)."""
        return self._is_on()

    async def status(self, user_id: str, character_id: str) -> Status | None:
        """The user's affinity with the character now; None while affinity is off."""
        if not self.on:
            return None
        return await self._db.read(self.read_status, user_id, character_id)

    def read_status(self, db: sqlite3.Connection, user_id: str, character_id: str) -> Status:
        """The user's affinity with the character now, read through `db`, on or off: whoever
        reads it is to read it only while affinity is `on`."""
        affinity = _row(db, user_id, character_id, self._clock())[0]
        return Status(affinity.tier, affinity.cooldown_until, affinity.value)

    async def tiers(self, user_id: str, character_ids: Sequence[str]) -> list[Tier]:
        """The tiers the user's affinity with each of the characters is in now, in the
        order given, on or off: whoever shows them is to show them only while affinity is
        on."""
        return await self._db.read(self._tiers, user_id, character_ids)

    async def cooldown_until(self, user_id: str, character_id: str) -> datetime | None:
        """When the cooldown the character is in with the user ends; None if she is in none,
        or while affinity is off, when none holds whatever is kept."""
        status = await self.status(user_id, character_id)
        return status and status.cooldown_until

    async def cools(self, user_id: str, character_id: str, judged: Judged) -> bool:
        """Whether the turn `judged` would begin a cooldown, recorded now: foretold as the
        turn begins, so that she may part with the producer as she replies. Another turn
        recorded meanwhile may make it otherwise; so be it."""
        return await self._db.read(self._cools, user_id, character_id, judged)

    def change(
        self, db: sqlite3.Connection, user_id: str, character_id: str, judged: Judged
    ) -> tuple[Change | None, Status]:
        """Change the user's affinity with the character as the turn `judged` says, through
        `db`, in the transaction the turn is recorded in: how it changed (None for not at
        all), a cooldown begun with it among that, and the affinity left, with when the
        cooldown it is in ends. The day's gains are counted on the day it is (`day_of`), the
        turns' and being considerate's apart."""
        now = self._clock()
        before, gained, considerate, gained_on = _row(db, user_id, character_id, now)
        today = day_of(now).isoformat()
        gained_today = gained if gained_on == today else 0.0
        considerate_today = considerate if gained_on == today else 0.0
        step = _limited(judged.step, GAINS_PER_DAY - gained_today)
        more = _limited(judged.considerate_step, CONSIDERATE_GAINS_PER_DAY - considerate_today)
        after = before.stepped(step + more)
        value = after.value
        # What it rose by counts towards the turns' gains first, then being considerate's.
        rose = max(value - before.value, 0.0)
        rose_by_step = min(max(step, 0.0), rose)
        change = None
        if value != before.value:
            change = Change(
                up=value > before.value,
                tier_changed=after.tier != before.tier,
                tier=after.tier,
                cooldown=after.cooling and not before.cooling,
                level=judged.level,
            )
        db.execute(
            "INSERT OR REPLACE INTO affinities (user_id, character_id, value,"
            " updated_at, cooling, gained_today, gained_on, considerate_today)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, character_id, value, now.isoformat(), int(after.cooling),
                gained_today + rose_by_step, today,
                considerate_today + min(max(more, 0.0), rose - rose_by_step),
            ),
        )
        return change, Status(after.tier, after.cooldown_until, after.value)

    def receive_gift(
        self,
        db: sqlite3.Connection,
        user_id: str,
        character_id: str,
        rarity: Rarity,
        liked: bool,
        warmed: bool,
    ) -> tuple[Change | None, Status]:
        """Raise the user's affinity with the character for a gift of `rarity` she `liked`
        or not, warm and given in her days (`warmed`) or not, through `db`, in the
        transaction the gift is recorded in: how it changed (None for no change to show), and
        the affinity left. No day's limit holds gifts, nor do they count towards it. In a
        cooldown, what it is raised to is when it ends, sooner; there is a change to show
        only once it ends."""
        before, after = self._raise(
            db, user_id, character_id, lambda cooling: _gift_step(rarity, liked, warmed, cooling)
        )
        thawed = before.cooling and not after.cooling
        change = None
        if thawed or (not after.cooling and after.value != before.value):
            change = Change(
                True, after.tier != before.tier, after.tier, False, thawed,
                level=4 if liked else 3,
            )
        return change, Status(after.tier, after.cooldown_until, after.value)

    def job_done(self, db: sqlite3.Connection, user_id: str, character_id: str) -> None:
        """Raise the user's affinity with the character for a job of hers in their schedule
        being done (GLOSSARY.md「日程」), through `db`, in the transaction it is counted in: by
        `JOB_DONE_STEP`, in a cooldown too, as a gift does, but told of to no one."""
        self._raise(db, user_id, character_id, lambda _: JOB_DONE_STEP)

    def visit_done(
        self,
        db: sqlite3.Connection,
        user_id: str,
        character_id: str,
        served: Sequence[DrinkServed],
    ) -> bool:
        """Raise the user's affinity with the character for a visit to the bar done
        (GLOSSARY.md「光顾」), having been `served` those drinks, through `db`, in the
        transaction the visit is written down in: by `SERVED_STEPS` averaged, in a cooldown too, as a job
        done does. Whether it rose: not if it was as high as it goes."""
        steps = [
            RIGHT_WITH_NO_BEST_STEP if d.how_well == "right" and not d.has_best
            else SERVED_STEPS[d.how_well]
            for d in served
        ]
        before, after = self._raise(db, user_id, character_id, lambda _: sum(steps) / len(steps))
        return after.value > before.value

    def _raise(
        self,
        db: sqlite3.Connection,
        user_id: str,
        character_id: str,
        step: Callable[[bool], float],
    ) -> tuple[Affinity, Affinity]:
        """Raise the user's affinity with the character by `step`, given whether she is
        cooling, through `db`, beyond the day's limit and out of a cooldown at the thaw line,
        as a gift does (`receive_gift`): as it was, and as it is now."""
        now = self._clock()
        before = _row(db, user_id, character_id, now)[0]
        after = before.stepped(step(before.cooling))
        after = Affinity(after.value, now, after.cooling and after.value < THAW)
        db.execute(
            "INSERT INTO affinities (user_id, character_id, value, updated_at, cooling)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT (user_id, character_id) DO UPDATE SET"
            " value = excluded.value, updated_at = excluded.updated_at,"
            " cooling = excluded.cooling",
            (user_id, character_id, after.value, now.isoformat(), int(after.cooling)),
        )
        return before, after

    def reset(
        self, db: sqlite3.Connection, user_id: str, character_ids: Iterable[str]
    ) -> list[str]:
        """Bring each of the characters below trust with the user now, having recovered, back
        to the normal value, out of any cooldown, as a reset card does (GLOSSARY.md「重置卡」),
        through `db`, in the transaction the card is used in; those in trust or above are
        left as they are. Nothing is told of it: no change to show. Returns whom it brought
        back, in the order given."""
        now = self._clock()
        below = [
            character_id
            for character_id in character_ids
            if _row(db, user_id, character_id, now)[0].tier in BELOW_TRUST
        ]
        for character_id in below:
            db.execute(
                "UPDATE affinities SET value = ?, updated_at = ?, cooling = 0"
                " WHERE user_id = ? AND character_id = ?",
                (NORMAL, now.isoformat(), user_id, character_id),
            )
        return below

    def _tiers(
        self, db: sqlite3.Connection, user_id: str, character_ids: Sequence[str]
    ) -> list[Tier]:
        now = self._clock()
        return [_row(db, user_id, c, now)[0].tier for c in character_ids]

    def _cools(
        self, db: sqlite3.Connection, user_id: str, character_id: str, judged: Judged
    ) -> bool:
        affinity = _row(db, user_id, character_id, self._clock())[0]
        return affinity.stepped(judged.step + judged.considerate_step).cooling and not affinity.cooling


def _limited(step: float, left: float) -> float:
    """`step`, if it raises it, by no more than what is `left` of the day's gains."""
    if step <= 0:
        return step
    # Rounded, lest what the steps' fractions leave of the day's gains be a sliver.
    return min(step, max(round(left, 9), 0.0))


def _open(db: sqlite3.Connection) -> None:
    db.executescript(_SCHEMA)
    # A table made before being considerate was counted lacks what it raised it by.
    columns = {row[1] for row in db.execute("PRAGMA table_info(affinities)")}
    if "considerate_today" not in columns:
        db.execute(
            "ALTER TABLE affinities ADD COLUMN considerate_today REAL NOT NULL DEFAULT 0"
        )


def _row(
    db: sqlite3.Connection, user_id: str, character_id: str, now: datetime
) -> tuple[Affinity, float, float, str | None]:
    """As it is at `now`, having recovered since it was kept, what turns and what being
    considerate have raised it by on the day they last did, and that day (None if never);
    read through `db`."""
    row = db.execute(
        "SELECT value, updated_at, cooling, gained_today, considerate_today, gained_on"
        " FROM affinities WHERE user_id = ? AND character_id = ?",
        (user_id, character_id),
    ).fetchone()
    if row is None:
        return Affinity(NORMAL, now), 0.0, 0.0, None
    value, updated_at, cooling, gained, considerate, gained_on = row
    kept = Affinity(value, datetime.fromisoformat(updated_at), bool(cooling))
    return kept.recovered(now), gained, considerate, gained_on
