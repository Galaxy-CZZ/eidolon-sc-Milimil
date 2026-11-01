"""A group photo (GLOSSARY.md「配图」): her moment's picture of her with one or two of her
circle, only in NovelAI's own format, where she has photo tags and one of her circle has
too. She is told who of her circle may be in it, and names them in `with`; a selfie if her
`action` says so, else someone else takes it. Each is a character of her own in NovelAI's
multiple characters, she first; how many they are, how it is taken, what they wear and how
much of them shows are said once; it is landscape. One with no one named, or one not of
those who may be, is a posed photo of her alone instead, and recorded. Whoever is in it likes
her moment.

Driven as `test_moment_pictures.py` drives pictures (`SteadyRandom(0)`: every moment has a
picture, her circle all the others, the likes shown 5 minutes after it), Hiori and Meguru with
photo tags, Kogane without."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from eidolon.config import ImageSettings, Settings
from eidolon.moment_prompt import (
    GROUP_CLOSING,
    IMAGE,
    LIKES,
    LIKES_OVER,
    GROUP_MARK,
    WITH,
    Member,
    PostMaterial,
    parse_post,
)
from eidolon.photo_prompt import NEGATIVE_PROMPT
from eidolon.producer import ProducerProfile
from tests.conftest import KOGANE_SHEET, MANO_PHOTO, MANO_SHEET, CharacterConfig, ClientFactory
from tests.fakes import FakeImageService, context_of
from tests.test_moment_circle import NOWHERE, SOMEONE
from tests.test_moment_pictures import HEAD, NOVELAI, TAIL, pictured, posted
from tests.test_moment_places import degraded
from tests.test_moments import FACTS, SEVEN, START, talked, tick, timeline
from tests.test_world_setting import section

HIORI_PHOTO = ("kazano hiori", "black hair, long hair, ponytail, blue eyes")
MEGURU_PHOTO = ("hachimiya meguru", "blonde hair, long hair, twintails, blue eyes")
MANO_BOX, HIORI_BOX, MEGURU_BOX = (
    f"girl, {tag}, {looks}" for tag, looks in (MANO_PHOTO, HIORI_PHOTO, MEGURU_PHOTO)
)


@pytest.fixture
def characters(tmp_path: Path, request: pytest.FixtureRequest) -> CharacterConfig:
    """Mano, Hiori and Meguru, with photo tags, Hiori's and Meguru's left out if asked
    (`request.param` False); Kogane, without."""
    others = getattr(request, "param", True)
    return (
        CharacterConfig(tmp_path / "characters")
        .add("mano", "櫻木真乃", MANO_SHEET, birthday="04-25", facts=FACTS, photo=MANO_PHOTO)
        .add("hiori", "風野灯織", "# 人设\n你是風野灯織。", birthday="02-02",
             photo=HIORI_PHOTO if others else None)
        .add("meguru", "八宮めぐる", "# 人设\n你是八宮めぐる。", birthday="06-19",
             photo=MEGURU_PHOTO if others else None)
        .add("kogane", "月岡恋鐘", KOGANE_SHEET, birthday="02-25")
    )


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With moments on and the deployer's image generation in NovelAI's own format, affinity
    off."""
    return replace(settings, moments=True, image=NOVELAI, affinity_and_gifts=False)


def captions(caption: dict) -> list[str]:
    """What each character's box in `caption` says, each placed where the model chooses."""
    assert all(c["centers"] == [{"x": 0, "y": 0}] for c in caption["char_captions"])
    return [c["char_caption"] for c in caption["char_captions"]]


@pytest.mark.parametrize(
    ("written", "positive", "boxes"),
    [
        pytest.param(
            "composition: group\nwith: hiori\nframing: full body\nplace: cafe, indoors\n"
            "outfit: white shirt\naction: smile, 2girls, sakuragi mano, 1girl, holding hands",
            "2girls, idolmaster shiny colors, side-by-side, upper body, cafe, indoors,"
            f" white shirt, smile, holding hands, looking at viewer, {TAIL}",
            [MANO_BOX, HIORI_BOX], id="two, someone else taking it",
        ),
        pytest.param(
            "composition: group\nwith: hiori, meguru\nframing: cowboy shot\nplace: park\n"
            "outfit: coat\naction: peace sign, looking at another",
            "3girls, idolmaster shiny colors, group picture, cowboy shot, park, coat,"
            f" peace sign, looking at another, {TAIL}",
            [MANO_BOX, HIORI_BOX, MEGURU_BOX], id="three, someone else taking it",
        ),
        pytest.param(
            "composition: group\nwith: meguru\nframing: cowboy shot\nplace: street\n"
            "outfit: coat\naction: group selfie, peace sign",
            "2girls, idolmaster shiny colors, selfie, upper body, street, coat, peace sign,"
            f" looking at viewer, {TAIL}",
            [MANO_BOX, MEGURU_BOX], id="two, a selfie",
        ),
        pytest.param(
            "composition: group\nwith: meguru，hiori\nframing: portrait\nplace: street\n"
            "outfit: coat\naction: selfie, smile",
            "3girls, idolmaster shiny colors, selfie, portrait, street, coat, smile,"
            f" looking at viewer, {TAIL}",
            [MANO_BOX, MEGURU_BOX, HIORI_BOX], id="three, a selfie",
        ),
    ],
)
async def test_a_group_photo_is_each_in_a_box_of_her_own_she_first_landscape(
    make_client: ClientFactory,
    settings: Settings,
    written: str,
    positive: str,
    boxes: list[str],
):
    image = FakeImageService()
    client, llm = await posted(make_client, image, pictured(written))

    [request] = image.requests
    parameters = request["body"]["parameters"]
    told = context_of(llm.prompts[-1])
    circle = section(told, "# 圈子成员")
    negative = parameters["v4_negative_prompt"]["caption"]

    assert "  - group：" in told
    assert told.endswith(GROUP_CLOSING)
    assert f"## hiori：風野灯織{GROUP_MARK}" in circle
    assert f"## meguru：八宮めぐる{GROUP_MARK}" in circle
    assert f"## kogane：月岡恋鐘{GROUP_MARK}" not in circle
    assert request["body"]["input"] == positive
    assert parameters["v4_prompt"]["caption"]["base_caption"] == positive
    assert captions(parameters["v4_prompt"]["caption"]) == boxes
    assert parameters["v4_prompt"]["use_coords"] is False
    assert parameters["negative_prompt"] == negative["base_caption"] == NEGATIVE_PROMPT
    assert captions(negative) == [""] * len(boxes)
    assert (parameters["width"], parameters["height"]) == (1216, 832)
    assert degraded(settings.database_path) == [None]


@pytest.mark.parametrize(
    "with_",
    [
        pytest.param("", id="no one"),
        pytest.param("with: hiori, kogane\n", id="one of them without photo tags"),
    ],
)
async def test_one_written_with_no_one_she_may_be_with_is_a_posed_photo_of_her_alone(
    make_client: ClientFactory, settings: Settings, with_: str
):
    image = FakeImageService()
    written = (
        f"composition: group\n{with_}framing: full body\nplace: park\noutfit: coat\n"
        "action: holding hands, smile"
    )
    client, _ = await posted(make_client, image, pictured(written))

    [request] = image.requests
    parameters = request["body"]["parameters"]
    [moment] = await timeline(client)

    assert request["body"]["input"] == (
        f"{HEAD}, full body, park, coat, smile, looking at viewer, {TAIL}"
    )
    assert parameters["v4_prompt"]["caption"]["char_captions"] == []
    assert (parameters["width"], parameters["height"]) == (832, 1216)
    assert moment["image"] is not None
    assert degraded(settings.database_path) == [{WITH: 1}]


async def test_whoever_is_in_it_with_her_likes_her_moment_written_so_or_not(
    make_client: ClientFactory, settings: Settings
):
    image = FakeImageService()
    written = [
        *NOWHERE,
        "<image>composition: group\nwith: hiori, meguru\naction: smile</image>",
        "<likes>kogane, meguru</likes>",
    ]
    client, _, clock, _ = await talked(make_client, written, image_transport=image.transport())
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    clock.now = SEVEN + timedelta(minutes=5)

    [moment] = await timeline(client)

    assert moment["likes"] == ["kogane", "meguru", "hiori"]
    assert degraded(settings.database_path) == [None]


async def test_in_openais_image_format_there_is_no_group_photo(
    make_client: ClientFactory, settings: Settings
):
    relay = ImageSettings("relay-key", "https://relay.image.test/v1", "nai", api_format="openai")
    image = FakeImageService()
    client, llm = await posted(
        make_client, image, pictured("composition: group\nwith: hiori\naction: smile"),
        settings=replace(settings, image=relay),
    )

    told = context_of(llm.prompts[-1])
    [moment] = await timeline(client)

    assert "  - selfie：" in told
    assert "group" not in told and GROUP_MARK not in told
    assert image.requests == []
    assert moment["image"] is None
    assert degraded(settings.database_path) == [{IMAGE: 1}]


@pytest.mark.parametrize("characters", [False], indirect=True)
async def test_with_no_one_of_her_circle_with_photo_tags_there_is_no_group_photo(
    make_client: ClientFactory, settings: Settings
):
    image = FakeImageService()
    client, llm = await posted(
        make_client, image, pictured("composition: group\nwith: hiori\naction: smile")
    )

    told = context_of(llm.prompts[-1])

    assert "  - posed：" in told
    assert "group" not in told and GROUP_MARK not in told
    assert image.requests == []
    assert degraded(settings.database_path) == [{IMAGE: 1}]


def test_those_with_her_are_never_of_the_likes_over_as_many_as_are_kept():
    """Not met with on a moment, her circle as many as may like it and more; read as the
    eval reads it."""
    her = replace(SOMEONE, photo_tag=MANO_PHOTO[0], photo_appearance=MANO_PHOTO[1])
    hiori = replace(SOMEONE, id="hiori", name="風野灯織", photo_tag=HIORI_PHOTO[0],
                    photo_appearance=HIORI_PHOTO[1])
    others = [Member(replace(SOMEONE, id=f"idol{i}", name=f"偶像{i}")) for i in range(LIKES)]
    material = PostMaterial(her, None, ProducerProfile(), [], False, [], None, [],
                            circle=[*others, Member(hiori)], compositions=["group"])
    written = "".join([
        *NOWHERE,
        "<image>composition: group\nwith: hiori\naction: smile</image>",
        f"<likes>{','.join(m.character.id for m in others)}</likes>",
    ])

    post = parse_post(written, material)

    assert post is not None
    assert post.likes == [*(f"idol{i}" for i in range(LIKES - 1)), "hiori"]
    assert post.degraded == {LIKES_OVER: 1}
    assert post.picture is not None and post.picture.written["with"] == "hiori"
