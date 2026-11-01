"""Her work moment (GLOSSARY.md「朋友圈」「工作」): on a day she has jobs the producer scheduled
her done in Tokyo, she posts of them all, half an hour to two hours after the last is done;
still at work as her time comes, she posts that long after the last of them instead, on the
next day in Tokyo if so, counted the day it was planned for. She is told each job, its name
and what it is, and no seeds of her everyday; the places she is given are of the kinds her jobs
take her to, none if none does. Schedules off, every moment is of her everyday.

Driven as `test_moments.py` drives moments, the week's jobs kept beforehand in the database
and saved through the API as `test_schedule_*` save them; the place pool of the test's own."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from eidolon.config import Settings
from eidolon.place_pool import PLACES_FILE
from tests.conftest import KOGANE_SHEET, MANO_SHEET, CharacterConfig, ClientFactory
from tests.fakes import FakeIdentityProvider, context_of
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_moment_places import CAFE, PARK
from tests.test_moments import FACTS, MOMENTS, POST, talked, tick, timeline
from tests.test_schedule_saving import placed, save
from tests.test_schedule_switch import SCHEDULE
from tests.test_schedule_weeks import live_in

SEASIDE = """\
[[places]]
id = "enoshima"
name = "江の島"
area = "神奈川県藤沢市"
lat = 35.2992
lon = 139.4806
category = "seaside"
note = "湘南的小岛"
checked = 2026-10-01
"""

WEEK = "2026-10-19"
SAVED = datetime(2026, 10, 19, 4, tzinfo=UTC)
"""Monday 12:00 in Shanghai: the week published, Tuesday still to come."""
TUESDAY = datetime(2026, 10, 19, 15, 30, tzinfo=UTC)
"""00:30 on Tuesday, October 20, in Tokyo: the first tick of the day."""

WORK = "# 今天做完的工作"


@pytest.fixture
def characters(tmp_path: Path) -> CharacterConfig:
    """Mano and Kogane, as `test_moments.py` has them, beside a pool of a park, a cafe and a
    seaside out of Tokyo-to."""
    config = (
        CharacterConfig(tmp_path / "characters")
        .add("mano", "櫻木真乃", MANO_SHEET, birthday="04-25", facts=FACTS)
        .add("kogane", "月岡恋鐘", KOGANE_SHEET, birthday="02-25")
    )
    config.write(PLACES_FILE, "\n".join([PARK, CAFE, SEASIDE]))
    return config


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, moments=True, admins=frozenset({ADMIN}))


def publish(database: Path, *listed: str) -> None:
    """Keep Mano's jobs of `WEEK` as drawn, each of the repository's job list by its
    identifier (its id too), with its name and note."""
    names = {
        "morning-run": ("晨跑", "沿着河边慢跑一圈，顺便练呼吸。", 1),
        "cafe": ("去咖啡馆", "找一家安静的咖啡馆坐一坐。", 1),
        "day-trip": ("一日游", "坐电车去附近的城市玩一整天。", 3),
        "vocal-lesson": ("声乐课", "跟老师练发声，重点是新歌高音的部分。", 1),
    }
    with sqlite3.connect(database) as db:
        db.executemany(
            "INSERT INTO weekly_jobs (id, week, position, character_id, listed_id, name, note,"
            " category, length, slots) VALUES (?, ?, ?, 'mano', ?, ?, ?, 'practice', ?, NULL)",
            [(id, WEEK, n, id, *names[id]) for n, id in enumerate(listed)],
        )


async def test_on_a_day_of_her_jobs_she_posts_of_them_all_after_the_last_is_done(
    make_client: ClientFactory, settings: Settings
):
    """Tuesday, in Shanghai, 6 to 12 and 12 to 18: in Tokyo, the last done at 19:00."""
    client, llm, clock, _ = await talked(make_client, POST, at=SAVED)
    publish(settings.database_path, "morning-run", "cafe")
    await save(client, WEEK, placed("morning-run", 1, 0), placed("cafe", 1, 1))

    await tick(client, clock, TUESDAY)
    await tick(client, clock, datetime(2026, 10, 20, 10, 29, tzinfo=UTC))
    before = await timeline(client)
    await tick(client, clock, datetime(2026, 10, 20, 10, 30, tzinfo=UTC))

    assert before == []
    [moment] = await timeline(client)
    assert moment["posted_at"] == "2026-10-20T10:30:00+00:00"  # 19:30 in Tokyo
    told = context_of(llm.prompts[-1])
    assert f"{WORK}\n" in told
    assert "- 晨跑：沿着河边慢跑一圈，顺便练呼吸。\n- 去咖啡馆：找一家安静的咖啡馆坐一坐。" in told
    assert "# 日常的素材" not in told
    assert "- inokashira：" in told and "- kissa：" in told and "enoshima" not in told


@pytest.mark.parametrize(
    ("job", "given"),
    [("cafe", ["kissa"]), ("day-trip", ["enoshima"]), ("vocal-lesson", [])],
)
async def test_the_places_she_is_given_are_of_the_kinds_her_jobs_take_her_to(
    make_client: ClientFactory, settings: Settings, job: str, given: list[str]
):
    """A day trip to anywhere in the outskirts; a vocal lesson to none to name. Ticked at
    02:30 on Wednesday in Tokyo, by when the whole day trip is done too."""
    client, llm, clock, _ = await talked(make_client, POST, POST, at=SAVED)
    publish(settings.database_path, job)
    await save(client, WEEK, placed(job, 1, 0))

    await tick(client, clock, TUESDAY)
    await tick(client, clock, TUESDAY + timedelta(days=1, hours=2))

    told = context_of(llm.prompts[-1])
    assert WORK in told
    named = [id for id in ("inokashira", "kissa", "enoshima") if f"- {id}：" in told]
    assert named == given
    assert ("这次没有候选，写 none。" in told) == (not given)


async def test_at_work_still_as_her_time_comes_she_posts_after_it_past_midnight_of_her_day(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """In Darwin, half an hour behind Tokyo: Tuesday's morning job is done at 11:30 in Tokyo,
    her moment due at 12:00; the evening job saved since is done at 23:30, and she posts at
    00:00 on Wednesday, Tuesday's, leaving Wednesday's one moment a day to come."""
    client, llm, clock, _ = await talked(make_client, POST, POST, at=SAVED)
    await live_in(client, "Australia/Darwin")
    async with admin_beside(client, github) as admin:
        await admin.put(MOMENTS, json={"enabled": True, "per_day": 1})
    publish(settings.database_path, "morning-run", "cafe")
    await save(client, WEEK, placed("morning-run", 1, 0))

    await tick(client, clock, TUESDAY)
    await save(client, WEEK, placed("cafe", 1, 2))
    await tick(client, clock, datetime(2026, 10, 20, 3, tzinfo=UTC))  # 12:00 in Tokyo
    at_twelve = await timeline(client)
    await tick(client, clock, datetime(2026, 10, 20, 14, 59, tzinfo=UTC))
    await tick(client, clock, datetime(2026, 10, 20, 15, tzinfo=UTC))  # 00:00 on Wednesday
    at_midnight = await timeline(client)
    await tick(client, clock, datetime(2026, 10, 20, 22, tzinfo=UTC))  # 07:00 on Wednesday

    assert at_twelve == []
    assert [m["posted_at"] for m in at_midnight] == ["2026-10-20T15:00:00+00:00"]
    assert len(await timeline(client)) == 2
    assert "- 去咖啡馆：" in context_of(llm.prompts[-2])
    assert WORK not in context_of(llm.prompts[-1])


async def test_with_schedules_off_she_posts_of_her_everyday(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client, llm, clock, _ = await talked(make_client, POST, at=SAVED)
    publish(settings.database_path, "cafe")
    await save(client, WEEK, placed("cafe", 1, 0))
    async with admin_beside(client, github) as admin:
        await admin.put(SCHEDULE, json={"enabled": False})

    await tick(client, clock, TUESDAY)
    await tick(client, clock, TUESDAY + timedelta(hours=6, minutes=30))  # 07:00 in Tokyo

    [moment] = await timeline(client)
    told = context_of(llm.prompts[-1])
    assert WORK not in told and "# 日常的素材" in told
