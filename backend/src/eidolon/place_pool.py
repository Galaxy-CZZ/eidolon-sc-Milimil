"""The place pool (GLOSSARY.md「地点」), loaded from the configuration beside the characters'.

It is configuration, not data, as the job list is: the maintainer keeps it in the repository,
and neither `.env` nor the admin console changes it. Each place is a real one in Tokyo or
the outskirts a day trip goes to, with its Japanese name, where it is, its kind of place
(`category`), and a line in Chinese saying what it is. A holy site (a card's or a
background's location in the original) says where that was found (`source`) and whose it is
(`idols`); a place only right in some seasons or at some times of day says which. A venue is
one of the world setting's live venues, by the name its live days give it.

The jobs say which kinds of place they take her to (`check_job_places`), and each idol which
kinds she likes (`check_place_likes`). Anything wrong in any of it keeps the backend from
starting (`PlacePoolError`).
"""

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal, get_args

from eidolon.characters import Character
from eidolon.job_list import SLOTS, ListedJob, Slot

Category = Literal[
    "cafe", "park", "shrine", "shopping-street", "fashion-street", "books", "mall", "seaside",
    "amusement", "museum", "night-view", "bath", "seasonal", "venue",
]
"""咖啡馆·甜品·餐厅、公园·河边、神社·寺、商店街、杂货·服装街区、书店·图书馆、商场·车站大楼
（含电影院）、海边·湾岸、水族馆·动物园·游乐园、美术馆·博物馆·天象仪、展望台·夜景、温泉·钱汤、
季节名所、演出场馆."""

CATEGORIES: tuple[Category, ...] = get_args(Category)

INDOOR: frozenset[Category] = frozenset({"cafe", "books", "mall", "museum", "bath", "venue"})
"""The kinds of place under a roof, for a day of rain or snow. An aquarium or an observatory
counts as outdoors, though some are not: better a few fewer on a rainy day."""

Season = Literal["spring", "summer", "autumn", "winter"]
"""In Tokyo: 3–5 月春、6–8 月夏、9–11 月秋、12–2 月冬."""

SEASONS: tuple[Season, ...] = get_args(Season)

NEARBY = "nearby"
"""What a job going anywhere outside Tokyo-to names in its `places`, of any kind."""

NEARBY_PREFECTURES = ("神奈川県", "千葉県", "埼玉県")
"""The prefectures of the outskirts. A place outside Tokyo-to begins its `area` with one."""

PLACES_FILE = "places.toml"
"""The file's name, in the directory of the character configuration."""

_SOUTH, _NORTH, _WEST, _EAST = 35.1, 36.1, 138.9, 140.3
"""Tokyo-to without its islands, and the outskirts, roughly."""

_VALID_ID = re.compile(r"[a-z0-9_-]+")

_PREFECTURE = re.compile(r"北海道|\S{2,3}?[府県]")
"""A prefecture beginning an area: no ward, city, town or village of Tokyo-to's begins as one
does (府中市 has nothing before its 府)."""


class PlacePoolError(RuntimeError):
    """The place pool, or the kinds of place in the job list or the character configuration,
    is missing or broken."""


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    """In Japanese, as the map and the sign have it: what the moment shows."""
    area: str
    """The ward, city, town or village, the prefecture first outside Tokyo-to."""
    lat: float
    lon: float
    category: Category
    note: str
    """One line in Chinese saying what it is, for her to go by."""
    checked: date
    """When it was last seen to be there still."""
    idols: tuple[str, ...] = ()
    """Whose holy site it is, or whose character sheet names it, by character identifier."""
    source: str | None = None
    """For a holy site: the cards or backgrounds it is in, and where that was found."""
    seasons: tuple[Season, ...] | None = None
    """The seasons it is for; None for any."""
    slots: tuple[Slot, ...] | None = None
    """The slots it is for; None for any."""
    venues: tuple[str, ...] = ()
    """For a venue: the names its live days give it, where they are not `name`."""

    @property
    def nearby(self) -> bool:
        """Whether it is outside Tokyo-to, in the outskirts."""
        return self.area.startswith(NEARBY_PREFECTURES)

    @property
    def venue_names(self) -> tuple[str, ...]:
        """The names live days give it, if it is a venue."""
        if self.category != "venue":
            return ()
        return self.venues or (self.name,)


def places_path(characters_path: Path) -> Path:
    """Where the place pool is: beside the character configuration."""
    return characters_path.parent / PLACES_FILE


def load_place_pool(path: Path, characters: Mapping[str, Character]) -> list[Place]:
    """The places in the pool at `path`, in file order, whose `idols` are of `characters`.
    Raises PlacePoolError if it is missing or broken."""
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PlacePoolError(f"找不到地点池 {path}") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise PlacePoolError(f"地点池 {path} 格式有误：{e}") from None
    entries = config.get("places", [])
    if not isinstance(entries, list):
        raise PlacePoolError(f"地点池 {path} 里的 places 应当是 [[places]] 段")
    places: dict[str, Place] = {}
    for entry in entries:
        place = _parse_place(entry, characters)
        if place.id in places:
            raise PlacePoolError(f"地点标识 {place.id} 重复")
        places[place.id] = place
    return list(places.values())


def _parse_place(entry: object, characters: Mapping[str, Character]) -> Place:
    if not isinstance(entry, dict):
        raise PlacePoolError(f"地点池里的 {entry!r} 应当是一个 [[places]] 段")
    label = entry.get("id", "（没有标识）")
    required = ("id", "name", "area", "lat", "lon", "category", "note", "checked")
    if missing := [f for f in required if f not in entry]:
        raise PlacePoolError(f"地点 {label} 缺少 {'、'.join(missing)}")
    id, category, area = entry["id"], entry["category"], entry["area"]
    if not isinstance(id, str) or not _VALID_ID.fullmatch(id):
        raise PlacePoolError(f"地点标识 {id} 只能用小写字母、数字、- 和 _")
    for field in ("name", "area", "note"):
        _one_line(entry[field], f"地点 {id} 的 {field}")
    if category not in CATEGORIES:
        raise PlacePoolError(f"地点 {id} 的类别 {category} 不在 {'、'.join(CATEGORIES)} 之中")
    if (prefecture := _PREFECTURE.match(area)) and prefecture[0] not in NEARBY_PREFECTURES:
        raise PlacePoolError(
            f"地点 {id} 的 area {area} 在 {prefecture[0]}，"
            f"不在东京都或 {'、'.join(NEARBY_PREFECTURES)}"
        )
    lat, lon = entry["lat"], entry["lon"]
    if type(lat) not in (int, float) or not _SOUTH <= lat <= _NORTH:
        raise PlacePoolError(f"地点 {id} 的纬度 lat {lat!r} 不在东京和近郊（{_SOUTH}–{_NORTH}）")
    if type(lon) not in (int, float) or not _WEST <= lon <= _EAST:
        raise PlacePoolError(f"地点 {id} 的经度 lon {lon!r} 不在东京和近郊（{_WEST}–{_EAST}）")
    checked = entry["checked"]
    # A TOML date; a date and time is a datetime, which is a date too.
    if not isinstance(checked, date) or isinstance(checked, datetime):
        raise PlacePoolError(f"地点 {id} 的 checked 应当是日期（如 2026-10-31），而不是 {checked!r}")
    idols = _strings(entry, "idols", id)
    if unknown := [i for i in idols if i not in characters]:
        raise PlacePoolError(f"地点 {id} 的 idols 里的 {'、'.join(unknown)} 不是角色")
    source = entry.get("source")
    if source is not None:
        _one_line(source, f"地点 {id} 的 source")
    seasons = _choices_in(entry, "seasons", SEASONS, id)
    slots = _choices_in(entry, "slots", SLOTS, id)
    venues = _strings(entry, "venues", id)
    if venues and category != "venue":
        raise PlacePoolError(f"地点 {id} 不是演出场馆（venue），不能写 venues")
    return Place(
        id, entry["name"], area, float(lat), float(lon), category, entry["note"], checked,
        idols, source,
        None if seasons is None else tuple(s for s in SEASONS if s in seasons),
        None if slots is None else tuple(s for s in SLOTS if s in slots),
        venues,
    )


def _one_line(value: object, what: str) -> None:
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n"):
        raise PlacePoolError(f"{what} 应当是一行文字")


def _strings(entry: dict, field: str, id: str) -> tuple[str, ...]:
    names = entry.get(field, [])
    if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
        raise PlacePoolError(f"地点 {id} 的 {field} 应当是字符串的列表")
    return tuple(names)


def _choices_in(entry: dict, field: str, choices: tuple[str, ...], id: str) -> list[str] | None:
    """Some of `choices` in `field`, if it is there."""
    listed = entry.get(field)
    if listed is None:
        return None
    if not isinstance(listed, list) or not listed or any(v not in choices for v in listed):
        raise PlacePoolError(
            f"地点 {id} 的 {field} {listed!r} 应当是 {'、'.join(choices)} 里几项的列表"
        )
    return listed


MIN_LIKES, MAX_LIKES = 2, 4
"""How many kinds of place an idol likes."""

_CHOOSABLE = tuple(c for c in CATEGORIES if c != "venue")


def check_job_places(jobs: Iterable[ListedJob]) -> None:
    """Raises PlacePoolError unless every job's `places`, if it has them, are kinds of place
    there are, or the outskirts, none twice. A venue is no job's: venues are for the days of
    her lives."""
    for job in jobs:
        if job.places is None:
            continue
        _check_kinds(f"工作 {job.id} 的 places", job.places, (*_CHOOSABLE, NEARBY), 1, None)


def check_place_likes(characters: Mapping[str, Character]) -> None:
    """Raises PlacePoolError unless every character's `place_likes`, if she has them, are
    `MIN_LIKES` to `MAX_LIKES` kinds of place there are, none twice, and no venue."""
    for c in characters.values():
        if c.place_likes is not None:
            _check_kinds(f"角色 {c.id} 的 place_likes", c.place_likes, _CHOOSABLE, MIN_LIKES, MAX_LIKES)


def _check_kinds(
    what: str, kinds: tuple[str, ...], choices: tuple[str, ...], least: int, most: int | None
) -> None:
    if unknown := [k for k in kinds if k not in choices]:
        raise PlacePoolError(f"{what} 里的 {'、'.join(unknown)} 不在 {'、'.join(choices)} 之中")
    if len(set(kinds)) < len(kinds):
        raise PlacePoolError(f"{what} 里有重复的类别")
    if len(kinds) < least or (most is not None and len(kinds) > most):
        many = f"{least}–{most}" if most is not None else f"至少 {least}"
        raise PlacePoolError(f"{what} 有 {len(kinds)} 个类别，应当{many}个")
