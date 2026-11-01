"""The weather she knows of as she talks (GLOSSARY.md「此刻」): typing, in a call or reaching out,
Tokyo's, where she is, and, where the producer has a city in their profile and the deployer a
QWeather account, the producer's: the weather now, whether it rains or snows later in the day,
the day's highest and lowest beside yesterday's (`weather.Today`), and there the weather
warnings in force (`qweather`). What cannot be had in `WAIT` she is not told, nor is she told
it is missing.

She is always told it, so that she can answer if asked; she may bring it up herself only if
they have not been in touch for `LONG_APART` (in a call, until it connected), or the day stands
out where either of them is (`weather.Today.stands_out`), or a warning is in force where the
producer is, and then only once in the conversation; Tokyo's and the producer's each on its own,
so that a day that stands out on one side frees her to bring up that side's alone. Where the
producer is in Tokyo too (within `SAME_PLACE`), Tokyo's weather is told once, as both of
theirs."""

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from eidolon.producer import City
from eidolon.qweather import QWeather
from eidolon.weather import NAMES, SWING, TOKYO, Spot, Today, Weathers

WAIT = 1.5
"""How long a turn waits on the weather it does not have yet, in seconds."""

LONG_APART = timedelta(hours=3)
"""How long out of touch has her free to bring up the weather."""

SAME_PLACE = 30.0
"""How near Tokyo, in kilometres, the producer's city is to be Tokyo's weather too."""

MAY_BRING_UP = (
    "天气可以当个话头：这段对话里还没聊过天气的话，可以在合适的时候自然地提一次，"
    "比如关心一句；已经聊过就不要再提。"
)
KEEP_IN_MIND = "天气只是让你心里有数：制作人问起时可以说，平时不要主动提。"


def may_bring_up_only(free: str, kept: str) -> str:
    """She may bring up the weather on the `free` side only, not on the `kept` one."""
    return (
        f"{free}的天气可以当个话头：这段对话里还没聊过天气的话，可以在合适的时候自然地提一次，"
        f"比如关心一句；已经聊过就不要再提。{kept}的天气只是让你心里有数，制作人问起时可以说，平时不要主动提。"
    )


TOKYO_SIDE = "东京"
THERE_SIDE = "制作人那边"
_LATER = {"rain": "今天晚些时候还会下雨", "snow": "今天晚些时候还会下雪"}


@dataclass(frozen=True)
class KnownWeather:
    """The weather she knows of: Tokyo's day (None if unknown); the producer's city (None
    without one, or without the deployer's account), and its day (None if unknown) and the
    warnings in force there; whether the producer is in Tokyo too; whether she may bring up
    Tokyo's herself, and the producer's (both of theirs in Tokyo's, in Tokyo too)."""

    tokyo: Today | None
    city: City | None
    there: Today | None
    warnings: tuple[str, ...]
    same_place: bool
    tokyo_free: bool
    there_free: bool


class HerWeather:
    """The weather from `weathers`, the producer's city found on `qweather` (None without)."""

    def __init__(self, weathers: Weathers, qweather: QWeather | None = None) -> None:
        self._weathers = weathers
        self._qweather = qweather

    async def known(
        self, city: City | None, now: datetime, last_apart: datetime | None
    ) -> KnownWeather:
        """What she knows of the weather at `now`, the producer in `city` (None for nowhere
        set), they last in touch at `last_apart` (None if never), waiting no longer than
        `WAIT` on what is not kept."""
        if self._qweather is None or not self._qweather.on:
            city = None
        same = city is not None and _km(city.spot, TOKYO) <= SAME_PLACE
        there = city if city is not None and not same else None
        tokyo, there_day, warnings = await asyncio.gather(
            self._weathers.today(TOKYO, WAIT),
            self._weathers.today(there.spot, WAIT) if there else _none(),
            self._qweather.warnings(city.spot, WAIT) if city and self._qweather else _none(),
        )
        warnings = warnings or ()
        apart = last_apart is None or now - last_apart >= LONG_APART
        tokyo_free = tokyo is not None and (
            apart or tokyo.stands_out or (same and bool(warnings))
        )
        there_free = (there_day is not None or bool(warnings)) and not same and (
            apart or bool(warnings) or (there_day is not None and there_day.stands_out)
        )
        return KnownWeather(tokyo, city, there_day, warnings, same, tokyo_free, there_free)


async def _none() -> None:
    return None


def weather_lines(known: KnownWeather) -> list[str]:
    """The lines of now telling her where the producer is, if she knows, then the weather,
    and whether she may bring it up; nothing of the weather if she knows none."""
    whereabouts = [city_line(known.city)] if known.city is not None else []
    lines: list[str] = []
    if known.tokyo is not None:
        where = "你和制作人都在东京一带，东京" if known.same_place else "东京（你这边）"
        lines.append(f"{where}这会儿：{_day(known.tokyo)}")
    if known.city is not None and known.there is not None:
        lines.append(f"制作人那边（{known.city.name}）这会儿：{_day(known.there)}")
    if known.warnings:
        lines.append(f"制作人那边正生效的气象预警：{'；'.join(known.warnings)}。")
    if not lines:
        return whereabouts
    return [*whereabouts, *lines, _bring_up(known)]


def _bring_up(known: KnownWeather) -> str:
    """Whether she may bring up the weather herself, of either side she knows of."""
    there_known = not known.same_place and (known.there is not None or bool(known.warnings))
    sides = [
        (TOKYO_SIDE, known.tokyo_free) if known.tokyo is not None else None,
        (THERE_SIDE, known.there_free) if there_known else None,
    ]
    free = [name for name, on in filter(None, sides) if on]
    kept = [name for name, on in filter(None, sides) if not on]
    if not free:
        return KEEP_IN_MIND
    if not kept:
        return MAY_BRING_UP
    return may_bring_up_only(free[0], kept[0])


def city_line(city: City) -> str:
    """The line telling her where the producer is."""
    return (
        f"制作人在{city.told}，这是制作人自己在档案里填的；记忆里如果有不一样的说法，以这里为准。"
        "被问起时可以回答，平时不要主动提起。"
    )


def _day(today: Today) -> str:
    said = f"{NAMES[today.now.kind]}，{today.now.temperature}°C；今天 {today.low}～{today.high}°C"
    if today.later is not None:
        said += f"，{_LATER[today.later]}"
    if (change := _change(today)) is not None:
        said += f"，{change}"
    return said + "。"


def _change(today: Today) -> str | None:
    """How much colder or warmer than yesterday, if by `weather.SWING` or more."""
    found = [
        (name, c) for name, c in (("最高", today.high_change), ("最低", today.low_change))
        if c is not None and abs(c) >= SWING
    ]
    if not found:
        return None
    name, c = max(found, key=lambda f: abs(f[1]))
    return f"比昨天{'冷' if c < 0 else '热'}了不少（{name}气温{'低' if c < 0 else '高'}了 {abs(c)}°C）"


def _km(a: Spot, b: Spot) -> float:
    """How far apart the two spots are, in kilometres, near enough."""
    dy = (a.latitude - b.latitude) * 111.2
    dx = (a.longitude - b.longitude) * 111.2 * math.cos(math.radians(b.latitude))
    return math.hypot(dx, dy)
