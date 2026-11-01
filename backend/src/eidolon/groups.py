"""自主群聊（多智能体）：一个用户可以开很多个群，每个群有自己的名字、成员和历史。

一个群由一条话题开始（某位成员随口抛出），之后每位成员按自己与话题的相关度决定说还是不说：
相关的可以连着说，不相关的沉默，没人接就冷场。随着对话推进，每个人「这跟我没关系、不必回」
的阈值逐步抬高，她「说过的越多、相关度越低」，所以每段对话都会自己收敛、必然结束（`MAX_TURNS`
是兜底）。她「顺带提到没在场的人」的概率也随轮次降低。

群与群之间彼此独立：一个群的历史只有它自己的话题和台词，解散一个群不会影响别的群。

对话在后台一句一句地生成，每句之间隔 `delay`（默认 10 秒到 90 秒），所以用户随时可以插话。

约每 `TOPIC_INTERVAL`（4 小时）由调度器给开着的群抛一个新话题；关掉开关只是停止调度，
已经写下的群聊、话题和消息都留着。解散（`dissolve`）把群标记为已解散：它从列表里消失，
不再有新话题，历史也不再显示（数据留着）。

用户发言与成员地位相同：插进当前对话，同样按相关度被回应，不是「必须每个人回复」的焦点。

她说的每句是日语原文 + 中文字幕，和私聊一样；她怎么对用户说话带上好感度的档位。

一段对话结束后，把这段群聊里用户透露的事写进每个参与成员的记忆（`memories` 表，
`conversation_id` 为空），私聊检索记忆时同样能查到。
"""

import asyncio
import json
import logging
import random
import re
import secrets
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from datetime import time as clock_time
from zoneinfo import ZoneInfo

from eidolon.affinity import Affinities, tier_prompt
from eidolon.characters import Character, chinese_names
from eidolon.clock import Clock
from eidolon.data_access import Database
from eidolon.llm import ChatMessage
from eidolon.memory import Memory, Memories, _INSTRUCTIONS
from eidolon.own_keys import DeployerLease

log = logging.getLogger(__name__)

TICK = timedelta(minutes=1)
"""How often the scheduler looks whose group is due a new topic."""

TOPIC_INTERVAL = timedelta(hours=4)
"""How long a group waits between one topic and the next, on average (kept for reference)."""

TOPIC_GAP = (timedelta(hours=2), timedelta(hours=6))
"""Each group picks its next topic's time at random from this, so they do not all speak at once."""

MAX_TURNS = 30
"""The most lines one topic gets before it is closed anyway: the ceiling, not the usual end."""

DEFAULT_MEMBERS = 4
"""How many members a group gets when none are picked."""

DEFAULT_DELAY = (10.0, 300.0)
"""Seconds between one line and the next: slow enough to feel live, and to leave room to cut in.
Each member has her own timer, so several may be waiting to answer at once."""

REPLY_DELAY = (8.0, 60.0)
"""The shorter timer for the members answering the user's own line: a reply to you should feel
like an answer, not like the group drifting on."""

BASE_THRESHOLD = 0.28
"""How relevant a member must be to speak at the topic's first line."""

CONTINUE_THRESHOLD = 0.72
"""How willing a member must be to answer the user's line in a topic already wound down: high,
so a stray remark does not restart a finished conversation."""

MENTION_BONUS = 0.60
"""How much naming (or plainly addressing) a member in the user's line adds to her willingness
to answer it: enough that being asked brings her in even when the line alone would not."""

THRESHOLD_STEP = 0.028
"""How much that bar rises for each line said: the longer it goes, the less anyone has to say."""

SPEAK_DECAY = 0.054
"""How much a member's relevance to the topic drops for each line she has said: having said
her piece, she has less left to add, so the conversation winds down instead of looping."""

BASE_MENTION = 0.45
"""How likely a speaker is to be told it may bring up someone not in the conversation."""

MENTION_STEP = 0.09
"""How much that falls for each line: late in a topic, no one drags in outsiders."""

MAX_LINE_CHARS = 220
"""A line longer than this is cut: the models are told to keep it short."""

MAX_NAME_CHARS = 40
"""A group's name longer than this is cut."""

RECENT_LINES = 8
"""How many of the latest lines a speaker is shown: enough to answer the conversation, short
enough not to drown it."""

PAST_LINES = 14
"""How many of the lines of the same group's earlier topics a speaker is shown: the group's
own history, which she can pick up or refer back to."""

TOPIC_RECALL = 12
"""How many of the group's earlier topics its next one is told about, to stay off them.

Without this the only material a topic had was her character sheet, and the group went round
the same three hooks for days (`.scratch/nsfw/`)."""

MATERIAL_MEMORIES = 6
"""How many of her memories of the producer a speaker is shown as something to talk from."""

HISTORY_TOPICS = 50
"""How many topics the page is given: the whole readable history of the group."""

SHOWN_MEMORIES = 10
"""How many of the user's memories the extractor is shown to avoid writing them again."""

MAX_MEMORY_CHARS = 200
"""A memory longer than this is cut (`memory.MAX_MEMORY_LENGTH`)."""

USER_SPEAKER = "user"
"""The speaker of a line the user said."""

QUIET = (clock_time(1), clock_time(7))
"""The producer's hours of quiet: from the first to the second nobody raises a new topic in
the group on her own (a conversation the user starts still answers)."""

QUIET_ZONE = ZoneInfo("Asia/Shanghai")
"""The producer's own clock, which the quiet hours are read in."""

_JA = re.compile(r"<ja>(.*?)</ja>", re.S)
_ZH = re.compile(r"<zh>(.*?)</zh>", re.S)

_SCHEMA = """
-- One row per group chat: its name, whether it still runs, when it last raised a topic, and
-- when it was dissolved (dissolved groups are hidden, their history kept).
CREATE TABLE IF NOT EXISTS group_chats (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    is_on INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_topic_at TEXT,
    next_topic_at TEXT,
    dissolved_at TEXT,
    seen_at TEXT
);
CREATE INDEX IF NOT EXISTS group_chats_by_user ON group_chats (user_id, created_at);
-- Who is in each group.
CREATE TABLE IF NOT EXISTS group_members (
    group_id TEXT NOT NULL REFERENCES group_chats(id),
    character_id TEXT NOT NULL,
    PRIMARY KEY (group_id, character_id)
);
-- One row per topic raised (a conversation): what was said to raise it, by whom, and when.
CREATE TABLE IF NOT EXISTS group_topics (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES group_chats(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    raised_by TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE INDEX IF NOT EXISTS group_topics_by_group ON group_topics (user_id, created_at);
-- Every line of every topic.
CREATE TABLE IF NOT EXISTS group_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id TEXT NOT NULL REFERENCES group_topics(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    speaker TEXT NOT NULL,
    text TEXT NOT NULL,
    zh TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS group_messages_by_topic ON group_messages (topic_id, id);
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _at_quiet(at: datetime) -> bool:
    """Whether it is the producer's quiet hours now (1:00–7:00, her own clock)."""
    local = at.astimezone(QUIET_ZONE).time()
    return QUIET[0] <= local < QUIET[1]


def _soon_topic_at() -> str:
    """Two to six hours from now, at random: when a group raises its next topic."""
    seconds = random.uniform(2 * 3600, 6 * 3600)
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _open(conn: sqlite3.Connection) -> None:
    """Make the tables, and bring a group chat made before there could be several over: its one
    group becomes a group of its own, named 群聊, with its members and topics."""
    conn.executescript(_SCHEMA)
    if "group_id" not in _columns(conn, "group_members"):
        conn.execute("ALTER TABLE group_members RENAME TO group_members_old")
        conn.execute(
            "CREATE TABLE group_members (group_id TEXT NOT NULL, character_id TEXT NOT NULL,"
            " PRIMARY KEY (group_id, character_id))"
        )
        conn.execute(
            "INSERT INTO group_members (group_id, character_id)"
            " SELECT user_id, character_id FROM group_members_old"
        )
        conn.execute("DROP TABLE group_members_old")
    if "group_id" not in _columns(conn, "group_topics"):
        conn.execute("ALTER TABLE group_topics ADD COLUMN group_id TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE group_topics SET group_id = user_id")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS group_topics_by_group_id"
        " ON group_topics (group_id, created_at)"
    )
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'groups'"
    ).fetchone():
        conn.execute(
            "INSERT OR IGNORE INTO group_chats (id, user_id, name, is_on, created_at, last_topic_at)"
            " SELECT user_id, user_id, '群聊', is_on, created_at, last_topic_at FROM groups"
        )
        conn.execute("DROP TABLE groups")
    if "zh" not in _columns(conn, "group_messages"):
        conn.execute("ALTER TABLE group_messages ADD COLUMN zh TEXT NOT NULL DEFAULT ''")
    if "seen_at" not in _columns(conn, "group_chats"):
        conn.execute("ALTER TABLE group_chats ADD COLUMN seen_at TEXT")
    if "next_topic_at" not in _columns(conn, "group_chats"):
        conn.execute("ALTER TABLE group_chats ADD COLUMN next_topic_at TEXT")
    # A group made before the random gap existed gets its own next time, so a batch of them
    # does not all speak at the same minute.
    rows = conn.execute(
        "SELECT id FROM group_chats WHERE next_topic_at IS NULL AND dissolved_at IS NULL"
    ).fetchall()
    for (group_id,) in rows:
        conn.execute(
            "UPDATE group_chats SET next_topic_at = ? WHERE id = ?",
            (_soon_topic_at(), group_id),
        )


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    intro: str
    sheet: str
    name_zh: str = ""


@dataclass(frozen=True)
class Line:
    speaker: str
    """The character's id, or `USER_SPEAKER`."""
    text: str
    """Her Japanese, or the user's own words."""
    created_at: str
    zh: str = ""
    """Her Chinese subtitle; empty for the user's lines and for hers before subtitles existed."""

    def shown(self, characters: dict[str, Character]) -> dict:
        if self.speaker == USER_SPEAKER:
            name, color = "你", None
        else:
            character = characters.get(self.speaker)
            name = character.name if character else self.speaker
            color = character.color if character else None
        return {"speaker": self.speaker, "name": name, "color": color, "text": self.text,
                "zh": self.zh, "created_at": self.created_at}


@dataclass(frozen=True)
class Said:
    """One line as the model wrote it: her Japanese, its Chinese subtitle."""

    ja: str
    zh: str


class Groups:
    """Every group chat of every user, the scheduler that raises their topics, and each
    conversation it talks through in the background."""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        characters: dict[str, Character],
        lease_of: Callable[[], DeployerLease],
        affinities: Affinities | None = None,
        memories: Memories | None = None,
        *,
        member_count: int = DEFAULT_MEMBERS,
        gap: tuple[timedelta, timedelta] = TOPIC_GAP,
        delay: tuple[float, float] = DEFAULT_DELAY,
    ) -> None:
        self._db = db
        self._clock = clock
        self._characters = characters
        self._lease_of = lease_of
        self._affinities = affinities
        self._memories = memories
        self._member_count = member_count
        self._gap = gap
        self._delay = delay
        self._busy: set[str] = set()
        """Groups whose topic is being talked through right now."""
        self._tasks: dict[str, asyncio.Task[None]] = {}
        """Each group's conversation under way, to cancel as it is dissolved or the backend closes."""
        self._task: asyncio.Task[None] | None = None
        db.prepare(_open)

    async def aclose(self) -> None:
        """Stop the conversations under way."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ---- the groups themselves --------------------------------------------------------

    async def for_user(self, user_id: str) -> list[dict]:
        """The user's groups, newest first, each with a preview of its latest line."""
        return await self._db.read(self._read_list, user_id)

    def _read_list(self, db: sqlite3.Connection, user_id: str) -> list[dict]:
        rows = db.execute(
            "SELECT id, name, is_on, created_at, last_topic_at, seen_at FROM group_chats"
            " WHERE user_id = ? AND dissolved_at IS NULL ORDER BY created_at DESC, rowid DESC",
            (user_id,),
        ).fetchall()
        return [self._listed(db, row) for row in rows]

    def _listed(self, db: sqlite3.Connection, row: Sequence) -> dict:
        group_id = row[0]
        preview = None
        last_message_at = None
        latest = db.execute(
            "SELECT id FROM group_topics WHERE group_id = ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (group_id,),
        ).fetchone()
        if latest is not None:
            line = db.execute(
                "SELECT speaker, text, zh, created_at FROM group_messages WHERE topic_id = ?"
                " ORDER BY id DESC LIMIT 1",
                (latest[0],),
            ).fetchone()
            if line is not None:
                preview = Line(line[0], line[1], line[3], line[2]).shown(self._characters)
                last_message_at = line[3]
        return {
            "id": row[0],
            "name": row[1],
            "on": bool(row[2]),
            "created_at": row[3],
            "last_topic_at": row[4],
            "last_message_at": last_message_at,
            "members": self._member_shown(db, group_id),
            "preview": preview,
            "unseen": self._unseen(db, group_id, row[5]),
        }

    def _unseen(
        self, db: sqlite3.Connection, group_id: str, seen_at: str | None
    ) -> bool:
        """Whether anyone has said anything since the page was last open."""
        since = seen_at or ""
        row = db.execute(
            "SELECT 1 FROM group_messages m JOIN group_topics t ON t.id = m.topic_id"
            " WHERE t.group_id = ? AND m.created_at > ? LIMIT 1",
            (group_id, since),
        ).fetchone()
        return row is not None

    def _member_shown(self, db: sqlite3.Connection, group_id: str) -> list[dict]:
        ids = [
            row[0]
            for row in db.execute(
                "SELECT character_id FROM group_members WHERE group_id = ? ORDER BY rowid",
                (group_id,),
            )
        ]
        return [
            {"id": member, "name": self._characters[member].name}
            for member in ids
            if member in self._characters
        ]

    async def read(self, user_id: str, group_id: str) -> dict | None:
        """One group: the members, the switch, and its whole history, oldest topic first.
        Reading it counts as having seen it, so the list stops dotting it."""
        state = await self._db.read(self._read_group, user_id, group_id)
        if state is not None:
            await self._db.write(self._mark_seen, group_id, self._clock())
        return state

    def _mark_seen(self, db: sqlite3.Connection, group_id: str, now: datetime) -> None:
        db.execute(
            "UPDATE group_chats SET seen_at = ? WHERE id = ?", (now.isoformat(), group_id)
        )

    def _read_group(self, db: sqlite3.Connection, user_id: str, group_id: str) -> dict | None:
        group = db.execute(
            "SELECT id, name, is_on, created_at, last_topic_at FROM group_chats"
            " WHERE id = ? AND user_id = ? AND dissolved_at IS NULL",
            (group_id, user_id),
        ).fetchone()
        if group is None:
            return None
        topics = db.execute(
            "SELECT id, raised_by, text, created_at, closed_at FROM group_topics"
            " WHERE group_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (group_id, HISTORY_TOPICS),
        ).fetchall()
        history = [
            {
                "topic": {
                    "id": row[0], "raised_by": row[1], "text": row[2],
                    "created_at": row[3], "open": row[4] is None,
                },
                "lines": [
                    Line(line[0], line[1], line[2], line[3]).shown(self._characters)
                    for line in db.execute(
                        "SELECT speaker, text, created_at, zh FROM group_messages"
                        " WHERE topic_id = ? ORDER BY id",
                        (row[0],),
                    )
                ],
            }
            for row in reversed(topics)
        ]
        latest = history[-1] if history else None
        return {
            "id": group[0],
            "name": group[1],
            "on": bool(group[2]),
            "created_at": group[3],
            "last_topic_at": group[4],
            "members": self._member_shown(db, group_id),
            "topic": latest["topic"] if latest else None,
            "lines": latest["lines"] if latest else [],
            "history": history,
        }

    def _default_members(self) -> list[str]:
        return list(self._characters)[: self._member_count]

    async def create(self, user_id: str, name: str, ids: Sequence[str]) -> str | None:
        """Start a group with the chosen members (拉群) and have someone raise its first topic;
        the new group's id, or None where there is no one to put in it."""
        chosen = [cid for cid in ids if cid in self._characters] or self._default_members()
        if not chosen:
            return None
        group_id = secrets.token_urlsafe(12)
        await self._db.write(
            self._create, user_id, group_id, _clean_name(name), chosen, self._clock()
        )
        await self.raise_topic(user_id, group_id)
        return group_id

    def _create(
        self, db: sqlite3.Connection, user_id: str, group_id: str, name: str,
        ids: Sequence[str], now: datetime,
    ) -> None:
        db.execute(
            "INSERT INTO group_chats (id, user_id, name, is_on, created_at)"
            " VALUES (?, ?, ?, 1, ?)",
            (group_id, user_id, name, now.isoformat()),
        )
        for cid in ids:
            db.execute(
                "INSERT INTO group_members (group_id, character_id) VALUES (?, ?)",
                (group_id, cid),
            )

    async def rename(self, user_id: str, group_id: str, name: str) -> None:
        """Give the group a new name."""
        cleaned = _clean_name(name)
        if not cleaned:
            return
        await self._db.write(self._rename, user_id, group_id, cleaned)

    def _rename(self, db: sqlite3.Connection, user_id: str, group_id: str, name: str) -> None:
        db.execute(
            "UPDATE group_chats SET name = ? WHERE id = ? AND user_id = ? AND dissolved_at IS NULL",
            (name, group_id, user_id),
        )

    async def set_on(self, user_id: str, group_id: str, on: bool) -> None:
        """Turn the group's scheduler on or off; off only stops new topics, nothing is deleted."""
        await self._db.write(self._set_on, user_id, group_id, on)

    def _set_on(
        self, db: sqlite3.Connection, user_id: str, group_id: str, on: bool
    ) -> None:
        db.execute(
            "UPDATE group_chats SET is_on = ? WHERE id = ? AND user_id = ? AND dissolved_at IS NULL",
            (int(on), group_id, user_id),
        )

    async def set_members(self, user_id: str, group_id: str, ids: Sequence[str]) -> None:
        """Set who is in the group, those that exist; nothing for an empty or unknown list."""
        chosen = [cid for cid in ids if cid in self._characters]
        if not chosen:
            return
        await self._db.write(self._set_members, user_id, group_id, chosen)

    def _set_members(
        self, db: sqlite3.Connection, user_id: str, group_id: str, ids: Sequence[str]
    ) -> None:
        kept = db.execute(
            "SELECT 1 FROM group_chats WHERE id = ? AND user_id = ? AND dissolved_at IS NULL",
            (group_id, user_id),
        ).fetchone()
        if kept is None:
            return
        db.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))
        for cid in ids:
            db.execute(
                "INSERT INTO group_members (group_id, character_id) VALUES (?, ?)",
                (group_id, cid),
            )

    async def dissolve(self, user_id: str, group_id: str) -> None:
        """Dissolve the group (解散): it leaves the list, its topics close and its history is
        hidden. The conversations under way end with it."""
        await self._db.write(self._dissolve, user_id, group_id, self._clock())
        task = self._tasks.pop(group_id, None)
        if task is not None:
            task.cancel()

    def _dissolve(
        self, db: sqlite3.Connection, user_id: str, group_id: str, now: datetime
    ) -> None:
        db.execute(
            "UPDATE group_chats SET dissolved_at = ?, is_on = 0"
            " WHERE id = ? AND user_id = ? AND dissolved_at IS NULL",
            (now.isoformat(), group_id, user_id),
        )
        db.execute(
            "UPDATE group_topics SET closed_at = ? WHERE group_id = ? AND closed_at IS NULL",
            (now.isoformat(), group_id),
        )

    # ---- the scheduler ----------------------------------------------------------------

    async def keep_going(self) -> None:
        """Raise a topic in every group whose time has come, once every `TICK`."""
        while True:
            try:
                await self._tick()
            except Exception:
                log.exception("the group chat's scheduler failed")
            await asyncio.sleep(TICK.total_seconds())

    async def _tick(self) -> None:
        now = self._clock()
        due = await self._db.read(self._due, now)
        for group_id, user_id in due:
            if group_id in self._busy:
                continue
            self._busy.add(group_id)
            try:
                await self.raise_topic(user_id, group_id)
            except Exception:
                log.exception("raising a group topic failed")
            finally:
                self._busy.discard(group_id)

    def _due(self, db: sqlite3.Connection, now: datetime) -> list[tuple[str, str]]:
        if _at_quiet(now):
            return []
        rows = db.execute(
            "SELECT id, user_id FROM group_chats WHERE is_on = 1 AND dissolved_at IS NULL"
            " AND (next_topic_at IS NULL OR next_topic_at <= ?)",
            (now.isoformat(),),
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def _next_topic_at(self, now: datetime) -> str:
        """When this group next raises a topic on its own: 2 to 6 hours from now, at random."""
        seconds = random.uniform(self._gap[0].total_seconds(), self._gap[1].total_seconds())
        return (now + timedelta(seconds=seconds)).isoformat()

    # ---- a topic, talked through ------------------------------------------------------

    async def raise_topic(self, user_id: str, group_id: str) -> str | None:
        """Have a member raise a topic and the others talk it through in the background; the
        topic's id, or None where the group is gone, off or has no members."""
        state = await self.read(user_id, group_id)
        if state is None or not state["on"] or not state["members"]:
            return None
        members = [self._members_by_id(m["id"]) for m in state["members"]]
        members = [m for m in members if m is not None]
        if not members:
            return None
        recent = state["lines"][-6:]
        # What it has been talking about, latest first, so the new topic can stay off it.
        past = [entry["topic"]["text"] for entry in reversed(state["history"])][:TOPIC_RECALL]
        raiser = members[secrets.randbelow(len(members))]
        try:
            said = await self._raise(user_id, members, raiser, recent, past)
        except Exception:
            log.warning("a member could not raise a topic", exc_info=True)
            return None
        topic_id = secrets.token_urlsafe(12)
        now = self._clock()
        await self._db.write(
            self._start_topic, user_id, group_id, topic_id, raiser.id, said.ja, said.zh, now
        )
        self._start_conversation(user_id, group_id, topic_id, members, said.ja, raiser.id)
        return topic_id

    async def _raise(
        self, user_id: str, members: Sequence[Member], raiser: Member, recent: Sequence[dict],
        past: Sequence[str],
    ) -> Said:
        system = await self._system(user_id, raiser)
        material = await self._material(user_id, raiser)
        prompt = _topic_prompt(
            system, raiser, members, recent,
            self._names_block(members), past, material,
        )
        answer = await self._ask(prompt)
        said = _parse_line(answer) or Said("今天想聊点什么呢。", "今天想聊点什么好呢。")
        return said if said.zh else await self._subtitle(said)

    def _names_block(self, members: Sequence[Member]) -> str:
        """How her names are written in the subtitles, for the prompt.

        Those of this group spelled out one a line, as they are the ones she is talking to
        and the ones that came out wrong; everyone else named once on a line of their own, so
        that a name she brings up is not the model's to make up (`.scratch/nsfw/`).

        Written tighter than `reply_format.names_instructions`, which a conversation reads
        once a turn: a group writes a line every few seconds, and neither the header nor the
        fallback is worth that many tokens each time."""
        in_group = {
            member.id: self._characters[member.id]
            for member in members
            if member.id in self._characters
        }
        names = chinese_names(in_group)
        rest = {ja: zh for ja, zh in chinese_names(self._characters).items() if ja not in names}
        lines = ["# 名字怎么译", "字幕里提到人时照下面的中文名写，不要自己音译："]
        lines += [f"- {ja} → {zh}" for ja, zh in names.items()]
        if rest:
            lines.append("其余人：" + "、".join(rest.values()))
        lines.append("同一个名字在整段里写法要一致。")
        return "\n".join(lines)

    async def _material(self, user_id: str, member: Member) -> str:
        """What she may talk from besides her own sheet: what she remembers of the producer.

        Without something of the day's, a topic could only be made out of her character sheet,
        and the group went round the same three hooks (`.scratch/nsfw/`)."""
        if self._memories is None:
            return ""
        try:
            held = await self._memories.kept(user_id)
        except Exception:
            log.warning("reading her memories for the group failed", exc_info=True)
            return ""
        hers = [memory for memory in held if memory.source_character_id == member.id]
        if not hers:
            return ""
        return "她记得的和制作人的事：\n" + "".join(
            f"- {memory.text}\n" for memory in hers[-MATERIAL_MEMORIES:]
        )

    def _start_conversation(
        self, user_id: str, group_id: str, topic_id: str, members: Sequence[Member],
        topic: str, raised_by: str, *, mentioned: Sequence[str] = (),
        threshold: float = BASE_THRESHOLD, delay: tuple[float, float] | None = None,
    ) -> None:
        """Talk the topic through in the background, so the page can show the lines as they
        come and the user can cut in between them."""
        previous = self._tasks.pop(group_id, None)
        if previous is not None:
            previous.cancel()
        task = asyncio.create_task(
            self._converse(
                user_id, group_id, topic_id, members, topic, raised_by,
                mentioned=mentioned, threshold=threshold, delay=delay,
            )
        )
        self._tasks[group_id] = task

        def done(finished: "asyncio.Task[None]") -> None:
            if self._tasks.get(group_id) is finished:
                self._tasks.pop(group_id, None)

        task.add_done_callback(done)

    async def _converse(
        self, user_id: str, group_id: str, topic_id: str, members: Sequence[Member],
        topic: str, raised_by: str, *, mentioned: Sequence[str] = (),
        threshold: float = BASE_THRESHOLD, delay: tuple[float, float] | None = None,
    ) -> None:
        """Talk the topic through: each member who wants to answer waits her own spell, and
        whoever's runs out first speaks; the bar rises and the outsider's mention falls, until
        no one is willing or `MAX_TURNS`. `mentioned` are the members the user named or
        addressed, whose willingness is raised; `delay` is the timer's range (the shorter one
        is for answering the user)."""
        timer = delay or self._delay
        try:
            scores = await self._relevance(members, topic)
            past = await self._past(group_id, topic_id)
        except Exception:
            log.exception("reading the group's own context failed")
            scores, past = {}, []
        by_id = {member.id: member for member in members}
        last_speaker = raised_by
        spoken: dict[str, int] = {}

        def willing(member: Member) -> float:
            bonus = MENTION_BONUS if member.id in mentioned else 0.0
            return (
                scores.get(member.id, 0.0) + bonus - spoken.get(member.id, 0) * SPEAK_DECAY
            )

        # Each member who wants to answer gets her own moment: her own timer, started now.
        # A raised topic always gets at least one answer — the most willing member speaks even
        # when nobody clears the bar — so a topic is never left hanging on its first line.
        pending: dict[str, float] = {}
        try:
            others = [member for member in members if member.id != raised_by]
            willing_now = [member for member in others if willing(member) >= threshold]
            if not willing_now and others:
                willing_now = [
                    max(others, key=lambda member: willing(member))
                ]
            for member in willing_now:
                pending[member.id] = time.monotonic() + random.uniform(*timer)
            for turn in range(MAX_TURNS):
                if not pending:
                    break
                # Whoever's timer is up first speaks; when several are due, the earliest wins.
                speaker_id = min(pending, key=lambda mid: pending[mid])
                due = pending.pop(speaker_id)
                wait = due - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                speaker = by_id[speaker_id]
                said = await self._lines(topic_id)
                mention = max(0.0, BASE_MENTION - turn * MENTION_STEP)
                outsiders = [m for m in members if m.id not in {speaker.id, last_speaker}]
                system = await self._system(user_id, speaker)
                prompt = _say_prompt(
                    system, speaker, members, said, past, mention, outsiders,
                    self._names_block([*members, *outsiders]),
                )
                try:
                    answer = await self._ask(prompt)
                except Exception:
                    log.warning("a member could not answer in the group", exc_info=True)
                    break
                line = _parse_line(answer)
                if line is None or not line.ja:
                    # She gave nothing readable this time: pass and let the others go on,
                    # rather than ending the whole topic on one bad answer.
                    log.warning("a member gave no readable line; passing")
                    continue
                if not line.zh:
                    line = await self._subtitle(line)
                now = self._clock()
                await self._db.write(
                    self._add_line, topic_id, user_id, speaker.id, line.ja, line.zh, now
                )
                spoken[speaker.id] = spoken.get(speaker.id, 0) + 1
                last_speaker = speaker.id
                # The bar rises with each line; whoever is no longer willing drops out.
                limit = threshold + (turn + 1) * THRESHOLD_STEP
                pending = {
                    mid: at for mid, at in pending.items()
                    if mid != speaker.id and willing(by_id[mid]) >= limit
                }
        except asyncio.CancelledError:
            raise
        finally:
            await self._close_topic(group_id, topic_id)
            await self._remember(user_id, topic_id, members)

    async def _subtitle(self, line: Said) -> Said:
        """Her line with a Chinese subtitle, asking for one when the model left `<zh>` out."""
        try:
            answer = await self._ask(
                [
                    ChatMessage(
                        "system",
                        "你是翻译。把用户给的日语翻成自然的中文口语，只输出译文，不要解释。",
                    ),
                    ChatMessage("user", line.ja),
                ]
            )
            subtitle = _clean_line(answer)
        except Exception:
            log.warning("translating a group line failed", exc_info=True)
            return line
        return Said(line.ja, subtitle) if subtitle else line

    async def _system(self, user_id: str, member: Member) -> str:
        """Who she is, and how she feels about the producer, as the affinity tier says."""
        tier = ""
        if self._affinities is not None:
            try:
                status = await self._affinities.status(user_id, member.id)
                tier = "\n".join(tier_prompt(status))
            except Exception:
                log.warning("reading her affinity for the group failed", exc_info=True)
        label = f"{member.name}（中文名 {member.name_zh}）" if member.name_zh else member.name
        return f"你叫{label}。{member.sheet}\n你们在群聊里。" + (f"\n{tier}" if tier else "")

    async def _relevance(
        self, members: Sequence[Member], topic: str
    ) -> dict[str, float]:
        """How relevant each member finds the topic, 0 to 1, one model call; none on
        failing (the topic then goes nowhere rather than guess)."""
        prompt = _relevance_prompt(members, topic)
        try:
            answer = await self._ask(prompt)
        except Exception:
            log.warning("judging the group's relevance failed", exc_info=True)
            return {}
        scores = _parse_scores(answer, [member.id for member in members])
        log.info("group relevance for %r: %s", topic[:40], scores)
        return scores

    async def _ask(self, messages: Sequence[ChatMessage]) -> str:
        """One model answer; asked twice when the first comes back empty, which happens
        now and then and would otherwise end a conversation on the spot."""
        for attempt in range(2):
            lease = self._lease_of()
            try:
                chunks: list[str] = []
                async for chunk in lease.keys.chat_llm.stream(messages):
                    if isinstance(chunk, str):
                        chunks.append(chunk)
                text = "".join(chunks)
            finally:
                lease.release()
            if text.strip() or attempt == 1:
                return text
        return ""

    # ---- the user's own line ----------------------------------------------------------

    async def say(self, user_id: str, group_id: str, text: str) -> None:
        """The user says something, an ordinary member's line: it goes on with the group's
        latest topic (reopened if it had wound down), or starts a new one if it is a new
        subject."""
        text = text.strip()[:MAX_LINE_CHARS]
        if not text:
            return
        state = await self.read(user_id, group_id)
        if state is None or not state["on"]:
            return
        topic = state["topic"]
        now = self._clock()
        members = [self._members_by_id(m["id"]) for m in state["members"]]
        members = [m for m in members if m is not None]
        lines = await self._lines(topic["id"]) if topic is not None else []
        last_speaker = lines[-1].speaker if lines else USER_SPEAKER
        fresh, mentioned, addressed = await self._shift(members, lines, text)
        if (
            not fresh
            and not mentioned
            and not addressed
            and last_speaker != USER_SPEAKER
            and text.rstrip().endswith(("？", "?"))
        ):
            # A question with no name is still asked of whoever just spoke.
            addressed = [last_speaker]
        if topic is None or fresh:
            topic_id = secrets.token_urlsafe(12)
            await self._db.write(
                self._start_topic, user_id, group_id, topic_id, USER_SPEAKER, text, "", now
            )
            if members:
                self._start_conversation(
                    user_id, group_id, topic_id, members, text, USER_SPEAKER,
                    threshold=BASE_THRESHOLD,
                )
            return
        topic_id = topic["id"]
        await self._db.write(self._add_line, topic_id, user_id, USER_SPEAKER, text, "", now)
        if not topic["open"]:
            await self._db.write(self._reopen, topic_id)
        if members and (self._tasks.get(group_id) is None or not topic["open"]):
            self._start_conversation(
                user_id, group_id, topic_id, members, text, last_speaker,
                mentioned=[*mentioned, *addressed], threshold=CONTINUE_THRESHOLD,
                delay=REPLY_DELAY,
            )

    async def _shift(
        self, members: Sequence[Member], lines: Sequence[Line], text: str
    ) -> tuple[bool, list[str], list[str]]:
        """Whether the user's line starts a new topic, which members it names, and which it is
        addressed to (the one answering, say, even unnamed), one model call; the conversation
        goes on as it was on failing."""
        try:
            answer = await self._ask(_shift_prompt(members, lines, text))
        except Exception:
            log.warning("judging the user's group line failed", exc_info=True)
            return False, [], []
        fresh, mentioned, addressed = _parse_shift(answer, members)
        log.info(
            "group line %r: new topic = %s, mentioned = %s, addressed = %s",
            text[:30], fresh, mentioned, addressed,
        )
        return fresh, mentioned, addressed

    # ---- the memory -------------------------------------------------------------------

    async def _remember(
        self, user_id: str, topic_id: str, members: Sequence[Member]
    ) -> None:
        """Write down what the user revealed in the group, as a private turn's memories are
        written down: only what is worth keeping, and once, not once per member."""
        try:
            lines = await self._lines(topic_id)
            if not lines or not any(line.speaker == USER_SPEAKER for line in lines):
                return
            owner = _owner(lines, members)
            if owner is None:
                return
            held = []
            if self._memories is not None:
                held = (await self._memories.kept(user_id))[-SHOWN_MEMORIES:]
            answer = await self._ask(_memory_prompt(owner, members, lines, held))
            written = _parse_memories(answer)
            if not written:
                return
            now = self._clock()
            await self._db.write(self._write_memories, user_id, owner, written, now)
        except Exception:
            log.warning("writing the group's memories failed", exc_info=True)

    def _write_memories(
        self,
        db: sqlite3.Connection,
        user_id: str,
        owner: Member,
        written: Sequence[str],
        now: datetime,
    ) -> None:
        created_at = now.isoformat()
        for text in written:
            kept = db.execute(
                "SELECT 1 FROM memories WHERE user_id = ? AND text = ?", (user_id, text)
            ).fetchone()
            if kept is not None:
                continue
            db.execute(
                "INSERT INTO memories (user_id, source_character_id, conversation_id, text,"
                " created_at) VALUES (?, ?, NULL, ?, ?)",
                (user_id, owner.id, text, created_at),
            )

    # ---- read/write bodies ------------------------------------------------------------

    def _members_by_id(self, character_id: str) -> Member | None:
        character = self._characters.get(character_id)
        if character is None:
            return None
        name_zh = getattr(character, "name_zh", None) or ""
        return Member(character.id, character.name, character.intro, _sheet(character), name_zh)

    async def _lines(self, topic_id: str) -> list[Line]:
        return await self._db.read(self._read_lines, topic_id)

    async def _past(self, group_id: str, topic_id: str) -> list[Line]:
        """The latest lines of this group's earlier topics: its own recent history."""
        return await self._db.read(self._read_past, group_id, topic_id)

    def _read_past(
        self, db: sqlite3.Connection, group_id: str, topic_id: str
    ) -> list[Line]:
        rows = db.execute(
            "SELECT m.speaker, m.text, m.created_at, m.zh FROM group_messages m"
            " JOIN group_topics t ON t.id = m.topic_id"
            " WHERE t.group_id = ? AND m.topic_id != ? ORDER BY m.id DESC LIMIT ?",
            (group_id, topic_id, PAST_LINES),
        ).fetchall()
        return [Line(row[0], row[1], row[2], row[3]) for row in reversed(rows)]

    def _read_lines(self, db: sqlite3.Connection, topic_id: str) -> list[Line]:
        return [
            Line(row[0], row[1], row[2], row[3])
            for row in db.execute(
                "SELECT speaker, text, created_at, zh FROM group_messages"
                " WHERE topic_id = ? ORDER BY id",
                (topic_id,),
            )
        ]

    def _start_topic(
        self, db: sqlite3.Connection, user_id: str, group_id: str, topic_id: str,
        raised_by: str, text: str, zh: str, now: datetime,
    ) -> None:
        db.execute(
            "UPDATE group_chats SET last_topic_at = ?, next_topic_at = ? WHERE id = ?",
            (now.isoformat(), self._next_topic_at(now), group_id),
        )
        db.execute(
            "INSERT INTO group_topics (id, group_id, user_id, raised_by, text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (topic_id, group_id, user_id, raised_by, text, now.isoformat()),
        )
        db.execute(
            "INSERT INTO group_messages (topic_id, user_id, speaker, text, zh, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (topic_id, user_id, raised_by, text, zh, now.isoformat()),
        )

    def _add_line(
        self, db: sqlite3.Connection, topic_id: str, user_id: str, speaker: str,
        text: str, zh: str, now: datetime,
    ) -> None:
        db.execute(
            "INSERT INTO group_messages (topic_id, user_id, speaker, text, zh, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (topic_id, user_id, speaker, text, zh, now.isoformat()),
        )

    def _reopen(self, db: sqlite3.Connection, topic_id: str) -> None:
        """Take the topic up again after it had wound down: the user spoke in it."""
        db.execute("UPDATE group_topics SET closed_at = NULL WHERE id = ?", (topic_id,))

    async def _close_topic(self, group_id: str, topic_id: str) -> None:
        now = self._clock()
        try:
            await self._db.write(self._closed, group_id, topic_id, now)
        except Exception:
            log.warning("closing the group topic failed", exc_info=True)

    def _closed(
        self, db: sqlite3.Connection, group_id: str, topic_id: str, now: datetime
    ) -> None:
        db.execute(
            "UPDATE group_topics SET closed_at = ? WHERE id = ? AND group_id = ?",
            (now.isoformat(), topic_id, group_id),
        )


# ---- the prompts ---------------------------------------------------------------------


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())[:MAX_NAME_CHARS]
    return cleaned or "群聊"


def _sheet(character: Character) -> str:
    """Her personality, cut short enough to sit in a prompt."""
    return " ".join(character.sheet.split())[:900]


def _topic_prompt(
    system: str, raiser: Member, members: Sequence[Member], recent: Sequence[dict],
    names: str, past: Sequence[str], material: str,
) -> list[ChatMessage]:
    context = _context(recent)
    others = "、".join(m.name for m in members if m.id != raiser.id)
    tired = "".join(f"- {text}\n" for text in past)
    user = (
        (f"# 她手边的素材\n{material}\n\n" if material else "")
        + (f"# 这个群最近开过的话头\n{tired}\n" if tired else "")
        + (f"# 刚说过的几句\n{context}\n\n" if context else "")
        + "现在请你主动开一个新话题：像在群里随口说一句，引出你想聊的事。\n"
        "- 说一件**具体**的事：今天遇到的、看到的、听到的、想到的一个细节。"
        "不要只是感想、感慨、「今天也要加油」这种空话。\n"
        "- 上面那些话头都聊过了，别回头再说它们；也别用「说到…」「…话说回来」把上一个"
        "话题接着往下拖——这次自己另起一件不相干的事。\n"
        "- 不要问「有人在吗」，不要提「换个话题」，不要解释。\n"
        "- 一到两句，口语。\n"
        + names
        + "\n用 <ja>日语原文</ja><zh>中文字幕</zh> 输出；<ja> 里只写日语、不要混入中文；"
        "<zh> 是这句日语的中文翻译；专有名词和拟声词可以保留原文，其余都要译成中文、不要夹日语；"
        "「ちゃん」「さん」这类称呼译成「酱」「小姐」或省略；不要留孤零零的假名；只输出这一组标签。"
    )
    return [ChatMessage("system", f"{system}\n群里的其他人：{others}"), ChatMessage("user", user)]


def _say_prompt(
    system: str, speaker: Member, members: Sequence[Member], said: Sequence[Line],
    past: Sequence[Line], mention: float, outsiders: Sequence[Member], names: str,
) -> list[ChatMessage]:
    spoken = {member.id: member.name for member in members}
    recent = list(said)[-RECENT_LINES:]
    # Her Japanese, not its subtitle: shown the Chinese, the model drifts into Chinese mid-line.
    context = "\n".join(
        f"{spoken.get(line.speaker, '制作人')}：{line.text}" for line in [*past, *recent]
    )
    hint = ""
    if outsiders:
        names_out = "、".join(m.name for m in outsiders)
        if secrets.randbelow(100) / 100 < mention:
            hint = f"如果话头合适，可以顺带提到{names_out}；不合适就别硬提。"
        else:
            hint = f"这次别提到{names_out}，就事论事。"
    user = (
        f"群聊记录：\n{context}\n\n"
        "你在群里，接着往下聊。这一句可以是：回应刚才某个人说的（直接用她名字或接话）、"
        "补一句你自己的看法、或者顺着这个话题聊出一个相关的小话题。"
        "一到两句，口语，像群里随口说的；不要复述别人刚说过的，不要旁白，不要每句都提问。"
        + hint
        + "\n"
        + names
        + "\n用 <ja>日语原文</ja><zh>中文字幕</zh> 输出；<ja> 里只写日语、不要混入中文；"
        "<zh> 是这句日语的中文翻译；专有名词和拟声词可以保留原文，其余都要译成中文、不要夹日语；"
        "「ちゃん」「さん」这类称呼译成「酱」「小姐」或省略；不要留孤零零的假名；只输出这一组标签。"
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def _relevance_prompt(members: Sequence[Member], topic: str) -> list[ChatMessage]:
    lines = "\n".join(f"- {m.id}（{m.name}）：{m.intro}" for m in members)
    system = (
        "你是一个群聊的旁白。你要判断每位成员对当前话题有多感兴趣、多相关，"
        "只输出 JSON，不要解释。"
    )
    user = (
        f"话题：{topic}\n\n成员：\n{lines}\n\n"
        "给每位成员一个 0 到 1 的分数（1 表示这个话题正好戳中她、她很有话可说）。"
        "输出形如 {\"mano\": 0.0, \"hiori\": 0.0} 的 JSON，key 只用成员 id，"
        "不要带名字或括号。"
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def _shift_prompt(
    members: Sequence[Member], lines: Sequence[Line], text: str
) -> list[ChatMessage]:
    """Whether the user's line opens a new topic, which members it names, and which it is
    addressed to, as one call."""
    names = {m.id: m.name for m in members}
    recent = list(lines)[-RECENT_LINES:]
    context = "\n".join(
        f"{names.get(line.speaker, '制作人')}：{line.text}" for line in recent
    )
    roster = "\n".join(f"- {m.id}（{m.name}" + (f" / {m.name_zh}" if m.name_zh else "") + "）" for m in members)
    system = "你在看一段群聊，判断制作人刚说的话是什么意思，只输出 JSON，不要解释。"
    user = (
        f"群聊最近的记录：\n{context or '（还没有）'}\n\n"
        f"成员：\n{roster}\n\n"
        f"制作人刚说：「{text}」\n\n"
        "判断三件事：\n"
        "1. 这句话是不是在**开一个新话题**：只有话题明显换了一个（比如从吃饭聊到学习、天气）才算；"
        "追问、补充、附和都不算。\n"
        "2. 这句话里有没有**点名某几位成员**（用名字或昵称叫了她们，比如「めぐる」「巡」）？\n"
        "3. 这句话是在**对谁说**：问句、请求、接话，一定要给出对象（即使没有点名）："
        "「那你呢？」「换你你会怎么做」就是对刚才说话的人说的；"
        "只有纯粹的附和、感叹、自言自语（比如「嗯」「原来是这样」）才写 []。\n"
        "只输出 JSON：{\"new_topic\": true 或 false, \"mentioned\": [\"<成员 id>\", ...], "
        "\"addressed\": [\"<成员 id>\", ...]}，没点名、没对象就写 []。"
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def _parse_shift(answer: str, members: Sequence[Member]) -> tuple[bool, list[str], list[str]]:
    """The JSON in `answer` as whether the line opens a new topic, which members it names,
    and which it is addressed to (by id or by any of their names)."""
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end <= start:
        return False, [], []
    try:
        raw = json.loads(answer[start : end + 1])
    except json.JSONDecodeError:
        return False, [], []
    if not isinstance(raw, dict):
        return False, [], []
    fresh = raw.get("new_topic") is True

    def matched(items: object) -> list[str]:
        if not isinstance(items, list):
            return []
        names = [str(item) for item in items]
        return [
            member.id
            for member in members
            if any(
                member.id == name
                or member.name == name
                or member.id in name
                or member.name in name
                for name in names
            )
        ]

    return fresh, matched(raw.get("mentioned")), matched(raw.get("addressed"))


def _memory_prompt(
    owner: Member, members: Sequence[Member], lines: Sequence[Line], held: Sequence[Memory]
) -> list[ChatMessage]:
    """What the user revealed in the group, as a private turn's extractor reads it: the
    same instructions, the group's lines for the exchange."""
    names = {m.id: m.name for m in members}
    head = ["# 已经记住的事"]
    head += [f"{n}. {m.text}" for n, m in enumerate(held, 1)] or ["（还没有）"]
    head += ["", f"# 群聊记录（{owner.name}也在场）"]
    for line in lines[-SHOWN_MEMORIES:]:
        if line.speaker == USER_SPEAKER:
            head.append(f"制作人：{line.text}")
        else:
            head.append(f"{names.get(line.speaker, line.speaker)}：{line.text}")
    head += ["", "只从制作人说的话里找值得长期记住的、关于他本人的信息；没有就输出 {\"memories\": []}。"]
    return [ChatMessage("system", _INSTRUCTIONS), ChatMessage("user", "\n".join(head))]


def _owner(lines: Sequence[Line], members: Sequence[Member]) -> Member | None:
    """The member the user was talking with: the first of them to speak after the user's
    last line; the last of them to speak, failing that."""
    by_id = {m.id: m for m in members}
    last_user = max(
        (i for i, line in enumerate(lines) if line.speaker == USER_SPEAKER), default=-1
    )
    for line in lines[last_user + 1:]:
        if line.speaker in by_id:
            return by_id[line.speaker]
    for line in reversed(lines):
        if line.speaker in by_id:
            return by_id[line.speaker]
    return None


def _parse_memories(answer: str) -> list[str]:
    """The memories in the extractor's JSON: `{"memories": [{"text": "..."}]}`."""
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        raw = json.loads(answer[start : end + 1])
    except json.JSONDecodeError:
        return []
    items = raw.get("memories") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    texts: list[str] = []
    for item in items:
        text = item.get("text") if isinstance(item, dict) else None
        if isinstance(text, str):
            cleaned = " ".join(text.split())[:MAX_MEMORY_CHARS]
            if cleaned:
                texts.append(cleaned)
    return texts


# ---- small helpers -------------------------------------------------------------------


def _context(lines: Sequence[dict]) -> str:
    """The recent lines as the model reads them: her Japanese, the user's own Chinese."""
    return "\n".join(
        f"{line.get('name') or '你'}：{line['text']}" for line in lines
    )


def _clean_line(answer: str) -> str:
    text = answer.strip().strip("「」\"'")
    text = " ".join(text.split())
    return text[:MAX_LINE_CHARS]


def _parse_line(answer: str) -> Said | None:
    """Her line as the model wrote it: the Japanese and its subtitle in `<ja>`/`<zh>`, or,
    for a model that wrote it plainly, the whole answer as the Japanese."""
    ja = _JA.search(answer)
    zh = _ZH.search(answer)
    if ja is None and zh is None:
        text = _clean_line(answer)
        return Said(text, "") if text else None
    japanese = _clean_line(ja.group(1)) if ja else ""
    subtitle = _clean_line(zh.group(1)) if zh else ""
    if not japanese:
        return None
    return Said(japanese, subtitle)


def _parse_scores(answer: str, ids: Sequence[str]) -> dict[str, float]:
    """The JSON object in `answer`, keeping only the members and clamping to 0-1. The models
    sometimes key by `id｜name` or `id（name）`; the id is taken from before the separator."""
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        raw = json.loads(answer[start : end + 1])
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    by_key: dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, (int, float)):
            continue
        by_key[key.strip()] = float(value)
        for separator in ("｜", "|", "（", "(", ":", "："):
            if separator in key:
                by_key.setdefault(key.split(separator)[0].strip(), float(value))
    scores: dict[str, float] = {}
    for cid in ids:
        if cid in by_key:
            scores[cid] = max(0.0, min(1.0, by_key[cid]))
    return scores
