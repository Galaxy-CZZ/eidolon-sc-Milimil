"""The bar (GLOSSARY.md「酒吧」「光顾」): characters come to VA-283, order, and the producer
serves them; the chat model writes what is said, the server decides everything else.

`Bar` is all there is to it from outside: reading it (whether it is open, its drinks, whether
a visit done today would be rewarded), a user coming in, serving a drink, trying a call again,
and leaving.
Everything a visit draws, judges, writes down and is rewarded with is done in here; the API
only carries it over HTTP.

**A visit.** Each user has at most one at a time, kept in memory and named by an id made up
for it; coming in again does away with the one before, and one untouched for `IDLE` is done
away with as it is next touched, or swept away (`keep_sweeping`). As she comes in, the server
draws who she is: the user's character of the day (Beijing's, `affinity.day_of`), by the user and
the day alone, until they have a visit done that day, and from then on anyone, each as
likely; whether she is in a cooldown or not. Then her reason for coming: half the time the
job of hers the producer scheduled today and she has done, if there is one, else one of the
list's not for leaving her out (`not_for`) and none of her `bar_visits.RECENT_VISITS` latest
visits with the user, unless that leaves none; the topic likewise, and her facts it finds
(`bar_facts`), looked up under the visit's record; and how many drinks she has
(`bar_rules.CUPS`). Each of her orders is drawn just before the call that has her order
it (`bar_rules.draw_order`), knowing whether the user is a novice at the bar and what she
wanted the last time.

**Calls.** A visit is written in as many calls as she has drinks, and one more: her coming in
and first order; after each drink served, her reaction, the talk and her next order; after
the last she has, her reaction, a short talk and her farewell (`bar_prompt`). The last she
has is the last planned, or the one that leaves her drunk (`bar_rules.drunk`), who then
talks and says goodbye drunk. Each streams her lines and the producer's as they close
(`bar_reply`); the line she orders in is held back to the end of its call, with what follows
it, and sent with the order memo once it names drinks as it should
(`bar_rules.names_rightly`): if it does not, the call is made again for it alone, told so,
and if that does not either, she says one of the fixed lines instead
(`bar_rules.fixed_order`).

**Failing.** A call that fails, or writes no line it needs, is made again at once, once
(`ATTEMPTS`), the browser told to clear what it sent (`Retrying`); failing again, the visit
stops before it (`VisitFailed`) till it is tried again (`Bar.retry`), on the order drawn for
it, or ended. Her farewell is not stopped before: she says it in fixed lines instead
(`bar_rules.fixed_farewell`), and the visit is done all the same.

**Let in.** Who she is drawn, the visit is let in as a text turn is (`Admissions.visit`), in a
cooldown or not: the keys it runs on, the user's own LLM if they bring one, its activity
record, and its use of the limit, refused over it (`OverLimit`). Every call of the visit,
and rewriting her order, runs on those keys, its service calls recorded under that record;
the keys are held until the visit is over, as a call holds them. As it is over it is
settled, once, whether anyone waits for it or not: done, from the moment its farewell is to
be written down; failed, if it ends stopped before a call that failed, however it ends; else
left: left, done away with by another or untouched, the page gone while a call is being
written (read or not, `BarCall`), or under way as the bar is closed. One failed with nothing
yet written is given back.

**Serving.** What the bar counter holds is matched against the recipes (`DrinkCatalog.match`):
broken, it is refused and nothing changes; anything else is served her and judged
(`bar_rules.judged`), the producer saying one of the fixed lines as he does.

**Done.** A visit is done the moment its farewell is written: one row is written down for it
(`visit_records`, one of a user's data, `database.USER_DATA`): who came, when, why, what about,
each order, whether she got drunk; nothing of what was said. Her visits with the user done
are what she remembers of the bar, next time; a visit left before it is done is not.

**Rewarded.** The user's first visit done of the day she came in on, while affinity and gifts
are on (`LiveConfig.affinity_on`), is rewarded as it is written down, in the same transaction:
a draw chance, held to the most kept (`Gifts.reward_draw`), keyed by the day; and her affinity
raised by how well each drink was served (`Affinities.visit_done`), whether there was a best
for its order or not (`bar_rules.has_best`). Told of as the visit is done; no conversation
event, nothing in the conversations. Later visits that day give nothing.

Nothing of the bar is told to the conversations, nor written in them or in memory.
"""

import asyncio
import hashlib
import json
import logging
import secrets
import sqlite3
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Coroutine, Sequence
from contextlib import aclosing
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any, Literal, TypeVar

from eidolon.activity import Result
from eidolon.admission import Admission, Admissions
from eidolon.affinity import Affinities, DrinkServed, day_of, tier_prompt
from eidolon.bar_facts import BarFacts
from eidolon.bar_lines import BarLines
from eidolon.bar_prompt import (
    Remembered,
    farewell_ask,
    opening_ask,
    prompt,
    rewrite_ask,
    serving_ask,
    shared_prompt,
    visit_prompt,
)
from eidolon.bar_reply import BarLine, BarParser
from eidolon.bar_rules import (
    NOVICE_VISITS,
    Had,
    Known,
    Order,
    Reason,
    Serving,
    cups,
    draw_order,
    drunk,
    fixed_farewell,
    fixed_order,
    has_best,
    judged,
    names_rightly,
)
from eidolon.bar_visits import RECENT_VISITS, BarVisits, Topic
from eidolon.bar_visits import Reason as ListedReason
from eidolon.characters import Character
from eidolon.clock import Clock
from eidolon.data_access import Database
from eidolon.drink_catalog import DrinkCatalog, Mixture
from eidolon.gifts import Gifts
from eidolon.her_now import HerNow, KnownNow
from eidolon.llm import ChatLLM
from eidolon.own_keys import BroughtKeys, OwnKeyFailed, TurnKeys
from eidolon.producer import ProducerProfile, producer_prompt
from eidolon.randomness import Random
from eidolon.schedule import Job
from eidolon.store import read_profile
from eidolon.world import World

log = logging.getLogger(__name__)

FAILED = "出了点问题，这次光顾没能接着写下去，请稍后再来"

ATTEMPTS = 2
"""How many times a call of a visit is tried: once, and once more should it fail."""

IDLE = timedelta(minutes=30)
"""How long a visit lasts untouched: from then on it is gone."""

SWEEP = timedelta(minutes=5)
"""How often visits untouched for `IDLE` are looked for, to be done away with."""

_SCHEMA = """
-- One row per visit done (GLOSSARY.md「光顾」): who came to whom, as she came in and as she
-- said goodbye, the day she came in on (Beijing's), her reason for coming (its identifier, or
-- the job's name where it was one of hers done that day) and topic, each order as JSON (what
-- she wanted, how she said it, what was served, whether big, how well), whether she got
-- drunk, and whether the visit was rewarded. Nothing of what was said.
CREATE TABLE IF NOT EXISTS visit_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    character_id TEXT NOT NULL,
    entered_at TEXT NOT NULL,
    left_at TEXT NOT NULL,
    entered_on TEXT NOT NULL,
    reason TEXT NOT NULL,
    topic TEXT NOT NULL,
    orders TEXT NOT NULL,
    drunk INTEGER NOT NULL,
    rewarded INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS visit_records_by_her ON visit_records (user_id, character_id, id);
CREATE INDEX IF NOT EXISTS visit_records_by_day ON visit_records (user_id, entered_on);
"""


class BarClosed(Exception):
    """The deployment has the bar off: no one comes in."""

    def __init__(self) -> None:
        super().__init__("酒吧暂时没有开放")


class VisitGone(Exception):
    """There is no such visit of the user's under way: never was, left, done, or done away
    with by another."""

    def __init__(self) -> None:
        super().__init__("这次光顾已经结束了")


class NotWaiting(Exception):
    """She is not waiting for a drink: her lines are still being written."""

    def __init__(self) -> None:
        super().__init__("她还没在等这一杯")


class NotFailed(Exception):
    """Her lines have not failed to be written: there is nothing to try again."""

    def __init__(self) -> None:
        super().__init__("现在没有要再试的")


class BrokenDrink(Exception):
    """What the bar counter holds is none of the drinks: it cannot be served."""

    def __init__(self) -> None:
        super().__init__("调坏了，不能上")


@dataclass(frozen=True)
class VisitBegan:
    visit_id: str
    character_id: str

    def shown(self) -> dict:
        return {"type": "visit", "visit_id": self.visit_id, "character_id": self.character_id}


@dataclass(frozen=True)
class Memo:
    """The order memo, after the line she ordered in."""

    text: str

    def shown(self) -> dict:
        return {"type": "memo", "text": self.text}


@dataclass(frozen=True)
class Waiting:
    """The call is written: she waits for her drink."""

    def shown(self) -> dict:
        return {"type": "waiting"}


@dataclass(frozen=True)
class Retrying:
    """The call failed and is made again: what it sent is to be cleared."""

    def shown(self) -> dict:
        return {"type": "retrying"}


@dataclass(frozen=True)
class Rewarded:
    """What a visit done was rewarded with: draw chances (none if the user had the most kept
    already), and whether her affinity rose."""

    draws: int
    affinity_up: bool


@dataclass(frozen=True)
class VisitDone:
    """Her farewell is written: the visit is done, rewarded or not (None)."""

    rewarded: Rewarded | None = None

    def shown(self) -> dict:
        rewarded = self.rewarded
        return {"type": "done", "rewarded": rewarded and asdict(rewarded)}


@dataclass(frozen=True)
class VisitFailed:
    """The call could not be written, tried again or not: the visit stops before it, till it
    is tried again or left."""

    message: str

    def shown(self) -> dict:
        return {"type": "failed", "message": self.message}


BarEvent = VisitBegan | BarLine | Memo | Waiting | Retrying | VisitDone | VisitFailed


class BarCall:
    """The events of one call of a visit, to be read through, and closed once they are or the
    page is gone, read or not: closed while her lines are still being written, the visit is
    left."""

    def __init__(
        self, events: AsyncGenerator[BarEvent, None], stopped: Callable[[], None]
    ) -> None:
        self._events = events
        self._stopped = stopped

    def __aiter__(self) -> AsyncIterator[BarEvent]:
        return self._events

    async def aclose(self) -> None:
        self._stopped()
        await self._events.aclose()

Step = Literal["writing", "waiting", "failed"]
"""Where a visit is: her lines being written, waiting for a drink, or stopped before a call
that failed."""

_Listed = TypeVar("_Listed", ListedReason, Topic)
T = TypeVar("T")


@dataclass
class _Visit:
    id: str
    user_id: str
    character: Character
    entered_at: datetime
    entered_on: date
    """Beijing's day she came in on, which the visit is of."""
    reason: Reason
    topic: Topic
    cups: int
    known: Known
    """What her orders are drawn knowing."""
    shared: str
    """The first part of every call's prompt (`bar_prompt.shared_prompt`)."""
    about: str
    """The second (`bar_prompt.visit_prompt`)."""
    admission: Admission[TurnKeys]
    """How it was let in: the keys its calls run on, its record and its use of the limit."""
    orders: list[Order] = field(default_factory=list)
    servings: list[Serving] = field(default_factory=list)
    written: list[tuple[str, list[BarLine]]] = field(default_factory=list)
    """What each call so far asked for, and what was written."""
    drunk: bool = False
    """Whether she has had as much as she holds (`bar_rules.drunk`)."""
    step: Step = "writing"
    asking: str = ""
    """What the call it is at asks for, to try it again should it fail."""
    touched: datetime = field(init=False)
    """When it was last touched: come in, served, tried again, or a call of it over."""
    calls: int = 0
    """How many calls of it were made: the latest is the one its step is of."""

    def __post_init__(self) -> None:
        self.touched = self.entered_at


@dataclass(frozen=True)
class _Before:
    """What a user coming in reads first: whether they have a visit done today, and how many
    they have done, with anyone."""

    done_today: bool
    visits_done: int


@dataclass(frozen=True)
class _Hers:
    """What is read of her visits with the user before she comes in, and who they are."""

    remembered: Remembered
    reasons: frozenset[str]
    """Her latest visits' reasons for coming."""
    topics: frozenset[str]
    about_producer: str


class Bar:
    """The bar, and every user's visit under way."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        characters: dict[str, Character],
        catalog: DrinkCatalog,
        listed: BarVisits,
        lines: BarLines,
        admissions: Admissions,
        is_on: Callable[[], bool],
        random: Random,
        her_now: HerNow,
        *,
        world: World | None = None,
        affinities: Affinities | None = None,
        gifts: Gifts | None = None,
        facts: BarFacts | None = None,
    ) -> None:
        """`is_on` tells whether the bar is open now (the live configuration's switch). Without
        `world`, she has no world setting; without `affinities` or `gifts`, no reward. `her_now`
        gives what she knows of now coming in, her job done today for a reason among it.
        Without `facts`, none of her facts are looked up. Her reasons for coming and
        topics are drawn from `listed`. Visits are let in by `admissions`."""
        self._db = db
        self._clock = clock
        self._characters = characters
        self._catalog = catalog
        self._listed = listed
        self._lines = lines
        self._admissions = admissions
        self._is_on = is_on
        self._random = random
        self._world = world
        self._affinities = affinities
        self._gifts = gifts
        self._her_now = her_now
        self._facts = facts
        self._visits: dict[str, _Visit] = {}
        """Each user's visit under way, by user."""
        self._settles: set[asyncio.Future[Any]] = set()
        """Visits over, till they are settled."""
        db.prepare(_open)

    def character(self, character_id: str) -> Character | None:
        """The character `character_id`, for her voice and the like; None if the bar has no
        such."""
        return self._characters.get(character_id)

    async def read(self, user_id: str) -> dict:
        """Whether the bar is open and, if it is, its drinks in catalog order, and whether the
        user would be rewarded for a visit done today: none done yet, and rewards given."""
        if not self._is_on():
            return {"enabled": False}
        reward_today = self._rewarding and not await self._db.read(
            _done_on, user_id, day_of(self._clock())
        )
        return {"enabled": True, "drinks": self._catalog.described(), "reward_today": reward_today}

    async def enter(
        self, user_id: str, brought: BroughtKeys, device_timezone: str | None = None
    ) -> "BarCall":
        """A visit begun for the user, bringing `brought`, their device in `device_timezone`,
        doing away with any of theirs under way: its first call's events, from the visit's
        id and who she is on. Raises BarClosed while the bar is off; OverLimit, once who she
        is is drawn, if the user has no visits left this hour."""
        if not self._is_on():
            raise BarClosed()
        now = self._clock()
        today = day_of(now)
        before = await self._db.read(_before, user_id, today)
        everyone = list(self._characters.values())
        if before.done_today:
            character = everyone[self._random(len(everyone))]
        else:
            character = everyone[_of_the_day(user_id, today, len(everyone))]
        admissions = self._admissions
        admission = await admissions.admitted(
            admissions.visit(user_id, character.id, brought), lambda let_in: let_in.settle("left")
        )
        try:
            visit = await self._drawn(user_id, character, now, before, device_timezone, admission)
        except Exception:
            await asyncio.shield(self._settling(admission, "failed", given_back=True))
            raise
        except BaseException:  # the page gone as she was being drawn: left
            self._settling(admission, "left")
            raise
        replaced = self._visits.get(user_id)
        self._visits[user_id] = visit
        if replaced is not None:
            await self._cut_short(replaced)
        return self._called(
            visit, opening_ask(visit.orders[0]), VisitBegan(visit.id, character.id)
        )

    async def _drawn(
        self,
        user_id: str,
        character: Character,
        now: datetime,
        before: _Before,
        device_timezone: str | None,
        admission: Admission[TurnKeys],
    ) -> _Visit:
        """The user's visit by `character`, coming in `now`, let in as `admission`: all the
        rest of it drawn."""
        today = day_of(now)
        now_known = await self._her_now.read(user_id, character.id, device_timezone, "visit")
        hers = await self._db.read(_hers, user_id, character.id)
        reason = self._reason(character, now_known.done_today, hers.reasons)
        topic = self._topic(character, hers.topics)
        with admission.recording.current():
            facts = await self._facts.about(character, topic) if self._facts is not None else []
        drinks = cups(self._random)
        known = Known(
            before.visits_done < NOVICE_VISITS,
            frozenset(h.wanted for h in hers.remembered.last_orders),
        )
        first = draw_order(character, self._catalog, self._random, [], known)
        world = self._world
        return _Visit(
            secrets.token_urlsafe(16), user_id, character, now, today, reason, topic, drinks,
            known,
            shared_prompt(character, world.prompt(character.name, today) if world else None),
            visit_prompt(
                hers.about_producer, reason, topic, drinks,
                _now_lines(self._her_now, now_known, now),
                hers.remembered, now, character, self._catalog, facts,
            ),
            admission,
            [first],
        )

    async def serve(self, user_id: str, visit_id: str, served: Mixture | str) -> "BarCall":
        """Serve her what the bar counter holds, or a bottled drink by its identifier, in the
        user's visit `visit_id`: the events of the call after it, on the keys the visit came in
        with, from the producer saying one of the fixed lines on. Raises VisitGone unless it is
        the user's visit under way; NotWaiting unless she waits for a drink; BrokenDrink,
        changing nothing, if what is served is none of the drinks."""
        visit = await self._under_way(user_id, visit_id)
        if visit.step != "waiting":
            raise NotWaiting()
        glass = self._catalog.match(served)
        if glass is None:
            raise BrokenDrink()
        serving = judged(visit.orders[-1], glass, visit.character)
        visit.touched = self._clock()
        visit.servings.append(serving)
        visit.drunk = drunk(visit.character, visit.servings)
        visit.step = "writing"
        enjoy = self._lines.enjoy[self._random(len(self._lines.enjoy))]
        if len(visit.servings) < visit.cups and not visit.drunk:
            ordered = [o.target.id for o in visit.orders]
            order = draw_order(visit.character, self._catalog, self._random, ordered, visit.known)
            visit.orders.append(order)
            ask = serving_ask(serving, enjoy, order)
        else:
            ask = farewell_ask(serving, enjoy, visit.servings, drunk=visit.drunk)
        return self._called(visit, ask, BarLine("producer", enjoy))

    async def retry(self, user_id: str, visit_id: str) -> "BarCall":
        """The call the user's visit `visit_id` stopped before, failing, tried again, on the
        same order: its events. Raises VisitGone unless it is the user's visit under way;
        NotFailed unless it stopped so."""
        visit = await self._under_way(user_id, visit_id)
        if visit.step != "failed":
            raise NotFailed()
        visit.touched = self._clock()
        visit.step = "writing"
        return self._called(visit, visit.asking, None)

    async def leave(self, user_id: str, visit_id: str) -> None:
        """The user leaves their visit `visit_id`, which is over. Raises VisitGone unless it is
        theirs under way."""
        visit = await self._under_way(user_id, visit_id)
        await self._cut_short(visit)

    async def sweep(self) -> None:
        """Every visit untouched for `IDLE` done away with."""
        for visit in list(self._visits.values()):
            if self._idle(visit):
                await self._cut_short(visit)

    async def keep_sweeping(self) -> None:
        """`sweep` at every `SWEEP`, until cancelled."""
        while True:
            await asyncio.sleep(SWEEP.total_seconds())
            try:
                await self.sweep()
            except Exception:
                log.exception("sweeping visits away failed")

    async def aclose(self) -> None:
        """Every visit still under way ended, and each visit over settled."""
        for visit in list(self._visits.values()):
            self._end(visit)
            result = _ending(visit)
            self._settling(visit.admission, result, given_back=_given_back(visit, result))
        while self._settles:
            await asyncio.gather(*self._settles, return_exceptions=True)

    @property
    def _rewarding(self) -> bool:
        """Whether visits done are rewarded now: affinity and gifts are on. Told on the event
        loop, as affinity is."""
        return self._affinities is not None and self._gifts is not None and self._affinities.on

    async def _under_way(self, user_id: str, visit_id: str) -> _Visit:
        """The user's visit `visit_id` under way. Raises VisitGone unless there is one; if it
        was untouched for `IDLE`, it is done away with first."""
        visit = self._visits.get(user_id)
        if visit is None or visit.id != visit_id:
            raise VisitGone()
        if self._idle(visit):
            await self._cut_short(visit)
            raise VisitGone()
        return visit

    def _idle(self, visit: _Visit) -> bool:
        """Whether the visit was untouched for `IDLE`."""
        return self._clock() - visit.touched >= IDLE

    def _end(self, visit: _Visit) -> bool:
        """The visit is no longer under way: whether it was until now."""
        if self._visits.get(visit.user_id) is not visit:
            return False
        del self._visits[visit.user_id]
        return True

    async def _over(self, visit: _Visit, result: Result) -> None:
        """The visit is over as `result`: no longer under way, and settled (`_settling`), only
        the first time; settled all the same should the wait be cancelled."""
        self._end(visit)
        await asyncio.shield(
            self._settling(visit.admission, result, given_back=_given_back(visit, result))
        )

    async def _cut_short(self, visit: _Visit) -> None:
        """The visit is over short of done (`_ending`)."""
        await self._over(visit, _ending(visit))

    def _left_off(self, visit: _Visit, call: int) -> None:
        """The visit is left if its call `call` stops while her lines are still being written,
        the page gone, and it is still under way: settled where that cannot be waited for. A
        call stopping once another is made, as it closes, leaves it be."""
        if visit.calls == call and visit.step == "writing" and self._end(visit):
            self._settling(visit.admission, "left", given_back=_given_back(visit, "left"))

    def _settling(
        self, admission: Admission[TurnKeys], result: Result, *, given_back: bool = False
    ) -> "asyncio.Future[None]":
        """`admission` settled as `result` (`Admission.settle`), whether anyone waits for it
        or not: before the bar is closed."""
        return self._kept(admission.settle(result, given_back=given_back))

    def _kept(self, work: Coroutine[Any, Any, T]) -> "asyncio.Future[T]":
        """`work` on a visit over, settling or writing it down, run whether anyone waits for
        it or not: before the bar is closed."""
        kept = asyncio.ensure_future(work)
        self._settles.add(kept)
        kept.add_done_callback(self._settled)
        return kept

    def _settled(self, kept: "asyncio.Future[Any]") -> None:
        self._settles.discard(kept)
        if not kept.cancelled() and (error := kept.exception()) is not None:
            log.error("settling or writing down a visit failed", exc_info=error)

    def _called(self, visit: _Visit, ask: str, first: BarEvent | None) -> "BarCall":
        visit.asking = ask
        visit.calls += 1
        call = visit.calls
        return BarCall(self._call(visit, ask, first, call), lambda: self._left_off(visit, call))

    def _reason(self, character: Character, job: Job | None, recent: frozenset[str]) -> Reason:
        """Her reason for coming: half the time `job`, if any; else one of the list's for her,
        none of the `recent` unless that leaves none."""
        if job is not None and self._random(2) == 0:
            return Reason(job.name, job.note, None, job=True)
        listed = self._fresh(
            [r for r in self._listed.reasons if character.id not in r.not_for], recent
        )
        return Reason(listed.id, listed.note, listed.mood)

    def _topic(self, character: Character, recent: frozenset[str]) -> Topic:
        return self._fresh(
            [t for t in self._listed.topics if character.id not in t.not_for], recent
        )

    def _fresh(self, entries: Sequence[_Listed], recent: frozenset[str]) -> _Listed:
        """One of `entries`, none of the `recent` unless that leaves none."""
        fresh = [e for e in entries if e.id not in recent] or entries
        return fresh[self._random(len(fresh))]

    async def _call(
        self, visit: _Visit, ask: str, first: BarEvent | None, call: int
    ) -> AsyncGenerator[BarEvent, None]:
        """A call of `visit`, its `call`th, asking for `ask`, sending `first` before it if any: its lines as
        they close, held back from the line she orders in on, if she is to order; then the
        memo and that she waits, or that the visit is done. Failing, it is made again once
        (`ATTEMPTS`), after telling the browser to clear what it sent; failing again, the
        visit stops before it, but for her farewell, said in fixed lines instead (the browser
        told to clear what it sent first) and done all the same. A visit left or done
        away with meanwhile is written no further, and the call ends there; one whose page is
        gone part-way is left. On the visit's keys, its service calls recorded under its
        record."""
        if first is not None:
            yield first
        ordering = len(visit.orders) > len(visit.servings)
        said: list[BarLine] = []
        failure = FAILED
        try:
            for attempt in range(ATTEMPTS):
                if attempt:
                    yield Retrying()
                said = []
                try:
                    async with aclosing(self._attempt(visit, ask, ordering, said)) as lines:
                        async for line in lines:
                            yield line
                    break
                except OwnKeyFailed as e:  # theirs to fix, so they are told what went wrong
                    log.warning("a visit's call failed on the user's own key: %s", e.service)
                    failure = e.message
                except Exception:
                    log.exception("a visit's call failed")
                    failure = FAILED
                if self._visits.get(visit.user_id) is not visit:
                    return
            else:
                if ordering:
                    visit.step = "failed"
                    visit.touched = self._clock()
                    yield VisitFailed(failure)
                    return
                if said:
                    yield Retrying()
                said = fixed_farewell(visit.servings[-1], visit.drunk, self._lines, self._random)
                for line in said:
                    yield line
            if self._visits.get(visit.user_id) is not visit:
                return  # left, or done away with by another: written no further
            visit.written.append((ask, said))
            if ordering:
                visit.step = "waiting"
                visit.touched = self._clock()
                yield Memo(visit.orders[-1].memo("".join(line.zh for line in said if line.order)))
                yield Waiting()
                return
            self._end(visit)  # done: too late to leave it now
            try:
                rewarded = await asyncio.shield(self._kept(self._done(visit)))
            except Exception:
                yield VisitFailed(FAILED)
                return
            yield VisitDone(rewarded)
        finally:
            self._left_off(visit, call)

    async def _done(self, visit: _Visit) -> Rewarded | None:
        """The visit done: written down, rewarded if it is to be (`_write_down`), and settled
        as such; failed, if it cannot be written down."""
        try:
            rewarded = await self._db.write(
                self._write_down, visit, self._clock(), self._rewarding
            )
        except BaseException:
            await self._over(visit, "failed")
            raise
        await self._over(visit, "success")
        return rewarded

    async def _attempt(
        self, visit: _Visit, ask: str, ordering: bool, said: list[BarLine]
    ) -> AsyncGenerator[BarLine, None]:
        """One try at a call of `visit` asking for `ask`, she ordering in it if `ordering`:
        each line as it is to be sent, `said` keeping all of them. Ends early, short, if the
        visit is no longer under way; raises if it fails or writes no line it needs."""
        chat = visit.admission.llms.chat
        with visit.admission.recording.current():
            held: list[BarLine] = []
            parser = BarParser()
            stream = chat.stream(prompt(visit.shared, visit.about, visit.written, ask))
            try:
                async for chunk in stream:
                    if not isinstance(chunk, str):
                        continue
                    if self._visits.get(visit.user_id) is not visit:
                        return
                    for line in parser.feed(chunk):
                        for shown in _holding(line, held, ordering):
                            said.append(shown)
                            yield shown
                for line in parser.finish():
                    for shown in _holding(line, held, ordering):
                        said.append(shown)
                        yield shown
            finally:
                if (close := getattr(stream, "aclose", None)) is not None:
                    await close()
            if ordering:
                if not held:
                    raise _Unwritten("she did not order")
                if not any(line.order for line in held):
                    held[0] = replace(held[0], order=True)
                held = await self._named(visit, chat, ask, said, held)
                if self._visits.get(visit.user_id) is not visit:
                    return
                for line in held:
                    said.append(line)
                    yield line
        if not said:
            raise _Unwritten("nothing was written")

    async def _named(
        self, visit: _Visit, chat: ChatLLM, ask: str, said: list[BarLine], held: list[BarLine]
    ) -> list[BarLine]:
        """`held`, her order and what follows it in a call asking for `ask`, after `said`, with
        her order naming drinks as it should: as written, rewritten in another call, or else
        said in a fixed line, the visit's last order then changed to how that line says it (an
        analogy to conditions)."""
        order = visit.orders[-1]
        rest = [line for line in held if not line.order]
        if names_rightly(order, [line for line in held if line.order], self._catalog):
            return held
        rewritten = await self._rewritten(visit, chat, rewrite_ask(ask, order, said))
        if rewritten and names_rightly(order, rewritten, self._catalog):
            return [*rewritten, *rest]
        visit.orders[-1], fixed = fixed_order(order, self._lines, self._random)
        return [*fixed, *rest]

    async def _rewritten(self, visit: _Visit, chat: ChatLLM, ask: str) -> list[BarLine]:
        """Her order as a call asking for `ask` writes it: her lines marked as her order, or
        else her last; none if it writes none of hers, or fails."""
        parser = BarParser()
        lines: list[BarLine] = []
        stream = chat.stream(prompt(visit.shared, visit.about, visit.written, ask))
        try:
            async for chunk in stream:
                if isinstance(chunk, str):
                    lines += parser.feed(chunk)
            lines += parser.finish()
        except Exception:
            log.exception("rewriting an order failed")
            return []
        finally:
            if (close := getattr(stream, "aclose", None)) is not None:
                await close()
        hers = [line for line in lines if line.speaker == "her"]
        return [line for line in hers if line.order] or [replace(h, order=True) for h in hers[-1:]]

    def _write_down(
        self, db: sqlite3.Connection, visit: _Visit, now: datetime, rewarding: bool
    ) -> Rewarded | None:
        """Write the visit down, done `now`, rewarding it if `rewarding`: the draw chance only
        on the user's first done of the day it came in on, her affinity on every visit; what it
        was rewarded with; None if nothing."""
        rewarded = None
        if rewarding:
            assert self._gifts is not None and self._affinities is not None
            her = visit.character
            first_today = not _done_on(db, visit.user_id, visit.entered_on)
            draws = (
                int(self._gifts.reward_draw(db, visit.user_id, f"bar:{visit.entered_on}"))
                if first_today
                else 0
            )
            affinity_up = self._affinities.visit_done(
                db, visit.user_id, her.id,
                [
                    DrinkServed(s.tier, has_best(s.order, her, self._catalog))
                    for s in visit.servings
                ],
            )
            if draws or affinity_up:
                rewarded = Rewarded(draws, affinity_up)
        orders = [
            {
                "target": s.order.target.id, "phrasing": s.order.phrasing,
                "served": s.served.drink.id, "big": s.served.big, "tier": s.tier,
            }
            for s in visit.servings
        ]
        db.execute(
            "INSERT INTO visit_records (user_id, character_id, entered_at, left_at, entered_on,"
            " reason, topic, orders, drunk, rewarded) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                visit.user_id, visit.character.id, visit.entered_at.isoformat(), now.isoformat(),
                visit.entered_on.isoformat(), visit.reason.id, visit.topic.id,
                json.dumps(orders), int(visit.drunk), int(rewarded is not None),
            ),
        )
        return rewarded


class _Unwritten(RuntimeError):
    """The model wrote no line a call needs."""


def _ending(visit: _Visit) -> Result:
    """How the visit turns out, ended now short of done: failed, if it stopped before a call
    that failed; else left."""
    return "failed" if visit.step == "failed" else "left"


def _given_back(visit: _Visit, result: Result) -> bool:
    """Whether the visit, over as `result`, is given back to the user's limit: failed with
    nothing yet written."""
    return result == "failed" and not visit.written


def _holding(line: BarLine, held: list[BarLine], ordering: bool) -> list[BarLine]:
    """The lines to send now that `line` has closed, `held` keeping those not to be sent yet:
    in a call she orders in, her latest line and what follows it, which may be her order,
    and anything from a line marked as her order on."""
    if not ordering:
        return [line]
    if any(h.order for h in held):
        held.append(line)
        return []
    if line.speaker == "her":
        sent = list(held)
        held[:] = [line]
        return sent
    if held:
        held.append(line)
        return []
    return [line]


def _of_the_day(user_id: str, today: date, characters: int) -> int:
    """Which character is the user's of the day `today`."""
    digest = hashlib.sha256(f"{user_id}/{today.isoformat()}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % characters


def _open(db: sqlite3.Connection) -> None:
    db.executescript(_SCHEMA)


def _done_on(db: sqlite3.Connection, user_id: str, day: date) -> bool:
    """Whether the user has a visit done that came in on `day`."""
    found = db.execute(
        "SELECT 1 FROM visit_records WHERE user_id = ? AND entered_on = ? LIMIT 1",
        (user_id, day.isoformat()),
    ).fetchone()
    return found is not None


def _before(db: sqlite3.Connection, user_id: str, today: date) -> _Before:
    (done,) = db.execute(
        "SELECT COUNT(*) FROM visit_records WHERE user_id = ?", (user_id,)
    ).fetchone()
    return _Before(_done_on(db, user_id, today), done)


def _now_lines(her_now: HerNow, known: KnownNow, now: datetime) -> list[str]:
    """What she is told of now coming in at `now`, as `known`: how she feels toward the
    producer, then the day in Tokyo. A visit tells her neither the time nor anything of the
    producer's (`her_now.CARRIES`), so no time zone, profile or last contact is needed."""
    return her_now.lines(
        known, "visit", now, "Asia/Tokyo", ProducerProfile(), None, tier_prompt(known.affinity)
    )


def _hers(db: sqlite3.Connection, user_id: str, character_id: str) -> _Hers:
    (count,) = db.execute(
        "SELECT COUNT(*) FROM visit_records WHERE user_id = ? AND character_id = ?",
        (user_id, character_id),
    ).fetchone()
    rows = db.execute(
        "SELECT left_at, reason, topic, orders, drunk FROM visit_records"
        " WHERE user_id = ? AND character_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, character_id, RECENT_VISITS),
    ).fetchall()
    remembered = Remembered(count)
    if rows:
        left_at, _, _, orders, drunk = rows[0]
        remembered = Remembered(
            count, datetime.fromisoformat(left_at),
            tuple(Had(**o) for o in json.loads(orders)), bool(drunk),
        )
    return _Hers(
        remembered, frozenset(r[1] for r in rows), frozenset(r[2] for r in rows),
        producer_prompt(read_profile(db, user_id)),
    )
