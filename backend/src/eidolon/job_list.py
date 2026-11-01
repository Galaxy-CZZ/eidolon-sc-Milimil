"""The job list (GLOSSARY.md「工作」), loaded from the configuration beside the characters'.

It is configuration, not data, as the gift catalog is: the maintainer keeps it in the
repository, and neither `.env` nor the admin console changes it. Each job has its
identifier, its name and a line saying what it is (both shown on the calendar, and what she
goes by), its category, how many slots it takes (`length`), which slots it may be in, if
not any, and the kinds of place it takes her to, if any (checked against the place pool's by
`place_pool.check_job_places`). A job of a whole day may only start in the morning, so it may
name no slots.
Each week's jobs are drawn from it (`schedule`) and kept as they were then, so changing it
changes only the weeks not yet published.

Anything wrong in it keeps the backend from starting (`JobListError`).
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

Category = Literal["practice", "appearance", "business", "private"]
"""练习、出镜、事务、私人: the first three are work."""

Slot = Literal["morning", "afternoon", "evening"]
"""上午 6–12、下午 12–18、晚上 18–24, in the order of the day."""

SLOTS: tuple[Slot, ...] = get_args(Slot)

WORK: frozenset[Category] = frozenset({"practice", "appearance", "business"})
"""The categories that are work, not private."""

JOBS_FILE = "jobs.toml"
"""The file's name, in the directory of the character configuration."""

_VALID_ID = re.compile(r"[a-z0-9_-]+")


class JobListError(RuntimeError):
    """The job list is missing or broken."""


@dataclass(frozen=True)
class ListedJob:
    id: str
    name: str
    note: str
    """One line saying what it is."""
    category: Category
    length: int
    """How many slots in a row it takes, 1 to 3."""
    slots: tuple[Slot, ...] | None = None
    """The slots it may be in; None for any."""
    places: tuple[str, ...] | None = None
    """The kinds of place it takes her to (`place_pool.Category`), or `nearby` for anywhere
    in the outskirts; None for none to name in her moment."""


def jobs_path(characters_path: Path) -> Path:
    """Where the job list is: beside the character configuration."""
    return characters_path.parent / JOBS_FILE


def load_job_list(path: Path) -> list[ListedJob]:
    """The jobs in the list at `path`, in file order. Raises JobListError if it is missing or
    broken."""
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise JobListError(f"找不到工作清单 {path}") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise JobListError(f"工作清单 {path} 格式有误：{e}") from None
    entries = config.get("jobs", [])
    if not isinstance(entries, list):
        raise JobListError(f"工作清单 {path} 里的 jobs 应当是 [[jobs]] 段")
    jobs: dict[str, ListedJob] = {}
    for entry in entries:
        job = _parse_job(entry)
        if job.id in jobs:
            raise JobListError(f"工作标识 {job.id} 重复")
        jobs[job.id] = job
    return list(jobs.values())


def _parse_job(entry: object) -> ListedJob:
    if not isinstance(entry, dict):
        raise JobListError(f"工作清单里的 {entry!r} 应当是一个 [[jobs]] 段")
    label = entry.get("id", "（没有标识）")
    missing = [f for f in ("id", "name", "note", "category", "length") if f not in entry]
    if missing:
        raise JobListError(f"工作 {label} 缺少 {'、'.join(missing)}")
    id, category, length = entry["id"], entry["category"], entry["length"]
    if not isinstance(id, str) or not _VALID_ID.fullmatch(id):
        raise JobListError(f"工作标识 {id} 只能用小写字母、数字、- 和 _")
    for field in ("name", "note"):
        value = entry[field]
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n"):
            raise JobListError(f"工作 {id} 的 {field} 应当是一行文字")
    if category not in get_args(Category):
        raise JobListError(f"工作 {id} 的类别 {category} 不在 {'、'.join(get_args(Category))} 之中")
    if type(length) is not int or not 1 <= length <= len(SLOTS):
        raise JobListError(f"工作 {id} 的 length 应当是 1、2 或 3，而不是 {length!r}")
    listed = entry.get("slots")
    slots: tuple[Slot, ...] | None = None
    if listed is not None:
        if not isinstance(listed, list) or not listed or any(s not in SLOTS for s in listed):
            raise JobListError(f"工作 {id} 的 slots {listed!r} 应当是 {'、'.join(SLOTS)} 里几项的列表")
        if length == len(SLOTS):
            raise JobListError(f"工作 {id} 占一整天，只能从上午排，不能再限定时段")
        slots = tuple(s for s in SLOTS if s in listed)
    places = entry.get("places")
    if places is not None and (
        not isinstance(places, list) or not all(isinstance(p, str) for p in places)
    ):
        raise JobListError(f"工作 {id} 的 places 应当是地点类别的列表")
    return ListedJob(
        id, entry["name"], entry["note"], category, length, slots,
        tuple(places) if places is not None else None,
    )
