"""Moments age out (GLOSSARY.md「朋友圈」「动态」): each is deleted once it showed 30 days ago,
with its picture, her circle's likes and comments, and the producer's like and comment, her
reply with it, shown or not; in batches, as the backend tidies up (`housekeeping`), whether
moments are on or off. A moment planned and missed goes once the day it was of in Tokyo is
the day before yesterday. Deleting the user deletes all of their moments; deleting a past
conversation none; and none goes into a data package.

Driven through the backend's external API, the user's turn taken as `test_moments.py` takes
it, their moments put in the database as `test_moments_she_knows.py` puts them, and the
backend's tidying up taken by hand (`Moments.forget_old`)."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from eidolon import housekeeping
from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.test_conversation_events import hang_up
from tests.test_data_package import export, unzipped
from tests.test_delete_account import DELETE, user_id
from tests.test_moments import START, talked, timeline
from tests.test_moments_she_knows import JA, put
from tests.test_reach_outs import backend_of
from tests.test_text_turn import start_conversation

MOMENT_TABLES = (
    "moments", "moment_images", "moment_circle", "moment_likes", "moment_comments",
)
"""The tables a moment and what goes with it are in."""

NOW = START + timedelta(days=40)


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, moments=True)


def put_all(database: Path, posted_at: datetime) -> int:
    """A moment posted at `posted_at` with everything that goes with it: a picture, a like
    and a comment of her circle's, the producer's like, and his comment, her reply to it
    not shown yet."""
    moment = put(
        database, posted_at, pictured=True, liked=True, commented="好可爱",
        reply_at=NOW + timedelta(hours=1),
    )
    with sqlite3.connect(database) as db:
        db.executemany(
            "INSERT INTO moment_circle (moment_id, character_id, kind, ja, zh, position,"
            " shown_at) VALUES (?, 'kogane', ?, ?, ?, 0, ?)",
            [(moment, "like", None, None, posted_at.isoformat()),
             (moment, "comment", "いいね", "不错", posted_at.isoformat())],
        )
    return moment


def rows_of(database: Path) -> dict[str, list[int]]:
    """Of each table a moment and what goes with it are in, which moments its rows are of."""
    with sqlite3.connect(database) as db:
        return {
            table: sorted(
                m for (m,) in db.execute(
                    f"SELECT {'id' if table == 'moments' else 'moment_id'} FROM {table}"
                )
            )
            for table in MOMENT_TABLES
        }


async def test_a_moment_that_showed_30_days_ago_goes_with_all_that_goes_with_it(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, _ = await talked(make_client)
    database = settings.database_path
    put_all(database, NOW - timedelta(days=30))
    kept = put_all(database, NOW - timedelta(days=30) + timedelta(minutes=1))
    clock.now = NOW

    await backend_of(client).moments.forget_old()

    assert rows_of(database) == {
        "moments": [kept], "moment_images": [kept], "moment_circle": [kept, kept],
        "moment_likes": [kept], "moment_comments": [kept],
    }


async def test_batch_by_batch_every_moment_aged_out_goes(
    make_client: ClientFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(housekeeping, "BATCH", 2)
    client, _, clock, _ = await talked(make_client)
    database = settings.database_path
    for days in range(31, 36):
        put_all(database, NOW - timedelta(days=days))
    clock.now = NOW

    await backend_of(client).moments.forget_old()

    assert rows_of(database) == {table: [] for table in MOMENT_TABLES}


async def test_a_moment_planned_and_missed_goes_once_its_day_is_the_day_before_yesterday(
    make_client: ClientFactory, settings: Settings
):
    client, _, clock, _ = await talked(make_client)
    database = settings.database_path
    today = date(2026, 11, 28)  # in Tokyo, at `NOW`
    with sqlite3.connect(database) as db:
        db.executemany(
            "INSERT INTO moment_plans (user_id, character_id, day, due_at, kind, birthday)"
            " VALUES (?, 'mano', ?, ?, 'daily', 0)",
            [(user_id(database, "producer"), (today - timedelta(days=days)).isoformat(),
              (NOW - timedelta(days=days)).isoformat()) for days in range(4)],
        )
    clock.now = NOW

    await backend_of(client).moments.forget_old()

    with sqlite3.connect(database) as db:
        assert [d for (d,) in db.execute("SELECT day FROM moment_plans ORDER BY day")] == [
            "2026-11-27", "2026-11-28",
        ]


async def test_deleting_the_user_deletes_all_of_their_moments(
    make_client: ClientFactory, settings: Settings
):
    client, _, _, _ = await talked(make_client)
    database = settings.database_path
    producer = user_id(database, "producer")
    put_all(database, START - timedelta(hours=1))
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO moment_plans (user_id, character_id, day, due_at, kind, birthday)"
            " VALUES (?, 'mano', '2026-10-19', ?, 'daily', 0)",
            (producer, START.isoformat()),
        )
        db.execute(
            "INSERT INTO moment_users VALUES (?, '2026-10-19', ?)", (producer, START.isoformat())
        )
        db.execute("INSERT INTO moments_off VALUES (?)", (producer,))

    tables = (*MOMENT_TABLES, "moment_plans", "moment_users", "moments_off")

    res = await client.post("/api/account/delete", json=DELETE)

    assert res.status_code == 204
    with sqlite3.connect(database) as db:
        assert {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables
        } == dict.fromkeys(tables, 0)


async def test_deleting_a_past_conversation_leaves_her_moments_as_they_are(
    make_client: ClientFactory, settings: Settings
):
    client, _, _, past = await talked(make_client)
    database = settings.database_path
    moment = put_all(database, START - timedelta(hours=1))
    hang_up(database, past)
    await start_conversation(client)

    assert (await client.delete(f"/api/conversations/{past}")).status_code == 204

    assert [m["id"] for m in await timeline(client)] == [moment]
    assert rows_of(database) == {
        "moments": [moment], "moment_images": [moment], "moment_circle": [moment, moment],
        "moment_likes": [moment], "moment_comments": [moment],
    }


async def test_no_moment_goes_into_a_data_package(
    make_client: ClientFactory, settings: Settings
):
    client, _, _, _ = await talked(make_client)
    put_all(settings.database_path, START - timedelta(hours=1))

    entries, manifest, data = unzipped(
        await export(client, "conversations,photos,memories,profile,cycles")
    )

    packaged = json.dumps([manifest, data], ensure_ascii=False)
    assert JA not in packaged
    assert "moment" not in packaged
    assert [e.filename for e in entries if "moment" in e.filename] == []
