"""The places in moments (GLOSSARY.md「地点」): she is given some of the place pool to choose
from as she posts, besides none, and the moment shows the one she chose by its Japanese name,
with a link to it on the map the deployer chooses. One she chose that she was not given is left
out, and recorded as made do without. The moment keeps a copy of the place, so that it shows
as it was should the pool change; a place the user's moments were at within 30 days is not
given again.

Driven as `test_moments.py` drives moments, on a place pool of the test's own."""

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from eidolon.config import Settings
from eidolon.moment_prompt import HOLY_SITE
from eidolon.place_pool import PLACES_FILE
from tests.conftest import KOGANE_SHEET, MANO_SHEET, CharacterConfig, ClientFactory
from tests.fakes import FakeIdentityProvider, FakeLLM, context_of
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_moments import FACTS, MOMENTS, SEVEN, START, talked, tick, timeline

PARK = """\
[[places]]
id = "inokashira"
name = "井の頭恩賜公園"
area = "武蔵野市"
lat = 35.6997
lon = 139.5731
category = "park"
note = "有池塘和小船的大公园"
checked = 2026-10-01
"""

CAFE = """\
[[places]]
id = "kissa"
name = "喫茶ルオー"
area = "文京区"
lat = 35.7076
lon = 139.7612
category = "cafe"
note = "本乡的老咖啡馆"
checked = 2026-10-01
"""

AT_THE_PARK = [
    "<post><ja>池のボート、乗ってみたいな</ja><zh>池塘的小船，好想坐坐看</zh></post>",
    "<place>inokashira</place>",
    "<likes></likes>",
]
PARK_ON_THE_MAP = {
    "name": "井の頭恩賜公園",
    "map": "https://www.openstreetmap.org/?mlat=35.6997&mlon=139.5731#map=17/35.6997/139.5731",
}


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


def degraded(database: Path) -> list[dict | None]:
    """What each moment's activity record says was made do without, oldest first."""
    with sqlite3.connect(database) as db:
        return [
            json.loads(d) if d else None
            for (d,) in db.execute(
                "SELECT degraded FROM activity_records WHERE kind = 'moment' ORDER BY id"
            )
        ]


async def test_she_chooses_among_the_places_given_and_the_moment_shows_it_on_the_map(
    make_client: ClientFactory, settings: Settings
):
    client, llm, clock, _ = await talked(make_client, AT_THE_PARK)

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    [moment] = await timeline(client)
    assert moment["place"] == PARK_ON_THE_MAP
    assert degraded(settings.database_path) == [None]
    told = context_of(llm.prompts[-1])
    assert "# 地点候选" in told
    assert "- inokashira：井の頭恩賜公園（武蔵野市）有池塘和小船的大公园" in told
    assert "- kissa：喫茶ルオー（文京区）本乡的老咖啡馆" in told


@pytest.mark.parametrize(
    ("written", "made_do_without"),
    [("<place>none</place>", None), ("<place>tokyo-tower</place>", {"place": 1}),
     ("", {"place": 1})],
)
async def test_at_none_or_at_one_not_given_the_moment_shows_no_place(
    make_client: ClientFactory, settings: Settings, written: str, made_do_without: dict | None
):
    client, _, clock, _ = await talked(make_client, [AT_THE_PARK[0], written, AT_THE_PARK[2]])

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    [moment] = await timeline(client)
    assert moment["place"] is None
    assert degraded(settings.database_path) == [made_do_without]


async def test_the_moment_shows_the_place_as_it_was_after_the_pool_changes(
    make_client: ClientFactory, settings: Settings, characters: CharacterConfig
):
    client, _, clock, _ = await talked(make_client, AT_THE_PARK)
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    characters.write(PLACES_FILE, CAFE.replace("喫茶ルオー", "井の頭公園"))
    again = make_client(FakeLLM(), clock=clock)

    [moment] = await timeline(again)
    assert moment["place"] == PARK_ON_THE_MAP


async def test_a_place_her_moments_were_at_within_30_days_is_not_given_again(
    make_client: ClientFactory, settings: Settings
):
    client, llm, clock, _ = await talked(make_client, AT_THE_PARK, AT_THE_PARK)

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    await tick(client, clock, START + timedelta(days=1))
    await tick(client, clock, SEVEN + timedelta(days=1))

    told = context_of(llm.prompts[-1])
    assert "kissa：" in told and "inokashira：" not in told
    assert told.index("# 你最近发的朋友圈") < told.index("# 地点候选")
    assert [m["place"] for m in await timeline(client)] == [None, PARK_ON_THE_MAP]


@pytest.mark.parametrize(
    ("site", "link"),
    [
        ("osm", PARK_ON_THE_MAP["map"]),
        ("google", "https://www.google.com/maps/search/?api=1&query=35.6997%2C139.5731"),
        ("amap", "https://uri.amap.com/marker?position=139.5731,35.6997"
                 "&name=%E4%BA%95%E3%81%AE%E9%A0%AD%E6%81%A9%E8%B3%9C%E5%85%AC%E5%9C%92"
                 "&coordinate=wgs84"),
    ],
)
async def test_the_link_is_to_the_map_the_admin_chooses(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider, site: str,
    link: str
):
    client, _, clock, _ = await talked(make_client, AT_THE_PARK)
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    async with admin_beside(client, github) as admin:
        chosen = await admin.put(MOMENTS, json={"enabled": True, "per_day": 3, "map": site})

    assert chosen.status_code == 200
    assert chosen.json()["moments"]["effective"]["map"] == site
    [moment] = await timeline(client)
    assert moment["place"] == {"name": "井の頭恩賜公園", "map": link}


async def test_a_map_not_of_the_three_is_refused_and_one_left_out_left_as_it_is(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client, _, _, _ = await talked(make_client)

    async with admin_beside(client, github) as admin:
        await admin.put(MOMENTS, json={"enabled": True, "per_day": 3, "map": "amap"})
        refused = await admin.put(MOMENTS, json={"enabled": True, "per_day": 3, "map": "baidu"})
        left_out = await admin.put(MOMENTS, json={"enabled": True, "per_day": 2})

    assert refused.status_code == 422
    assert left_out.json()["moments"]["effective"] == {
        "enabled": True, "per_day": 2, "map": "amap", "replies_per_day": 10,
    }


async def test_her_holy_site_is_marked_among_the_places_given(
    make_client: ClientFactory, settings: Settings, characters: CharacterConfig
):
    holy = PARK.replace('checked = 2026-10-01', 'checked = 2026-10-01\nidols = ["mano"]\nsource = "卡面"')
    characters.write(PLACES_FILE, holy + "\n" + CAFE)
    client, llm, clock, _ = await talked(make_client, AT_THE_PARK)

    await tick(client, clock, START)
    await tick(client, clock, SEVEN)

    told = context_of(llm.prompts[-1])
    assert f"- inokashira：井の頭恩賜公園（武蔵野市）有池塘和小船的大公园{HOLY_SITE}" in told
    assert f"本乡的老咖啡馆{HOLY_SITE}" not in told
