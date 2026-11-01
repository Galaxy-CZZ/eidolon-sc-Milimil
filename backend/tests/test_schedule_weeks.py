"""Each week's jobs (GLOSSARY.md「工作」): published at Monday 0:00 Beijing time, the week named
by that Monday's date; seven of the idols, never the office's staff, each given two or three
jobs from the job list, 24 to 27 slots in all, no job twice in a week, at least one of work
and at most one private each; every idol once in four weeks running. Drawn as a week is first
read and kept, the same for everyone, and kept as it was when the list changes.

The producer reads their week (`/api/schedule`) in their own time zone (their profile's, else
their device's, else Shanghai's): this week, and next week once it is published, which is
already on their Sunday west of Beijing; east of it, their Monday's first hours come before
their week is published, and they are told when it will be."""

from collections import Counter
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from eidolon.characters import load_characters
from eidolon.job_list import JOBS_FILE, WORK, load_job_list
from eidolon.schedule import FIRST_WEEK, draw_week, idols_of
from eidolon.world import load_world

from tests.conftest import REPO_JOBS, CharacterConfig, ClientFactory
from tests.fakes import FakeClock, FakeLLM
from tests.test_world_setting import write_world

REPO_CHARACTERS = REPO_JOBS.parent
MONDAY = datetime(2026, 9, 20, 16, 0, tzinfo=UTC)
"""Monday 2026-09-21, 0:00 in Beijing: the week the tests' clocks start in."""
IDOLS = ["mano", "kogane", *(f"idol{n:02}" for n in range(3, 29))]
"""The fixture's 28 idols, in idol order."""


@pytest.fixture
def characters(characters: CharacterConfig) -> CharacterConfig:
    """Mano, Kogane and 26 more idols, and the office's clerk, with the world setting that
    tells her from them."""
    for n in range(3, 29):
        characters.add(f"idol{n:02}", f"偶像{n:02}", "# 人设", idol_id=n)
    characters.add("hazuki", "七草はづき", "# 人设", idol_id=91)
    write_world(characters, [
        ("櫻木真乃", "illumination STARS", "関根瞳"),
        ("月岡恋鐘", "L'Antica", "礒部花凜"),
        *((f"偶像{n:02}", "L'Antica", "cv") for n in range(3, 29)),
    ])
    return characters


async def schedule(client: httpx.AsyncClient, timezone: str | None = None) -> dict:
    res = await client.get(
        "/api/schedule", headers={"X-Timezone": timezone} if timezone else None
    )
    assert res.status_code == 200, res.text
    return res.json()


async def live_in(client: httpx.AsyncClient, timezone: str) -> None:
    res = await client.put("/api/profile", json={"timezone": timezone})
    assert res.status_code == 200, res.text


def whose(week: dict) -> set[str]:
    return {j["character_id"] for j in week["jobs"]}


async def test_a_week_is_drawn_as_first_read_seven_idols_the_same_for_everyone_and_kept(
    make_client: ClientFactory,
):
    clock = FakeClock(MONDAY + timedelta(days=4))
    client = make_client(FakeLLM(), clock=clock)
    friend = make_client(FakeLLM(), "friend", clock=clock)

    first = await schedule(client)
    theirs = await schedule(friend)
    again = await schedule(client)

    week = first["this_week"]
    assert first["enabled"] is True
    assert (week["id"], week["published"]) == ("2026-09-21", True)
    # This week and the two after it open together (`OPEN_WEEKS`, `.scratch/nsfw/`).
    assert [w["id"] for w in first["weeks"]] == ["2026-09-21", "2026-09-28", "2026-10-05"]
    assert [w["published"] for w in first["weeks"]] == [True, True, True]
    assert first["next_week"]["id"] == "2026-09-28"
    assert len(whose(week)) == 7 and "hazuki" not in whose(week)
    assert week["placements"] == []
    job = week["jobs"][0]
    listed = {j.name: j for j in load_job_list(REPO_JOBS)}[job["name"]]
    assert set(job) == {"id", "character_id", "name", "note", "category", "length", "slots"}
    assert (job["note"], job["category"], job["length"], job["slots"]) == (
        listed.note, listed.category, listed.length, listed.slots and list(listed.slots)
    )
    assert theirs["this_week"] == week and again["this_week"] == week


async def test_every_idol_has_her_week_once_in_four_running(make_client: ClientFactory):
    clock = FakeClock(MONDAY)
    client = make_client(FakeLLM(), clock=clock)
    weeks = 0
    while (date(2026, 9, 21) + timedelta(weeks=weeks) - FIRST_WEEK).days // 7 % 4:
        weeks += 1

    drawn = []
    for n in range(weeks, weeks + 4):
        clock.now = MONDAY + timedelta(weeks=n, hours=12)
        drawn.append(whose((await schedule(client))["this_week"]))

    assert Counter(c for week in drawn for c in week) == Counter(IDOLS)


async def test_a_changed_list_leaves_the_weeks_drawn_as_they_were_and_draws_the_next_from_it(
    make_client: ClientFactory, characters: CharacterConfig
):
    clock = FakeClock(MONDAY + timedelta(days=2))
    before = (await schedule(make_client(FakeLLM(), clock=clock)))["this_week"]
    characters.write(JOBS_FILE, "".join(
        f'[[jobs]]\nid = "new-{n}"\nname = "新{n}"\nnote = "说明"\n'
        f'category = "{"private" if n < 7 else "practice"}"\nlength = {1 + n % 2}\n'
        for n in range(40)
    ))
    client = make_client(FakeLLM(), clock=clock)

    this_week = (await schedule(client))["this_week"]
    clock.advance(days=7)
    ahead = (await schedule(client))["weeks"]

    assert this_week == before
    # A week drawn before the list changed keeps what it was drawn from; whatever is drawn
    # from now on comes from the new list (`OPEN_WEEKS`, `.scratch/nsfw/`).
    assert all(j["name"].startswith("新") for j in ahead[2]["jobs"])


async def test_west_of_beijing_the_three_weeks_open_from_this_weeks_monday_in_beijing(
    make_client: ClientFactory,
):
    clock = FakeClock(MONDAY + timedelta(days=7, minutes=-1))  # Sunday 23:59 in Beijing
    client = make_client(FakeLLM(), clock=clock)
    await live_in(client, "America/Los_Angeles")  # Sunday 08:59

    before = await schedule(client)
    clock.advance(minutes=1)
    after = await schedule(client)

    # The group this week opened on its own Monday, so the two after it are there already.
    assert before["this_week"]["id"] == "2026-09-21"
    assert [w["id"] for w in before["weeks"]] == ["2026-09-21", "2026-09-28", "2026-10-05"]
    assert [w["published"] for w in before["weeks"]] == [True, True, True]
    assert after["this_week"] == before["this_week"]
    assert after["next_week"]["id"] == "2026-09-28"
    assert after["next_week"]["published"] is True
    assert len(whose(after["next_week"])) == 7


async def test_east_of_beijing_their_monday_begins_before_their_week_is_published(
    make_client: ClientFactory,
):
    # Monday 0:30 in Auckland, still Sunday 19:30 in Beijing; the device's zone is overridden.
    client = make_client(FakeLLM(), clock=FakeClock(MONDAY + timedelta(days=7, hours=-4.5)))
    await live_in(client, "Pacific/Auckland")

    read = await schedule(client, "Asia/Shanghai")

    assert read["this_week"] == {
        "id": "2026-09-28", "published": False,
        "published_at": (MONDAY + timedelta(days=7)).isoformat(), "jobs": [], "placements": [],
    }
    assert read["next_week"] is None


async def test_the_devices_zone_is_theirs_without_one_in_their_profile(
    make_client: ClientFactory,
):
    client = make_client(FakeLLM(), clock=FakeClock(MONDAY + timedelta(days=7, hours=-4.5)))

    assert (await schedule(client, "Pacific/Auckland"))["this_week"]["published"] is False


def test_the_repositorys_list_gives_a_good_week_for_years_of_weeks():
    characters = load_characters(REPO_CHARACTERS / "characters.toml")
    idols = idols_of(characters, load_world(REPO_CHARACTERS / "world.json"))
    jobs = load_job_list(REPO_JOBS)

    for n in range(520):
        week = FIRST_WEEK + timedelta(weeks=n)
        drawn = draw_week(week, idols, jobs)
        by_idol: dict[str, list] = {}
        for character, job in drawn:
            by_idol.setdefault(character, []).append(job)
        assert len(by_idol) == 7, week
        assert "hazuki" not in by_idol, week
        assert all(2 <= len(js) <= 3 for js in by_idol.values()), week
        assert all(any(j.category in WORK for j in js) for js in by_idol.values()), week
        assert all(sum(j.category == "private" for j in js) <= 1 for js in by_idol.values()), week
        assert 24 <= sum(j.length for _, j in drawn) <= 27, week
        assert len({j.id for _, j in drawn}) == len(drawn), week
