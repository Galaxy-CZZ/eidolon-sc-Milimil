"""What happens between the user and the characters, as it happens (GLOSSARY.md「成就」):
a turn recorded, typed or in a call alike, and a gift given, each with the tier it leaves her
affinity in; a call that connected ended; and drawing. Each is kept here once, a gift given,
a call kept and drawing here altogether, and whatever it counts towards is kept and rewarded
with it: the achievements (`achievements`).

Each achievement's stage unlocked, and each character complete, gives its rewards through
the gifts (`Gifts.reward`), once, in the same transaction as what unlocked it is kept, so
that two unlocking it at once are rewarded once.

The achievements were worked out once as they launched, from what was recorded before
(`achievements.launch`): rewarded open or not, logged, with no activity record.

Only what is told here counts: a turn refused or failed is never recorded, so never told; a
data package's turns and gifts are put in the database, not told; deleting a past
conversation takes nothing back. Nothing is kept while affinity and gifts are closed
(`LiveConfig.affinity_on`); what was kept before stays. What happened is kept in the same
transaction as the turn, the gift, the call or the draw it was told of: keeping it failing,
none of them is kept either (ADR-0028).

Each stage unlocked and each character complete, once its reward is given, has an activity
record for the dashboard to count (`ActivityLog.achievement_unlocked`,
`ActivityLog.character_complete`): written apart, once what it records is kept, writing them
failing is only logged.

Each stage unlocked and each character complete is told to the letters in the same transaction
(`Letters.reached`): which of them is an occasion for a letter is theirs to tell. Whether
letters are on is told with whether affinity and gifts are, on the event loop, before the
write task is handed in (`open`): a transaction body reads none of the event loop's state
(ADR-0028).

Each user's progress with the achievements is theirs, deleted with them
(`database.USER_DATA`), and goes in no data package. The retired daily tasks' table of
progress is dropped as the backend starts (`_open`)."""

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from eidolon import achievements
from eidolon.achievements import Completed, Hers, Progress, Tally, Unlocked
from eidolon.activity import ActivityLog
from eidolon.affinity import Tier, day_of
from eidolon.data_access import Database
from eidolon.gifts import Drawn, Given, Gifts, Reward
from eidolon.store import keep_call

if TYPE_CHECKING:
    from eidolon.letters import Letters

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Open:
    """What is open now, told on the event loop before handing in the write task what
    happens is kept in, and kept to as told (ADR-0028): affinity and gifts, for what happens
    to be kept towards them; letters, for what it unlocks to be told to them."""

    affinity: bool
    letters: bool


@dataclass(frozen=True)
class Rewarded:
    """What something the user did was rewarded with: draw chances, reset cards, the
    achievements' stages it unlocked and the characters it completed; and when, by the time
    the rewards are kept by, for the browser to tell what it has seen."""

    draws: int
    reset_cards: int
    rewarded_at: datetime
    achievements: list[Unlocked] = field(default_factory=list)
    completed: list[Completed] = field(default_factory=list)

    def shown(self) -> dict:
        """As the browser is told it."""
        return {
            "draws": self.draws,
            "reset_cards": self.reset_cards,
            "achievements": [u.shown() for u in self.achievements],
            "completed": [c.shown() for c in self.completed],
            "rewarded_at": self.rewarded_at.isoformat(),
        }


class Happenings:
    """What happens between users and characters, kept in the database next to the gifts
    they are rewarded with. What a turn, a gift, a call or a draw counts towards is kept and
    rewarded in the transaction the turn, the gift, the call or the draw is kept in, with it
    or not at all: a turn's is a body of the write task the turn is recorded in
    (`turn_recorded`); giving a gift, keeping a call and drawing are each such a task here
    (`give`, `call_ended`, `draw`)."""

    def __init__(
        self,
        db: Database,
        is_open: Callable[[], bool],
        gifts: Gifts,
        activity: ActivityLog,
        letters: "Letters | None" = None,
    ) -> None:
        """`is_open` tells whether affinity and gifts are open now; `letters` is told of each
        stage unlocked and each character complete, while they are on."""
        self._db = db
        self._is_open = is_open
        self._gifts = gifts
        self._activity = activity
        self._letters = letters
        db.prepare(_open)
        self._launch()

    @property
    def open(self) -> Open:
        """What is open now: told on the event loop, before handing in the write task what
        happens is kept in (`turn_recorded`)."""
        return Open(self._is_open(), self._letters is not None and self._letters.on)

    def _launch(self) -> None:
        """Reward everyone, once ever, for how far they had come before the achievements
        launched, open or not: no activity record, as it did not happen now."""
        what: dict[tuple[str, str], Unlocked | Completed] = {}
        """Each stage unlocked or character completed, by the user and key it is rewarded
        by."""
        launched = False

        def due(db: sqlite3.Connection, now: datetime) -> list[tuple[str, Reward]]:
            nonlocal launched
            unlocked = achievements.launch(db, now)
            launched = unlocked is not None
            what.update({(u, r.key): w for u, (r, w) in unlocked or []})
            return [(u, r) for u, (r, _) in unlocked or []]

        given = self._db.prepare(self._gifts.reward_everyone, due)
        if launched:
            log.info(
                "achievements launched: %d users, %d stages, %d draw chances, %d reset cards",
                len({u for u, _ in given}),
                sum(isinstance(what[u, r.key], Unlocked) for u, r in given),
                sum(r.draws for _, r in given),
                sum(r.reset_cards for _, r in given),
            )

    def turn_recorded(
        self,
        db: sqlite3.Connection,
        user_id: str,
        character_id: str,
        tier: Tier | None,
        open: Open,
    ) -> Rewarded | None:
        """A turn of the user's with the character is recorded, now, leaving her affinity in
        `tier` (None if not known), through `db`, in the transaction it is recorded in, with
        what is `open` as it was told as it was handed in: what it is rewarded with; None if
        nothing. Its activity records are `write_records`'s."""
        if not open.affinity:
            return None
        return self._happened(db, user_id, character_id, open, turns=1, tier=tier)

    async def give(
        self, user_id: str, gift_id: str, character_id: str, device_timezone: str | None
    ) -> tuple[Given, Rewarded | None]:
        """Give the character one of the gift (`Gifts.give`), the user's device in
        `device_timezone`, and keep it towards the achievements, in one transaction: what
        giving it did, and what it was rewarded with (None if nothing). Raises GiftsClosed
        if gifts are not open, NoSuchCharacter for no such character, NoneLeft if the user
        has none of it."""
        await self._gifts.refuse_unless_open()
        self._gifts.refuse_unknown(gift_id, character_id)
        warmed = await self._gifts.warms(user_id, gift_id, character_id, device_timezone)
        given, rewarded = await self._db.write(
            self._give, user_id, gift_id, character_id, warmed, self.open
        )
        await self.write_records(user_id, rewarded)
        return given, rewarded

    async def call_ended(
        self,
        conversation_id: str,
        user_id: str,
        character_id: str,
        connected_at: datetime,
        seconds: float,
    ) -> Rewarded | None:
        """A call of the user's with the character in the conversation, that connected at
        `connected_at`, ended, now, having lasted `seconds` once it had: kept for stats
        (`store.keep_call`) and towards the achievements, in one transaction; what it was
        rewarded with, None if nothing, or if the conversation is gone meanwhile."""
        rewarded = await self._db.write(
            self._call_ended,
            conversation_id, user_id, character_id, connected_at, seconds, self.open,
        )
        await self.write_records(user_id, rewarded)
        return rewarded

    async def draw(self, user_id: str, *, all: bool = False) -> tuple[Drawn, Rewarded | None]:
        """Draw once, or every chance if `all` (`Gifts.draw`), and keep it towards the
        achievements, in one transaction: what drawing gave, and what it was rewarded with
        (None if nothing). Raises GiftsClosed if gifts are not open, NoDraws if there are no
        chances to draw."""
        await self._gifts.refuse_unless_open()
        drawn, rewarded = await self._db.write(self._draw, user_id, all, self.open)
        await self.write_records(user_id, rewarded)
        return drawn, rewarded

    async def write_records(self, user_id: str, rewarded: Rewarded | None) -> None:
        """Write the activity records of what the user was `rewarded` for, once it is kept:
        each stage unlocked and each character complete, each a write task of its own, apart
        from what it records; failing, only logged. Only what happens is recorded: those the
        launch works out from before it are rewarded without coming here."""
        if rewarded is None:
            return
        at = rewarded.rewarded_at
        for stage in rewarded.achievements:
            await self._activity.achievement_unlocked(
                user_id, stage.character_id, stage.achievement, stage.stage, at
            )
        for complete in rewarded.completed:
            await self._activity.character_complete(user_id, complete.character_id, at)

    async def hers(self, user_id: str, character_id: str) -> Hers | None:
        """How far the user has come with the character's own achievements; None while
        closed."""
        if not self._is_open():
            return None
        return await self._db.read(achievements.hers, user_id, character_id)

    async def of_all(self, user_id: str) -> list[Progress] | None:
        """How far the user has come with the achievements of all the characters together;
        None while closed."""
        if not self._is_open():
            return None
        return await self._db.read(achievements.of_all, user_id)

    async def tally(self, user_id: str) -> Tally | None:
        """How many stages the user has unlocked and how many characters are complete;
        None while closed."""
        if not self._is_open():
            return None
        return await self._db.read(achievements.tally, user_id)

    def _give(
        self, db: sqlite3.Connection, user_id: str, gift_id: str, character_id: str,
        warmed: bool, open: Open,
    ) -> tuple[Given, Rewarded | None]:
        given = self._gifts.give(db, user_id, gift_id, character_id, warmed)
        return given, self._happened(
            db, user_id, character_id, open, gifts=1, tier=given.affinity.tier
        )

    def _call_ended(
        self,
        db: sqlite3.Connection,
        conversation_id: str,
        user_id: str,
        character_id: str,
        connected_at: datetime,
        seconds: float,
        open: Open,
    ) -> Rewarded | None:
        if not keep_call(db, conversation_id, connected_at, seconds) or not open.affinity:
            return None
        return self._happened(db, user_id, character_id, open, call_time=seconds)

    def _draw(
        self, db: sqlite3.Connection, user_id: str, all: bool, open: Open
    ) -> tuple[Drawn, Rewarded | None]:
        drawn = self._gifts.draw(db, user_id, all=all)
        return drawn, self._happened(db, user_id, None, open, draws=len(drawn.drawn))

    def _happened(
        self,
        db: sqlite3.Connection,
        user_id: str,
        character_id: str | None,
        open: Open,
        *,
        turns: int = 0,
        gifts: int = 0,
        call_time: float = 0,
        draws: int = 0,
        tier: Tier | None = None,
    ) -> Rewarded | None:
        """Keep the `turns` and `gifts` with the character (None for none), the time talked in
        a call, the times drawn and the tier her affinity was left in towards the
        achievements, and give the rewards for the stages it unlocked, through `db`, in the
        transaction what happened is kept in, affinity and gifts open, telling the letters of
        what it unlocked if they are `open`: what it was rewarded with; None if nothing."""
        done: dict[str, Unlocked | Completed] = {}
        """Each stage unlocked or character completed, by the key it is rewarded by."""

        def due(db: sqlite3.Connection, now: datetime) -> list[Reward]:
            unlocked = achievements.keep(
                db, user_id, character_id, now, day_of(now),
                turns=turns, gifts=gifts, call_time=call_time, draws=draws, tier=tier,
            )
            done.update({reward.key: what for reward, what in unlocked})
            return [reward for reward, _ in unlocked]

        given, at = self._gifts.reward(db, user_id, due)
        if not given:
            return None
        what = [done[r.key] for r in given]
        if self._letters is not None and open.letters:
            self._letters.reached(db, user_id, what, at)
        return Rewarded(
            sum(r.draws for r in given), sum(r.reset_cards for r in given), at,
            [w for w in what if isinstance(w, Unlocked)],
            [w for w in what if isinstance(w, Completed)],
        )


def _open(db: sqlite3.Connection) -> None:
    db.executescript(achievements.SCHEMA)
    db.execute("DROP TABLE IF EXISTS daily_task_progress")
