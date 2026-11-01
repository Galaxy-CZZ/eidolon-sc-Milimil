"""Her moment's picture no one is in at GPT Image (GLOSSARY.md「配图」「生图」): where the
deployer has image generation and GPT Image beside it, scenery, food and an object are asked
of GPT Image first, in sentences the server puts together, at their sizes; one it fails, takes
too long over or answers amiss is asked of image generation as it always was, in what time is
left, and the moment's record says so (`picture_fallback`); failing there too, the moment is
posted without it. Every other picture, and every photo, is image generation's alone. The two
wait their turns apart, GPT Image one at a time.

Driven as `test_moment_pictures.py` drives moments, each service faked at its own transport."""

import asyncio
import io
import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from PIL import Image

import eidolon.moments
from eidolon.config import DEFAULT_GPT_IMAGE_STYLE, GptImageSettings, Settings
from eidolon.moment_prompt import PICTURE_FALLBACK
from tests.conftest import ClientFactory
from tests.fakes import FakeImageService
from tests.test_moment_pictures import (  # noqa: F401  (`characters` and `settings`)
    STREET,
    characters,
    pictured,
    settings,
)
from tests.test_moment_places import degraded
from tests.test_moments import SEVEN, START, moment_records, talked, tick, timeline
from tests.test_photos import SELFIE, WORDS, asking, photo_events, settled
from tests.test_reach_outs import backend_of
from tests.test_text_turn import send_turn

GPT = GptImageSettings("gpt-key", "https://api.openai.test/v1")


@pytest.fixture
def gpt_settings(settings: Settings) -> Settings:  # noqa: F811
    """`settings` with GPT Image beside the deployer's image generation."""
    return replace(settings, gpt_image=GPT)


async def posted(
    make_client: ClientFactory,
    settings: Settings,  # noqa: F811
    novelai: FakeImageService,
    gpt: FakeImageService,
    *replies,
) -> httpx.AsyncClient:
    """A client whose user has had a turn with Mano, once she has posted with `replies`."""
    client, _, clock, _ = await talked(
        make_client, *replies, settings=settings, image_transport=novelai.transport(),
        gpt_image_transport=gpt.transport(),
    )
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    return client


def image_calls(database: Path) -> list[tuple[str, str, str | None, float | None]]:
    """Each call to image generation: where, which model, its error, how many pictures it
    was billed."""
    with sqlite3.connect(database) as db:
        return db.execute(
            "SELECT provider, model, error, usage_input FROM service_calls"
            " WHERE service = 'image' ORDER BY id"
        ).fetchall()


async def test_scenery_is_asked_of_gpt_image_in_sentences_with_nothing_but_what_openai_takes(
    make_client: ClientFactory, gpt_settings: Settings
):
    novelai, gpt = FakeImageService(), FakeImageService()
    client = await posted(make_client, gpt_settings, novelai, gpt, pictured(STREET))

    [request] = gpt.requests
    [moment] = await timeline(client)
    picture = await client.get(moment["image"])

    assert novelai.requests == []
    assert request["url"] == "https://api.openai.test/v1/images/generations"
    assert request["key"] == "gpt-key"
    body = request["body"]
    assert body.keys() == {"model", "prompt", "size", "quality", "n"}
    assert (body["model"], body["size"], body["quality"], body["n"]) == (
        "gpt-image-2", "1216x832", "medium", 1
    )
    assert body["prompt"] == "\n".join([
        DEFAULT_GPT_IMAGE_STYLE,
        "Subject: scenery, a casual snapshot a young woman living in Tokyo just posted to her"
        " social media feed. At most a few small, distant passersby; no one is the subject.",
        "What the picture shows (follow this): 回家路上的住宅街",
        "Details: street, dusk, sidewalk, power lines, vending machine",
        "When: October, morning.",  # 07:00 in Tokyo; no weather to be had
        "Seen at eye level from the ground, as if she took it herself."
        " No added text, captions or watermarks.",
    ])
    with Image.open(io.BytesIO(picture.content)) as webp:
        assert webp.size == (1216, 832)
    assert image_calls(gpt_settings.database_path) == [("api.openai.test", "gpt-image-2", None, 1)]
    assert degraded(gpt_settings.database_path) == [None]


async def test_a_picture_at_another_size_is_cut_to_its_shape_not_refused(
    make_client: ClientFactory, gpt_settings: Settings
):
    novelai, gpt = FakeImageService(), FakeImageService()
    gpt.size = (1086, 1448)  # turned the other way, as relays answer
    client = await posted(make_client, gpt_settings, novelai, gpt, pictured(STREET))

    [moment] = await timeline(client)
    picture = await client.get(moment["image"])

    assert novelai.requests == []
    with Image.open(io.BytesIO(picture.content)) as webp:
        assert webp.size == (1216, 832)


async def test_food_is_asked_of_gpt_image_upright(
    make_client: ClientFactory, gpt_settings: Settings
):
    novelai, gpt = FakeImageService(), FakeImageService()
    await posted(make_client, gpt_settings, novelai, gpt, pictured("composition: food"))

    [request] = gpt.requests

    assert novelai.requests == []
    assert request["body"]["size"] == "832x1216"
    assert "Subject: food" in request["body"]["prompt"]


async def test_one_she_is_in_and_every_photo_are_image_generations_alone(
    make_client: ClientFactory, gpt_settings: Settings
):
    novelai, gpt = FakeImageService(), FakeImageService()
    selfie = "composition: selfie\nplace: park\noutfit: coat\naction: smile"
    client, _, clock, conversation = await talked(
        make_client, pictured(selfie), [f"<photo>{SELFIE}</photo>", WORDS], clients=asking(),
        settings=gpt_settings, image_transport=novelai.transport(),
        gpt_image_transport=gpt.transport(),
    )
    await tick(client, clock, START)
    await tick(client, clock, SEVEN)
    [photo] = photo_events(await send_turn(client, conversation, "发张自拍给我看看"))
    await settled(client, photo["id"])

    assert gpt.requests == []
    assert len(novelai.requests) == 2


@pytest.mark.parametrize("answered", ["HTTP 400", "not a picture", "too slow"])
async def test_one_gpt_image_does_not_give_is_had_from_image_generation_and_told(
    make_client: ClientFactory,
    gpt_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    answered: str,
):
    novelai, gpt = FakeImageService(), FakeImageService()
    if answered == "HTTP 400":
        gpt.status, gpt.error = 400, "moderation_blocked"
    if answered == "not a picture":
        gpt.openai_answer = "chat"
    if answered == "too slow":
        monkeypatch.setattr(eidolon.moments, "GPT_TIME_LIMIT", 0.2)
        gpt.gate = asyncio.Event()
    client = await posted(make_client, gpt_settings, novelai, gpt, pictured(STREET))
    if gpt.gate is not None:
        gpt.gate.set()

    [moment] = await timeline(client)
    [request] = novelai.requests
    [(gpt_host, _, gpt_error, gpt_billed), (novelai_host, _, novelai_error, _)] = image_calls(
        gpt_settings.database_path
    )

    assert moment["image"] is not None
    assert "sidewalk" in request["body"]["input"]  # her tags, as always
    assert (gpt_host, novelai_host) == ("api.openai.test", "image.novelai.test")
    assert gpt_error == {"HTTP 400": "refused", "not a picture": "unreadable",
                         "too slow": "timeout"}[answered]
    assert gpt_billed == 0  # no picture, none billed
    assert novelai_error is None
    assert degraded(gpt_settings.database_path) == [{PICTURE_FALLBACK: 1}]


async def test_failing_at_both_the_moment_is_posted_without_a_picture(
    make_client: ClientFactory, gpt_settings: Settings
):
    novelai, gpt = FakeImageService(), FakeImageService()
    novelai.status = gpt.status = 503
    client = await posted(make_client, gpt_settings, novelai, gpt, pictured(STREET))

    [moment] = await timeline(client)

    assert moment["image"] is None
    assert moment_records(gpt_settings.database_path) == [("moment", "mano", "success", 0)]
    assert [error for _, _, error, _ in image_calls(gpt_settings.database_path)] == [
        "server_error", "server_error"
    ]
    assert degraded(gpt_settings.database_path) == [{PICTURE_FALLBACK: 1}]


async def test_without_image_generation_gpt_image_alone_gives_no_picture(
    make_client: ClientFactory, gpt_settings: Settings
):
    novelai, gpt = FakeImageService(), FakeImageService()
    client = await posted(
        make_client, replace(gpt_settings, image=None), novelai, gpt, pictured(STREET)
    )

    [moment] = await timeline(client)

    assert gpt.requests == novelai.requests == []
    assert moment["image"] is None
    assert backend_of(client).photos.gpt_on is False


async def test_gpt_image_and_image_generation_wait_their_turns_apart(
    make_client: ClientFactory, gpt_settings: Settings
):
    novelai, gpt = FakeImageService(), FakeImageService()
    gpt.gate = asyncio.Event()
    client, _, clock, conversation = await talked(
        make_client, pictured(STREET), *[[f"<photo>{SELFIE}</photo>", WORDS]] * 2,
        clients=asking(), settings=gpt_settings, image_transport=novelai.transport(),
        gpt_image_transport=gpt.transport(),
    )
    await tick(client, clock, START)
    clock.now = SEVEN
    posting = asyncio.create_task(backend_of(client).moments.run_due())
    while not gpt.requests:
        await asyncio.sleep(0.01)

    # GPT Image busy, a photo is generated all the same, on a key one at a time.
    [photo] = photo_events(await send_turn(client, conversation, "发张自拍给我看看"))
    came_out = await settled(client, photo["id"])
    # And image generation busy, GPT Image answers.
    novelai.gate = asyncio.Event()
    [other] = photo_events(await send_turn(client, conversation, "再来一张"))
    while len(novelai.requests) < 2:
        await asyncio.sleep(0.01)
    gpt.gate.set()
    await posting
    [moment] = await timeline(client)
    novelai.gate.set()
    await settled(client, other["id"])

    assert came_out == {"status": "ready", "reason": None}
    assert moment["image"] is not None
    assert len(gpt.requests) == 1

