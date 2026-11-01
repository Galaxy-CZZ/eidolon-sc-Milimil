"""GPT Image (GLOSSARY.md「生图」) as it is configured and asked: `.env` sets it, the admin
console's card beside image generation's overrides it, a change tried before it is kept by
generating one picture of fixed scenery, neither billed nor recorded; it goes through the
proxy by a switch of its own. What it is sent for a moment's picture no one is in is put
together by the server (`gpt_image_prompt`), and a picture it answers at another size is cut
to the size kept, never refused.

The prompt and the fitting are pure, and tried as such; the card through the backend's
external API, the service faked at its transport."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from eidolon.config import (
    DEFAULT_GPT_IMAGE_STYLE,
    GptImageSettings,
    Settings,
    proxy_from_env,
)
from eidolon.gpt_image_prompt import gpt_picture_prompt
from eidolon.image_generation import kept_as_webp
from eidolon.photo_prompt import PictureTag
from eidolon.place_pool import Place
from eidolon.weather import Weather
from tests.conftest import ClientFactory
from tests.fakes import FakeIdentityProvider, FakeImageService, FakeServiceClients, png
from tests.test_live_config import CONFIG, admin_client, recorded
from tests.test_photos import IMAGE, asking

GPT_CARD = "/api/admin/config/gpt_image"
GPT_KEY = "sk-gpt-key-9876"
CARD = {
    "base_url": "https://api.openai.test/v1/",
    "model": "gpt-image-2",
    "quality": "low",
    "style": "",
    "api_key": GPT_KEY,
}
SHIMOKITA = Place(
    "shimokita", "下北沢南口商店街", "世田谷区", 35.66, 139.67, "shopping-street",
    "下北沢站南口延伸出去的商店街。", date(2026, 10, 1),
)
YOKOHAMA = Place(
    "akarenga", "横浜赤レンガ倉庫", "神奈川県横浜市", 35.45, 139.64, "seaside", "港边的红砖仓库。",
    date(2026, 10, 1),
)
EVENING = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
"""17:00 in Tokyo."""


def tag(composition, place=(), action=()) -> PictureTag:
    return PictureTag(composition, None, tuple(place), (), tuple(action))


# What GPT Image is sent.


def test_scenery_says_where_she_was_as_background_and_when_in_tokyos_weather():
    prompt = gpt_picture_prompt(
        tag("scenery", ["street", "dusk"], ["sidewalk", "street"]), " 回家路上的商店街 ",
        SHIMOKITA, EVENING, Weather("rain", 12), "Style.",
    )

    assert prompt.size == (1216, 832)
    assert prompt.text == "\n".join([
        "Style.",
        "Subject: scenery, a casual snapshot a young woman living in Tokyo just posted to her"
        " social media feed. At most a few small, distant passersby; no one is the subject.",
        "Place (background information only; do not add things because of it):"
        " 下北沢南口商店街, 世田谷区, Tokyo — 下北沢站南口延伸出去的商店街。",
        "What the picture shows (follow this): 回家路上的商店街",
        "Details: street, dusk, sidewalk",
        "When: November, evening, rainy.",
        "Seen at eye level from the ground, as if she took it herself."
        " No added text, captions or watermarks.",
    ])


def test_an_object_is_upright_with_no_one_in_it_seen_from_close_by():
    prompt = gpt_picture_prompt(
        tag("object", ["desk"], ["letter paper"]), "信纸", None, EVENING, None, "Style."
    )

    assert prompt.size == (832, 1216)
    assert "Subject: an object, a casual snapshot" in prompt.text
    assert "No people in the frame." in prompt.text
    assert prompt.text.endswith(
        "Seen from close by, as if she took it herself. No added text, captions or watermarks."
    )


def test_at_no_place_nor_in_known_weather_those_are_left_out():
    prompt = gpt_picture_prompt(tag("object", [], ["flowers"]), "", None, EVENING, None, "S.")

    assert "Place" not in prompt.text
    assert "What the picture shows" not in prompt.text
    assert "When: November, evening.\n" in prompt.text


def test_a_place_of_a_prefecture_of_its_own_is_not_said_to_be_in_tokyo():
    prompt = gpt_picture_prompt(tag("scenery"), "", YOKOHAMA, EVENING, None, "S.")

    assert "横浜赤レンガ倉庫, 神奈川県横浜市 — 港边的红砖仓库。" in prompt.text
    assert "Tokyo —" not in prompt.text
    assert "Details" not in prompt.text


@pytest.mark.parametrize(
    ("hour", "said"),
    [(2, "late at night"), (7, "morning"), (12, "midday"), (15, "afternoon"), (18, "evening"),
     (21, "night")],
)
def test_the_time_of_day_is_tokyos(hour: int, said: str):
    at = datetime(2026, 5, 31, 15, tzinfo=UTC) + timedelta(hours=hour)  # 00:00 June 1 in Tokyo

    prompt = gpt_picture_prompt(tag("scenery"), "", None, at, None, "S.")

    assert f"When: June, {said}." in prompt.text


# What is kept of what it answers.


def test_a_picture_of_the_size_asked_for_is_kept_as_it_is():
    picture = png(1216, 832, "metadata")

    assert kept_as_webp(picture, (1216, 832), fit=True) == kept_as_webp(picture, (1216, 832))


# Configured.


def test_env_sets_it_off_without_a_key_and_refuses_a_quality_not_known(
    monkeypatch: pytest.MonkeyPatch,
):
    for name in ("GPT_IMAGE_BASE_URL", "GPT_IMAGE_MODEL", "GPT_IMAGE_QUALITY", "GPT_IMAGE_STYLE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GPT_IMAGE_API_KEY", raising=False)
    off = GptImageSettings.from_env()
    monkeypatch.setenv("GPT_IMAGE_API_KEY", "sk-key")
    by_default = GptImageSettings.from_env()
    monkeypatch.setenv("GPT_IMAGE_BASE_URL", "https://relay.test/v1/")
    monkeypatch.setenv("GPT_IMAGE_MODEL", "gpt-image-2.5-flare")
    monkeypatch.setenv("GPT_IMAGE_QUALITY", "xhigh")
    monkeypatch.setenv("GPT_IMAGE_STYLE", " Watercolor. ")
    set_so = GptImageSettings.from_env()
    monkeypatch.setenv("GPT_IMAGE_QUALITY", "ultra")

    assert off is None
    assert by_default == GptImageSettings(
        "sk-key", "https://api.openai.com/v1", "gpt-image-2", "medium", DEFAULT_GPT_IMAGE_STYLE
    )
    assert set_so == GptImageSettings(
        "sk-key", "https://relay.test/v1", "gpt-image-2.5-flare", "xhigh", "Watercolor."
    )
    with pytest.raises(RuntimeError, match="GPT_IMAGE_QUALITY"):
        GptImageSettings.from_env()


def test_it_goes_through_the_proxy_by_a_switch_of_its_own(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EIDOLON_PROXY_URL", "http://127.0.0.1:7890")
    monkeypatch.setenv("EIDOLON_PROXY_SERVICES", "image")
    image_only = proxy_from_env()
    monkeypatch.setenv("EIDOLON_PROXY_SERVICES", "gpt_image")
    gpt_only = proxy_from_env()

    assert image_only.proxy_for("gpt_image") is None
    assert gpt_only.proxy_for("gpt_image") == "http://127.0.0.1:7890"
    assert gpt_only.proxy_for("image") is None


@pytest.fixture
def admins(settings: Settings) -> Settings:
    """With the admin and the deployer's image generation, no GPT Image in `.env`."""
    return replace(
        settings, admins=frozenset({("github", "1001")}), image=IMAGE, gpt_image=None
    )


async def gpt_admin(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider,
    gpt: FakeImageService, clients: FakeServiceClients | None = None,
) -> httpx.AsyncClient:
    def factory(*args, **kwargs) -> httpx.AsyncClient:
        return make_client(*args, gpt_image_transport=gpt.transport(), **kwargs)

    return await admin_client(factory, settings, github, clients or asking())


async def test_a_card_saved_is_tried_on_one_picture_of_scenery_unbilled_then_holds_till_restored(
    make_client: ClientFactory, admins: Settings, github: FakeIdentityProvider
):
    gpt = FakeImageService()
    client = await gpt_admin(make_client, admins, github, gpt)
    before = (await client.get(CONFIG)).json()["gpt_image"]

    saved = await client.put(GPT_CARD, json=CARD)
    assert saved.status_code == 200, saved.text
    backend = client._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]
    in_effect = backend.config.gpt_image_settings
    restored = await client.delete(GPT_CARD)
    assert restored.status_code == 200, restored.text

    assert before["status"] == "env"
    assert before["effective"] == {
        "base_url": "https://api.openai.com/v1", "model": "gpt-image-2", "quality": "medium",
        "style": DEFAULT_GPT_IMAGE_STYLE, "api_key_last4": None,
    }
    shown = saved.json()["gpt_image"]
    assert shown["status"] == "overridden"
    assert shown["effective"] == {
        "base_url": "https://api.openai.test/v1", "model": "gpt-image-2", "quality": "low",
        "style": DEFAULT_GPT_IMAGE_STYLE, "api_key_last4": "9876",
    }
    assert GPT_KEY not in saved.text
    [check] = gpt.requests
    assert check["url"] == "https://api.openai.test/v1/images/generations"
    assert check["key"] == GPT_KEY
    assert check["body"].keys() == {"model", "prompt", "size", "quality", "n"}
    assert (check["body"]["size"], check["body"]["quality"]) == ("1216x832", "low")
    assert check["body"]["prompt"].startswith(DEFAULT_GPT_IMAGE_STYLE + "\nSubject: scenery")
    assert recorded(client, "image") == []
    assert in_effect == GptImageSettings(
        GPT_KEY, "https://api.openai.test/v1", "gpt-image-2", "low", DEFAULT_GPT_IMAGE_STYLE
    )
    assert backend.config.gpt_image_settings is None
    assert restored.json()["gpt_image"] == before


async def test_a_card_whose_try_fails_is_not_saved_saying_why(
    make_client: ClientFactory, admins: Settings, github: FakeIdentityProvider
):
    gpt = FakeImageService()
    gpt.status, gpt.error = 400, "invalid size"  # a model before gpt-image-2
    client = await gpt_admin(make_client, admins, github, gpt)

    refused = await client.put(GPT_CARD, json=CARD)
    without_key = await client.put(GPT_CARD, json={k: v for k, v in CARD.items() if k != "api_key"})

    assert refused.status_code == 422
    assert refused.json()["detail"].startswith("试调失败，没有保存：")
    assert "400" in refused.json()["detail"]
    assert without_key.status_code == 422
    assert "GPT Image 的 key" in without_key.json()["detail"]
    assert (await client.get(CONFIG)).json()["gpt_image"]["status"] == "env"


async def test_the_proxy_card_tries_gpt_image_apart_and_keeps_its_switch(
    make_client: ClientFactory, admins: Settings, github: FakeIdentityProvider
):
    from tests.test_proxy import ALL_OFF, PROXY, FakeReach

    reach = FakeReach()
    gpt = FakeImageService()

    def factory(*args, **kwargs) -> httpx.AsyncClient:
        return make_client(*args, reach=reach, gpt_image_transport=gpt.transport(), **kwargs)

    client = await admin_client(
        factory, replace(admins, gpt_image=GptImageSettings("sk-env")), github, asking()
    )
    saved = await client.put(
        PROXY, json={"enabled": True, "url": "http://127.0.0.1:7890"} | ALL_OFF | {"gpt_image": True}
    )

    assert saved.status_code == 200, saved.text
    assert reach.reached == [("https://api.openai.com/v1", "http://127.0.0.1:7890")]
    assert saved.json()["proxy"]["effective"]["gpt_image"] is True
    assert saved.json()["proxy"]["effective"]["image"] is False
    assert "gpt_image" not in saved.json()["proxy"]["unconfigured"]

