"""The weather in moments (GLOSSARY.md「朋友圈」「动态」): Tokyo's, from Open-Meteo, as the moment
is posted. She is told it, the moment keeps it, and the timeline shows it as one of seven,
with a whole temperature; in rain, snow or thunder she is given only places under a roof.
Without it (the service failing, a code not of the seven), she is told none, the moment shows
none, and is posted all the same.

Moments are driven as `test_moments.py` drives them, Open-Meteo stood in for over its
transport (`FakeWeather`); the fetching and keeping of the weather on a clock of its own."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from eidolon.config import Settings
from eidolon.place_pool import PLACES_FILE
from eidolon.weather import Kind, Weather, Weathers
from tests.conftest import KOGANE_SHEET, MANO_SHEET, CharacterConfig, ClientFactory
from tests.fakes import FakeClock, FakeLLM, FakeWeather, context_of
from tests.test_admin_users import ADMIN
from tests.test_moment_places import AT_THE_PARK, CAFE, PARK
from tests.test_moments import FACTS, SEVEN, START, talked, tick, timeline

AFTER_SEVEN = SEVEN + timedelta(minutes=10)
"""07:10 in Tokyo: the moment due at seven posted, not at the top of the hour."""


@pytest.fixture
def characters(tmp_path: Path) -> CharacterConfig:
    """Mano and Kogane, as `test_moments.py` has them, beside a pool of a park and a cafe."""
    config = (
        CharacterConfig(tmp_path / "characters")
        .add("mano", "櫻木真乃", MANO_SHEET, birthday="04-25", facts=FACTS)
        .add("kogane", "月岡恋鐘", KOGANE_SHEET, birthday="02-25")
    )
    config.write(PLACES_FILE, PARK + "\n" + CAFE)
    return config


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, moments=True, admins=frozenset({ADMIN}))


async def test_she_is_told_tokyos_weather_and_the_moment_shows_it(
    make_client: ClientFactory, settings: Settings
):
    weather = FakeWeather(code=2, temperature=18.6)
    client, llm, clock, _ = await talked(
        make_client, AT_THE_PARK, weather_transport=weather.transport()
    )

    await tick(client, clock, START)
    await tick(client, clock, AFTER_SEVEN)

    [moment] = await timeline(client)
    assert moment["weather"] == {"kind": "cloudy", "temperature": 19}
    told = context_of(llm.prompts[-1])
    assert "东京这会儿的天气：多云，19°C。" in told
    assert told.index("东京这会儿的天气") < told.index("# 地点候选")
    assert "inokashira：" in told and "kissa：" in told  # dry: outdoors too
    [asked] = weather.hours_asked()
    assert (asked["latitude"], asked["longitude"]) == ("35.6895", "139.6917")
    assert asked["models"] == "jma_msm"
    assert asked["start_hour"] == "2026-10-18T22:00"


async def test_in_rain_snow_or_thunder_she_is_given_only_places_under_a_roof(
    make_client: ClientFactory, settings: Settings
):
    client, llm, clock, _ = await talked(
        make_client, AT_THE_PARK, weather_transport=FakeWeather(code=61).transport()
    )

    await tick(client, clock, START)
    await tick(client, clock, AFTER_SEVEN)

    told = context_of(llm.prompts[-1])
    assert "kissa：" in told and "inokashira：" not in told
    [moment] = await timeline(client)
    assert moment["place"] is None  # the park she chose was not given


@pytest.mark.parametrize(
    "weather", [FakeWeather(failing=True), FakeWeather(code=None)]
)
async def test_without_the_weather_she_is_told_none_and_the_moment_shows_none_but_is_posted(
    make_client: ClientFactory, settings: Settings, weather: FakeWeather
):
    client, llm, clock, _ = await talked(
        make_client, AT_THE_PARK, weather_transport=weather.transport()
    )

    await tick(client, clock, START)
    await tick(client, clock, AFTER_SEVEN)

    [moment] = await timeline(client)
    assert moment["weather"] is None and moment["ja"]
    told = context_of(llm.prompts[-1])
    assert "天气" not in told


async def test_the_moment_keeps_the_weather_it_was_posted_in(
    make_client: ClientFactory, settings: Settings
):
    weather = FakeWeather(code=0, temperature=12.4)
    client, _, clock, _ = await talked(
        make_client, AT_THE_PARK, weather_transport=weather.transport()
    )
    await tick(client, clock, START)
    await tick(client, clock, AFTER_SEVEN)

    weather.code, weather.temperature = 71, -1.6
    again = make_client(FakeLLM(), clock=clock, weather_transport=weather.transport())

    [moment] = await timeline(again)
    assert moment["weather"] == {"kind": "clear", "temperature": 12}


NOON = datetime(2026, 10, 31, 3, 20, tzinfo=UTC)
"""12:20 in Tokyo."""


@pytest.mark.parametrize(
    ("codes", "kind"),
    [((0, 1), "clear"), ((2,), "cloudy"), ((3,), "overcast"), ((45, 48), "fog"),
     ((51, 55, 61, 67, 80, 82), "rain"), ((71, 77, 85, 86), "snow"), ((95, 96, 99), "thunder")],
)
async def test_the_codes_are_told_as_seven_kinds_rain_snow_and_thunder_wet(
    codes: tuple[int, ...], kind: Kind
):
    for code in codes:
        weathers = Weathers(FakeClock(NOON), FakeWeather(code=code, temperature=-0.5).transport())
        try:
            found = await weathers.at(NOON)
        finally:
            await weathers.aclose()
        assert found is not None and found == Weather(kind, 0), code
        assert found.wet == (kind in ("rain", "snow", "thunder"))


@pytest.mark.parametrize("code", [4, None])
async def test_a_code_not_of_the_seven_or_none_is_no_weather(code: int | None):
    weathers = Weathers(FakeClock(NOON), FakeWeather(code=code).transport())
    try:
        assert await weathers.at(NOON) is None
    finally:
        await weathers.aclose()


async def test_an_hour_fetched_is_kept_three_hours_and_after_failing_none_is_asked_for_ten_minutes():
    clock = FakeClock(NOON)
    weather = FakeWeather(code=3, temperature=20)
    weathers = Weathers(clock, weather.transport())
    try:
        assert await weathers.at(NOON) == Weather("overcast", 20)
        clock.advance(hours=2, minutes=50)
        assert await weathers.at(clock()) == Weather("overcast", 20)  # 15:10, fetched with noon's
        assert await weathers.at(NOON) == Weather("overcast", 20)
        assert len(weather.requests) == 1

        clock.advance(minutes=20)  # 15:30: noon's fetch is over three hours old
        weather.failing = True
        assert await weathers.at(clock()) is None
        clock.advance(minutes=9)
        assert await weathers.at(clock()) is None
        assert len(weather.requests) == 2

        weather.failing = False
        clock.advance(minutes=1)
        assert await weathers.at(clock()) == Weather("overcast", 20)
        assert len(weather.requests) == 3
    finally:
        await weathers.aclose()


async def test_none_is_asked_for_at_the_top_of_the_hour():
    top = NOON.replace(minute=0, second=30)
    clock = FakeClock(top)
    weather = FakeWeather()
    weathers = Weathers(clock, weather.transport())
    try:
        assert await weathers.at(top) is None
        assert weather.requests == []
        clock.advance(minutes=2)
        assert await weathers.at(top) == Weather("clear", 18)
    finally:
        await weathers.aclose()
