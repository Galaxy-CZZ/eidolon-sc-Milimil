"""Saving jobs into the producer's schedule (GLOSSARY.md「日程」「时间段」): each placed at a day
of their week and the slot it starts in, as many slots in a row as it is long, in their own
time zone. Saved is for good: nothing saved is moved or taken back. What cannot be placed is
handed back with why, as the browser tells it, the rest saved: a slot begun or past, one
taken by another job (saved before, or earlier in the same saving), one the job may not be
in, a job too long for what is left of the day; a week not published, a job not of the week,
a job saved already. Two saving into the same slot at once save one of them.

Driven through the backend's external API, the week's jobs kept beforehand in the database
(`publish`), as the week's draw would have kept them."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import httpx

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import FakeClock, FakeLLM
from tests.test_schedule_weeks import MONDAY, live_in, schedule

WEEK = "2026-09-21"
WEDNESDAY_AFTERNOON = MONDAY + timedelta(days=2, hours=14)
"""Wednesday 14:00 in Shanghai, where the producer is: the afternoon under way."""


def publish(
    database: Path,
    week: str,
    *jobs: tuple[str, int, list[str] | None],
    character: str = "mano",
) -> None:
    """Keep the character's jobs of `week`, each its name, length and slots, as drawn; the
    job's id is its name, its note「说明」."""
    with sqlite3.connect(database) as db:
        position = db.execute(
            "SELECT COUNT(*) FROM weekly_jobs WHERE week = ?", (week,)
        ).fetchone()[0]
        db.executemany(
            "INSERT INTO weekly_jobs (id, week, position, character_id, listed_id, name, note,"
            " category, length, slots) VALUES (?, ?, ?, ?, ?, ?, '说明', 'practice', ?, ?)",
            [
                (name, week, position + n, character, name, name, length,
                 slots and json.dumps(slots))
                for n, (name, length, slots) in enumerate(jobs)
            ],
        )


def placed(job: str, day: int, slot: int) -> dict:
    return {"job_id": job, "day": day, "slot": slot}


async def save(client: httpx.AsyncClient, week: str, *placements: dict) -> httpx.Response:
    return await client.post(
        f"/api/schedule/weeks/{week}", json={"placements": list(placements)}
    )


async def test_what_can_be_placed_is_saved_and_the_rest_handed_back_with_why(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(), clock=FakeClock(WEDNESDAY_AFTERNOON))
    publish(
        settings.database_path, WEEK,
        ("lesson", 1, None), ("talk", 1, None), ("shoot", 2, None), ("trip", 3, None),
        ("dinner", 1, ["evening"]),
    )
    publish(settings.database_path, "2026-09-28", ("later", 1, None))

    res = await save(
        client, WEEK,
        placed("lesson", 3, 0),
        placed("shoot", 3, 0),  # the morning is the lesson's, just saved
        placed("shoot", 3, 2),
        placed("trip", 4, 1),
        placed("dinner", 4, 0),
        placed("lesson", 5, 0),
        placed("talk", 1, 2),  # Tuesday evening
        placed("talk", 2, 1),  # this afternoon
        placed("later", 6, 0),
        placed("shoot", 3, 1),
        placed("trip", 5, 0),
    )

    assert res.status_code == 200, res.text
    assert res.json() == {
        # Saved again at another day and slot, the lesson moves there instead of being
        # turned away (`unsave`'s other half, `.scratch/nsfw/`), and the slot it left is
        # free — which is why the trip finds the evening taken.
        "saved": [placed("lesson", 3, 0), placed("lesson", 5, 0), placed("shoot", 3, 1)],
        "returned": [
            placed("shoot", 3, 0) | {"reason": "格子里有别的工作"},
            placed("shoot", 3, 2) | {"reason": "当天排不下"},
            placed("trip", 4, 1) | {"reason": "一整天的工作只能从上午排"},
            placed("dinner", 4, 0) | {"reason": "只能排在晚上"},
            placed("talk", 1, 2) | {"reason": "已经过了"},
            placed("talk", 2, 1) | {"reason": "正在进行"},
            placed("later", 6, 0) | {"reason": "这项工作不在这一周"},
            placed("trip", 5, 0) | {"reason": "格子里有别的工作"},
        ],
    }
    assert (await schedule(client))["this_week"]["placements"] == [
        placed("shoot", 3, 1), placed("lesson", 5, 0),
    ]


async def test_a_week_not_published_takes_nothing(make_client: ClientFactory, settings: Settings):
    # Three weeks past this one: the group opens together, so the second is hers to save into
    # and this one is not (`OPEN_WEEKS`, `.scratch/nsfw/`).
    client = make_client(FakeLLM(), clock=FakeClock(WEDNESDAY_AFTERNOON))
    publish(settings.database_path, "2026-10-12", ("later", 1, None))

    res = await save(client, "2026-10-12", placed("later", 0, 0))

    assert res.json() == {
        "saved": [], "returned": [placed("later", 0, 0) | {"reason": "这一周的工作还没有发布"}],
    }


async def test_saved_is_kept_by_day_and_slot_wherever_the_producer_moves_and_can_be_taken_back(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(), clock=FakeClock(WEDNESDAY_AFTERNOON))
    publish(settings.database_path, WEEK, ("lesson", 1, None))
    await save(client, WEEK, placed("lesson", 4, 2))

    await live_in(client, "America/New_York")  # Wednesday 02:00 there
    moved = (await schedule(client))["this_week"]["placements"]
    changed = await client.put(f"/api/schedule/weeks/{WEEK}", json={"placements": []})

    assert moved == [placed("lesson", 4, 2)]
    # No route replaces a week wholesale; taking one back out is its own (`unsave`,
    # `.scratch/nsfw/`), and then the slot is free again.
    assert changed.status_code == 405
    assert (await schedule(client))["this_week"]["placements"] == moved
    taken = await client.request(
        "DELETE", f"/api/schedule/weeks/{WEEK}", json={"jobs": ["lesson"]}
    )
    assert taken.status_code == 200
    assert (await schedule(client))["this_week"]["placements"] == []


async def test_in_the_hours_before_the_morning_the_whole_day_is_still_to_come(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(), clock=FakeClock(MONDAY + timedelta(days=2, hours=5)))
    publish(settings.database_path, WEEK, ("trip", 3, None))

    res = await save(client, WEEK, placed("trip", 2, 0))

    assert res.json()["saved"] == [placed("trip", 2, 0)]


async def test_two_saving_into_the_same_slot_at_once_save_one(
    make_client: ClientFactory, settings: Settings
):
    clock = FakeClock(WEDNESDAY_AFTERNOON)
    phone = make_client(FakeLLM(), clock=clock)
    desktop = make_client(FakeLLM(), clock=clock)
    publish(settings.database_path, WEEK, ("lesson", 1, None), ("talk", 1, None))

    both = await asyncio.gather(
        save(phone, WEEK, placed("lesson", 6, 1)), save(desktop, WEEK, placed("talk", 6, 1))
    )

    assert sorted(len(r.json()["saved"]) for r in both) == [0, 1]
    assert len((await schedule(phone))["this_week"]["placements"]) == 1


async def test_a_week_is_named_by_its_monday(make_client: ClientFactory):
    client = make_client(FakeLLM(), clock=FakeClock(WEDNESDAY_AFTERNOON))

    for week in ("2026-09-23", "next", "2026-9-21"):
        assert (await save(client, week)).status_code == 404, week
