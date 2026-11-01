"""The weather, from Open-Meteo, which wants no key: Tokyo's as a moment is posted
(GLOSSARY.md「动态」), the hourly WMO weather code and temperature at one spot in Tokyo, where its
model is the JMA's MSM (`Weathers.at`); and the day's, Tokyo's or where the producer is, as
she talks (GLOSSARY.md「此刻」): the weather now, whether it rains or snows later in the day,
and the day's highest and lowest beside yesterday's (`Weathers.today`). Should Open-Meteo be
gone for good, MET Norway's Locationforecast is the one to turn to.

Fetched as the price catalogs are (`price_catalog`): direct, never through the proxy, not a
service the status page or activity records know of. For a moment, each fetch asks for
`AHEAD` hours from the one wanted, and each hour is kept in memory, by the grid cell and the
hour, for `KEPT`; for her day, each fetch asks for yesterday, today and tomorrow where the
spot is, kept by the grid cell for `KEPT`, waited on no longer than the caller says, the
fetch going on to be kept all the same. One failing, none is asked for again for
`RETRY_AFTER` (of the same cell, for a day), nor in the first `PEAK` of an hour, when
Open-Meteo drops what it cannot take: the weather is then none, as it is for a code not of
the seven kinds (`KINDS`)."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, get_args

import httpx

from eidolon.clock import Clock

log = logging.getLogger(__name__)

URL = "https://api.open-meteo.com/v1/forecast"

TOKYO_AT = (35.6895, 139.6917)
"""Where in Tokyo the weather is of: the Metropolitan Government Building, in WGS-84."""

SWING = 8
"""How many degrees today's highest or lowest is to be off yesterday's for the day to stand
out: as a cold wave is commonly reckoned."""

KEPT = timedelta(hours=3)
"""How long an hour fetched is kept: MSM is run again every three hours."""

RETRY_AFTER = timedelta(minutes=10)
"""How long after a fetch fails none is tried again."""

PEAK = timedelta(minutes=2)
"""How long into each hour none is fetched."""

AHEAD = 12
"""How many hours after the one wanted each fetch asks for besides."""

Kind = Literal["clear", "cloudy", "overcast", "fog", "rain", "snow", "thunder"]

ALL_KINDS: frozenset[str] = frozenset(get_args(Kind))

KINDS: tuple[tuple[range, Kind], ...] = (
    (range(0, 2), "clear"),
    (range(2, 3), "cloudy"),
    (range(3, 4), "overcast"),
    (range(45, 46), "fog"),
    (range(48, 49), "fog"),
    (range(51, 68), "rain"),
    (range(80, 83), "rain"),
    (range(71, 78), "snow"),
    (range(85, 87), "snow"),
    (range(95, 100), "thunder"),
)
"""The kinds of weather, each by the WMO codes it is."""

WET: frozenset[Kind] = frozenset({"rain", "snow", "thunder"})

NAMES: dict[Kind, str] = {
    "clear": "晴", "cloudy": "多云", "overcast": "阴", "fog": "雾", "rain": "雨", "snow": "雪",
    "thunder": "雷雨",
}
"""How she is told each kind."""


@dataclass(frozen=True)
class Weather:
    """One of the kinds, and the temperature in whole degrees Celsius."""

    kind: Kind
    temperature: int

    @property
    def wet(self) -> bool:
        """Whether it rains, snows or thunders: no day to be out of doors."""
        return self.kind in WET

    def shown(self) -> dict:
        return {"kind": self.kind, "temperature": self.temperature}


@dataclass(frozen=True)
class Spot:
    """Where a day's weather is of, in WGS-84, kept by its grid cell (`cell`); `model` is the
    one Open-Meteo is to answer with, None for its best."""

    latitude: float
    longitude: float
    model: str | None = None

    @property
    def cell(self) -> tuple[float, float]:
        return (round(self.latitude, 2), round(self.longitude, 2))


TOKYO = Spot(*TOKYO_AT, model="jma_msm")
"""Tokyo, its day's weather as MSM has it, as its moments have it."""

Later = Literal["rain", "snow"]


@dataclass(frozen=True)
class Today:
    """A day's weather where a spot is, as of an hour in it: the weather `now`; whether it
    rains or snows `later`, in the hours left of the day (snow if both, thunder as rain; None
    if neither); the day's `high` and `low`, and yesterday's (None if unknown), in whole
    degrees Celsius."""

    now: Weather
    later: Later | None
    high: int
    low: int
    yesterday_high: int | None = None
    yesterday_low: int | None = None

    @property
    def high_change(self) -> int | None:
        return None if self.yesterday_high is None else self.high - self.yesterday_high

    @property
    def low_change(self) -> int | None:
        return None if self.yesterday_low is None else self.low - self.yesterday_low

    @property
    def stands_out(self) -> bool:
        """Whether it is a day to bring up: it rains, snows or thunders now, or rains or
        snows later, or the day's highest or lowest is `SWING` degrees or more off
        yesterday's."""
        changes = (c for c in (self.high_change, self.low_change) if c is not None)
        return self.now.wet or self.later is not None or any(abs(c) >= SWING for c in changes)


@dataclass(frozen=True)
class _Forecast:
    """What a fetch for a day's weather answered: the hours (as the start of each), their
    codes and temperatures; the days where the spot is (as the start of each), their highest
    and lowest."""

    hours: list[int]
    codes: list[object]
    temperatures: list[object]
    days: list[int]
    highs: list[object]
    lows: list[object]

    def today(self, now: datetime) -> Today | None:
        at = now.timestamp()
        day = next(
            (i for i, start in enumerate(self.days) if start <= at < self._day_end(i)), None
        )
        hour = next((i for i, start in enumerate(self.hours) if start <= at < start + 3600), None)
        if day is None or hour is None:
            return None
        weather = _weather(self.codes[hour], self.temperatures[hour])
        high, low = self.highs[day], self.lows[day]
        if weather is None or not isinstance(high, int | float) or not isinstance(low, int | float):
            return None
        later = {
            kind for i, start in enumerate(self.hours)
            if self.hours[hour] < start < self._day_end(day)
            and (kind := _kind(self.codes[i])) in WET
        }
        return Today(
            weather,
            "snow" if "snow" in later else "rain" if later else None,
            round(high), round(low),
            _whole(self.highs[day - 1]) if day > 0 else None,
            _whole(self.lows[day - 1]) if day > 0 else None,
        )

    def _day_end(self, day: int) -> float:
        return self.days[day + 1] if day + 1 < len(self.days) else self.days[day] + 86400


def _whole(degrees: object) -> int | None:
    return round(degrees) if isinstance(degrees, int | float) else None


@dataclass(frozen=True)
class _KeptDay:
    """A spot's days as fetched, and when."""

    forecast: _Forecast
    fetched_at: datetime


@dataclass(frozen=True)
class _Kept:
    """An hour's weather as fetched (None for none to be had), and when it was."""

    weather: Weather | None
    fetched_at: datetime


def weather_line(weather: Weather) -> str:
    """The line of now telling her the weather."""
    return f"东京这会儿的天气：{NAMES[weather.kind]}，{weather.temperature}°C。"


def _kind(code: object) -> Kind | None:
    if not isinstance(code, int):
        return None
    return next((kind for codes, kind in KINDS if code in codes), None)


def _weather(code: object, temperature: object) -> Weather | None:
    kind = _kind(code)
    if kind is None or not isinstance(temperature, int | float):
        return None
    return Weather(kind, round(temperature))


class Weathers:
    """The weather, Tokyo's for moments and any spot's for her day, fetched over `transport`
    (Open-Meteo's own by default), kept by `clock`."""

    def __init__(self, clock: Clock, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._clock = clock
        self._http = httpx.AsyncClient(
            transport=transport, timeout=10, headers={"User-Agent": "eidolon-sc"},
            trust_env=False,
        )
        self._cell = TOKYO.cell
        self._kept: dict[tuple[tuple[float, float], datetime], _Kept] = {}
        self._failed_at: datetime | None = None
        self._days: dict[tuple[float, float], _KeptDay] = {}
        self._days_failed: dict[tuple[float, float], datetime] = {}
        self._fetching: dict[tuple[float, float], asyncio.Task[_Forecast | None]] = {}

    async def today(self, spot: Spot, wait: float) -> Today | None:
        """The day's weather at `spot`, as of now: as kept, or fetched now, waited on for no
        longer than `wait` seconds; None if it cannot be had by then."""
        now = self._clock()
        kept = self._days.get(spot.cell)
        if kept is not None and now - kept.fetched_at < KEPT:
            return kept.forecast.today(now)
        failed_at = self._days_failed.get(spot.cell)
        into = now - now.replace(minute=0, second=0, microsecond=0)
        if into < PEAK or (failed_at is not None and now - failed_at < RETRY_AFTER):
            return None
        fetching = self._fetching.get(spot.cell)
        if fetching is None:
            fetching = asyncio.create_task(self._fetch_day(spot))
            self._fetching[spot.cell] = fetching
        done, _ = await asyncio.wait({fetching}, timeout=wait)
        forecast = fetching.result() if done else None
        return forecast.today(self._clock()) if forecast is not None else None

    async def _fetch_day(self, spot: Spot) -> _Forecast | None:
        try:
            params: dict[str, str | float | int] = {
                "latitude": spot.latitude, "longitude": spot.longitude,
                "hourly": "weather_code,temperature_2m",
                "daily": "temperature_2m_max,temperature_2m_min",
                "past_days": 1, "forecast_days": 2, "timezone": "auto", "timeformat": "unixtime",
            }
            if spot.model is not None:
                params["models"] = spot.model
            response = await self._http.get(URL, params=params)
            response.raise_for_status()
            answer = response.json()
            hourly, daily = answer["hourly"], answer["daily"]
            forecast = _Forecast(
                list(hourly["time"]), list(hourly["weather_code"]),
                list(hourly["temperature_2m"]), list(daily["time"]),
                list(daily["temperature_2m_max"]), list(daily["temperature_2m_min"]),
            )
            if not (
                len(forecast.hours) == len(forecast.codes) == len(forecast.temperatures)
                and len(forecast.days) == len(forecast.highs) == len(forecast.lows)
            ):
                raise ValueError("lengths differ")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            log.warning("could not fetch the day's weather: %s", type(e).__name__)
            self._days_failed[spot.cell] = self._clock()
            return None
        finally:
            self._fetching.pop(spot.cell, None)
        now = self._clock()
        self._days = {k: v for k, v in self._days.items() if now - v.fetched_at < KEPT}
        self._days[spot.cell] = _KeptDay(forecast, now)
        return forecast

    async def at(self, when: datetime) -> Weather | None:
        """The weather in the hour of `when`: as kept, or fetched now; None if it cannot be."""
        hour = when.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        now = self._clock()
        kept = self._kept.get((self._cell, hour))
        if kept is not None and now - kept.fetched_at < KEPT:
            return kept.weather
        into = now - now.replace(minute=0, second=0, microsecond=0)
        if into < PEAK or (self._failed_at is not None and now - self._failed_at < RETRY_AFTER):
            return None
        try:
            hours = await self._fetch(hour)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            log.warning("could not fetch the weather: %s", type(e).__name__)
            self._failed_at = now
            return None
        self._kept = {k: v for k, v in self._kept.items() if now - v.fetched_at < KEPT}
        hours.setdefault(hour, None)  # not in the answer: none to be had, not asked again
        for at, weather in hours.items():
            self._kept[(self._cell, at)] = _Kept(weather, now)
        return hours[hour]

    async def _fetch(self, hour: datetime) -> dict[datetime, Weather | None]:
        response = await self._http.get(URL, params={
            "latitude": TOKYO_AT[0], "longitude": TOKYO_AT[1],
            "hourly": "weather_code,temperature_2m", "models": "jma_msm",
            "timeformat": "unixtime",
            "start_hour": f"{hour:%Y-%m-%dT%H:%M}",
            "end_hour": f"{hour + timedelta(hours=AHEAD):%Y-%m-%dT%H:%M}",
        })
        response.raise_for_status()
        hourly = response.json()["hourly"]
        return {
            datetime.fromtimestamp(at, UTC): _weather(code, temperature)
            for at, code, temperature in zip(
                hourly["time"], hourly["weather_code"], hourly["temperature_2m"], strict=True
            )
        }

    async def aclose(self) -> None:
        for fetching in list(self._fetching.values()):
            fetching.cancel()
        await self._http.aclose()
