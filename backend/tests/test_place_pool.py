"""The place pool (GLOSSARY.md「地点」) comes from configuration beside the characters', as
the job list does: real places in and around Tokyo a moment may name, checked as the backend
starts; and the jobs say which kinds of place they take her to, and each idol which kinds
she likes."""

import json
import tomllib
from collections import Counter
from datetime import date

import pytest

from eidolon.characters import load_characters
from eidolon.place_pool import CATEGORIES, PLACES_FILE, load_place_pool

from tests.conftest import REPO_PLACES, CharacterConfig, ClientFactory
from tests.fakes import FakeLLM

REPO_CHARACTERS = REPO_PLACES.parent


def place(id: str = "iroha-sakura-park", **fields: object) -> str:
    """A place, every field right unless `fields` say otherwise (None leaves one out), as
    TOML writes it."""
    entry: dict[str, object] = {
        "id": id, "name": "いろは坂桜公園", "area": "多摩市", "lat": 35.6468, "lon": 139.4497,
        "category": "park", "note": "坡道旁的小公园。", "checked": date(2026, 10, 31),
    } | fields
    lines = ["[[places]]"]
    for field, value in entry.items():
        if value is None:
            continue
        if isinstance(value, date):
            lines.append(f"{field} = {value.isoformat()}")  # a TOML date, not a string
        else:
            lines.append(f"{field} = {json.dumps(value, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def test_the_repositorys_pool_loads_with_its_holy_sites_venues_and_every_kind():
    idols = load_characters(REPO_CHARACTERS / "characters.toml")
    pool = load_place_pool(REPO_PLACES, idols)

    by_category = Counter(p.category for p in pool)
    assert 350 <= len(pool) <= 450
    assert all(by_category[c] >= 10 for c in CATEGORIES), by_category
    assert 40 <= sum(p.source is not None for p in pool) <= 60
    assert all(p.idols for p in pool if p.source is not None and not p.source.startswith("［"))


def test_every_venue_in_the_pool_is_a_venue_in_the_world_setting():
    """Checked here, not as the backend starts, so that syncing the world setting cannot keep
    it from starting."""
    world = json.loads((REPO_CHARACTERS / "world.json").read_text(encoding="utf-8"))
    venues = {day["venue"] for live in world["lives"] for day in live["days"]}
    pool = load_place_pool(REPO_PLACES, load_characters(REPO_CHARACTERS / "characters.toml"))

    for p in pool:
        if p.category == "venue":
            assert set(p.venue_names) <= venues, p.id


def test_every_idol_likes_two_to_four_kinds_of_place():
    entries = tomllib.loads((REPO_CHARACTERS / "characters.toml").read_text(encoding="utf-8"))
    world = json.loads((REPO_CHARACTERS / "world.json").read_text(encoding="utf-8"))
    idols = {i["name"] for i in world["idols"]}

    likes = {c["id"]: c.get("place_likes") for c in entries["characters"] if c["name"] in idols}
    assert len(likes) == 28
    assert all(liked and 2 <= len(liked) <= 4 for liked in likes.values()), likes


@pytest.mark.parametrize(
    ("places", "named"),
    [
        (place() + place(), "iroha-sakura-park"),
        (place(category="karaoke"), "karaoke"),
        (place(name=None), "name"),
        (place(lat=34.05), "lat"),  # 神津島, out of the way
        (place(lon=135.5), "lon"),  # 大阪
        (place(idols=["hiori"]), "hiori"),
        (place(seasons=["rainy"]), "rainy"),
        (place(slots=["night"]), "night"),
        (place(checked="2026-10"), "checked"),
        (place(checked=None), "checked"),
        (place(area="大阪府大阪市"), "大阪府"),
        (place(area="北海道札幌市"), "北海道"),
        (place(venues=["東京ドーム"]), "venues"),
        (place(note="坡道旁\n的小公园。"), "note"),
        ("[[places]\n", PLACES_FILE),
    ],
)
def test_a_broken_pool_keeps_the_backend_from_starting_naming_what_is_wrong(
    make_client: ClientFactory, characters: CharacterConfig, places: str, named: str
):
    characters.write(PLACES_FILE, places)

    with pytest.raises(RuntimeError, match=named):
        make_client(FakeLLM())


@pytest.mark.parametrize(
    ("places", "named"),
    [('["venue"]', "venue"), ("[]", "places")],
)
def test_a_job_going_to_kinds_of_place_there_are_not_keeps_the_backend_from_starting(
    make_client: ClientFactory, characters: CharacterConfig, places: str, named: str
):
    characters.write(
        "jobs.toml",
        '[[jobs]]\nid = "walk"\nname = "散步"\nnote = "说明"\ncategory = "private"\n'
        f"length = 1\nplaces = {places}\n",
    )

    with pytest.raises(RuntimeError, match=named):
        make_client(FakeLLM())


@pytest.mark.parametrize(
    ("likes", "named"),
    [
        ([], "place_likes"),
        (["park", "cafe", "books", "bath", "museum"], "place_likes"),
        (["park", "park"], "place_likes"),
        (["park", "nearby"], "nearby"),
    ],
)
def test_an_idol_liking_kinds_of_place_wrongly_keeps_the_backend_from_starting(
    make_client: ClientFactory, characters: CharacterConfig, likes: list[str], named: str
):
    characters.add("hiori", "風野灯織", "", place_likes=tuple(likes))

    with pytest.raises(RuntimeError, match=named):
        make_client(FakeLLM())
