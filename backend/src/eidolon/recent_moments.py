"""Her latest moments as she knows of them talking with the producer (GLOSSARY.md「朋友圈」
「动态」「此刻」): typing, in a call, and reaching out, but not visiting the bar, nor posting a
moment, which has its own latest (`moments.RECENT`).

Of hers that have shown within `WITHIN`, the latest `AT_MOST`, each told in a line: when, the
producer's time as the rest of now is; her Japanese, not its subtitle; what its picture is, by
its note, if it has one he sees; whether he likes it, his comment, and her reply to it once it
has shown. Not what her circle made of it. After them, how she may bring them up: never
complaining of, nor pressing him about, one he neither liked nor commented on; only close or
intimate, looking forward a little to his seeing it, once at most. None at all while the
deployer has moments off, or the user their own switch (`read_switched_on`); nor a section
without any.

The tables read are those `moments` keeps; read here, below it, for what she knows of now
(`her_now`) to read, which `moments` itself reads."""

import json
import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from eidolon.affinity import Tier
from eidolon.clock import Clock
from eidolon.data_access import Database

WITHIN = timedelta(days=3)
"""How far back she knows of her moments as she talks with the producer."""

AT_MOST = 3
"""How many of her latest she knows of, at most."""

HEADING = "# 你最近发的朋友圈"
"""What the section telling her of them opens with."""

BRING_UP = "这些是你这几天自己发的动态，可以自己提起。他没赞也没评论的，不抱怨，也不追问。"
"""How she may bring them up, in any tier."""

LOOKING_FORWARD = "他没赞也没评论的，可以带一点期待，最多提一次。"
"""How she may besides, close or intimate."""

NOTHING_YET = "他还没赞也没评论"
"""Told of one he neither likes nor commented on."""

_DAYS_AGO = {0: "今天", 1: "昨天", 2: "前天"}


@dataclass(frozen=True)
class RecentMoment:
    """One of her moments as she knows of it: when it showed, her Japanese, its picture's
    note (None without a picture he sees, or a note), whether he likes it, his comment (None
    for none) and her reply to it (None till it shows)."""

    posted_at: datetime
    ja: str
    note: str | None
    liked: bool
    comment: str | None
    reply: str | None


class RecentMoments:
    """Her latest moments, in `db`, at the time `clock` says, while `is_on` says the deployer
    has moments on."""

    def __init__(self, db: Database, clock: Clock, is_on: Callable[[], bool]) -> None:
        self._db = db
        self._clock = clock
        self._is_on = is_on

    async def hers(self, user_id: str, character_id: str) -> tuple[RecentMoment, ...]:
        """The latest of the character's moments for the user she knows of, the earliest
        first; none while the deployer or the user has moments off."""
        if not self._is_on():
            return ()
        now = self._clock()
        return await self._db.read(
            _hers, user_id, character_id, (now - WITHIN).astimezone(UTC).isoformat(),
            now.astimezone(UTC).isoformat(),
        )


def read_switched_on(db: sqlite3.Connection, user_id: str) -> bool:
    """Whether the user has their own switch for moments on, as it is by default."""
    row = db.execute("SELECT 1 FROM moments_off WHERE user_id = ?", (user_id,)).fetchone()
    return row is None


def moments_section(
    moments: Sequence[RecentMoment], now: datetime, timezone: str, tier: Tier | None
) -> str | None:
    """The section telling her of `moments` at `now`, the producer in `timezone`, she in
    `tier` (None where affinity is off, as trust); None without any."""
    if not moments:
        return None
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).date()
    rules = BRING_UP + (LOOKING_FORWARD if tier in ("close", "intimate") else "")
    return "\n".join([HEADING, *(_line(m, zone, today) for m in moments), rules])


def _line(moment: RecentMoment, zone: ZoneInfo, today: date) -> str:
    at = moment.posted_at.astimezone(zone)
    day = _DAYS_AGO.get((today - at.date()).days) or f"{at.month}月{at.day}日"
    picture = f"（配图：{_one_line(moment.note)}）" if moment.note else ""
    return f"{day} {at:%H:%M}　{_one_line(moment.ja)}{picture}　{_made_of(moment)}"


def _made_of(moment: RecentMoment) -> str:
    """What the producer made of `moment`, and she of his comment."""
    if moment.comment is None:
        return "制作人赞了，没评论" if moment.liked else NOTHING_YET
    commented = f"评论「{_one_line(moment.comment)}」"
    replied = f"，你回了「{_one_line(moment.reply)}」" if moment.reply is not None else ""
    if moment.liked:
        return f"制作人赞了；他{commented}{replied}"
    return f"制作人没赞，{commented}{replied}"


def _one_line(text: str) -> str:
    """`text` on one line: its line breaks, and the spaces around them, one space."""
    return re.sub(r"\s*\n\s*", " ", text.strip())


def _hers(
    db: sqlite3.Connection, user_id: str, character_id: str, since: str, now: str
) -> tuple[RecentMoment, ...]:
    if not read_switched_on(db, user_id):
        return ()
    rows = db.execute(
        "SELECT m.posted_at, m.ja, m.image,"
        " EXISTS (SELECT 1 FROM moment_images i WHERE i.moment_id = m.id),"
        " EXISTS (SELECT 1 FROM moment_likes l WHERE l.moment_id = m.id),"
        " c.text, c.reply_at, c.reply_ja"
        " FROM moments m LEFT JOIN moment_comments c ON c.moment_id = m.id"
        " WHERE m.user_id = ? AND m.character_id = ? AND m.posted_at > ? AND m.posted_at <= ?"
        " ORDER BY m.posted_at DESC, m.id DESC LIMIT ?",
        (user_id, character_id, since, now, AT_MOST),
    ).fetchall()
    return tuple(
        RecentMoment(
            datetime.fromisoformat(posted_at), ja, picture_note(image) if pictured else None,
            bool(liked), text,
            reply_ja if reply_ja is not None and reply_at is not None and reply_at <= now
            else None,
        )
        for posted_at, ja, image, pictured, liked, text, reply_at, reply_ja in reversed(rows)
    )


def picture_note(image: str | None) -> str | None:
    """The note of a moment's picture as she wrote it, kept as JSON; None for none."""
    note = json.loads(image).get("note") if image is not None else None
    return note if isinstance(note, str) else None
