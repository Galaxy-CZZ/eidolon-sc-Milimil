"""Image generation (GLOSSARY.md「生图」): one picture from a prompt, checked and made into what
a photo is kept as.

An image service is reached in the format whoever configured it chose (`ImageFormat`),
never found out. In NovelAI's own: `POST {base_url}/ai/generate-image` with a bearer
token, answering with a ZIP of the picture, at NovelAI or a relay passing requests on as
they are; every request asks for one picture of the size its prompt says
(`ImagePrompt.size`: 832×1216 for a photo) at 23 steps, scale 7 with Euler Ancestral, from
a random seed, in the shape of V4's prompts and later. In OpenAI's image format:
`POST {base_url}/images/generations`, the address up to `/v1`, asking at the top level for
one picture of that size with the negative prompt, as base64 (`b64_json`, with a `data:`
prefix or without); one answered with a URL instead is downloaded on the same client, in
the same time. An answer in any other shape, a chat completion's among them, is not a
picture. None of it is anyone's to set. What comes back is checked: exactly one picture, of
the size asked for. It is kept as WebP, its size as it is, every bit of metadata dropped,
the prompt the PNG carries among it. Only the server calls the service; browsers never do.

GPT Image (`GptImageGenerator`), for moments' pictures no one is in, is spoken to in OpenAI's
image format as OpenAI has it, not as relays of NovelAI do: `model`, `prompt` (sentences,
`gpt_image_prompt`), `size`, `quality` and `n` alone, no negative prompt nor
`response_format`; its answer read as above, base64 or a URL. It is asked for the size the
picture is kept at, which gpt-image-2 and later take; one it answers at another size, as
relays do, turned the other way even, is cut to that shape about its middle and scaled to
it (`kept_as_webp`), never refused for it.

A request is billed in pictures (`billing`): one where the service answered with a picture,
of the size asked for or not, none where it answered with an error, or not in time. A
change to an image service is tried by generating one picture (`try_image_service`,
`try_gpt_image`: fixed scenery), which is billed for nothing and recorded nowhere.
"""

import asyncio
import base64
import binascii
import io
import random
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from eidolon.billing import bill
from eidolon.config import GptImageSettings, ImageSettings
from eidolon.gpt_image_prompt import GptPrompt, gpt_picture_prompt
from eidolon.photo_prompt import ImagePrompt, PictureTag, check_prompt
from eidolon.today import TOKYO
from eidolon.weather import Weather

STEPS = 23
SCALE = 7
SAMPLER = "k_euler_ancestral"
WEBP_QUALITY = 85
MAX_SEED = 4294967295 - 7
"""The largest seed NovelAI takes."""

TIME_LIMIT = 90
"""The longest a photo may take in all, in seconds, waiting its turn included."""
GENERATION_TIMEOUT = httpx.Timeout(TIME_LIMIT, connect=10)
GPT_TIME_LIMIT = 240
"""The longest a moment's picture may take at GPT Image, in seconds, waiting its turn
included, before NovelAI is tried instead."""
GPT_GENERATION_TIMEOUT = httpx.Timeout(GPT_TIME_LIMIT, connect=10)

Failure = Literal["timeout", "service_error", "bad_image"]
"""Why a picture could not be had: the service took too long, answered with an error or
could not be reached, or answered with what is not one picture of the size asked for."""


class ImageFailed(Exception):
    def __init__(self, reason: Failure, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason: Failure = reason
        self.detail = detail


def _bad_image(why: str) -> ImageFailed:
    """The service answered with what is not one picture of the size asked for: what is
    recorded as an answer that could not be read (`activity.error_kind`)."""
    return ImageFailed("bad_image", f"生图服务的返回无法解析（{why}）")


@dataclass(frozen=True)
class GeneratedImage:
    webp: bytes


def generation_request(model: str, prompt: ImagePrompt, seed: int) -> dict:
    """The body NovelAI's `/ai/generate-image` is sent for `prompt` with `model`: each of a
    group photo's characters in a box of her own, her negative box beside it empty, placed
    where the model chooses."""
    # Without coordinates: centers (0, 0) and `use_coords` false. The PNG that comes back
    # says `use_coords: true` in its metadata all the same; the picture is none the worse.
    # Not to be "fixed".
    unplaced = [{"x": 0, "y": 0}]
    positives = [{"char_caption": c, "centers": unplaced} for c in prompt.characters]
    negatives = [{"char_caption": "", "centers": unplaced} for _ in prompt.characters]
    return {
        "input": prompt.positive,
        "model": model,
        "action": "generate",
        "parameters": {
            "params_version": 3,
            "width": prompt.size[0],
            "height": prompt.size[1],
            "scale": SCALE,
            "sampler": SAMPLER,
            "steps": STEPS,
            "n_samples": 1,
            "ucPreset": 3,  # none: the negative prompt is written out in full
            "qualityToggle": False,  # the quality tags are written out too
            "seed": seed,
            "noise_schedule": "karras",
            "cfg_rescale": 0,
            "negative_prompt": prompt.negative,
            "v4_prompt": {
                "caption": {"base_caption": prompt.positive, "char_captions": positives},
                "use_coords": False,
                "use_order": True,
            },
            "v4_negative_prompt": {
                "caption": {"base_caption": prompt.negative, "char_captions": negatives},
                "legacy_uc": False,
            },
        },
    }


class ImageGenerator:
    """Generates pictures at the image service `settings` name, over `client`; whoever
    made the client closes it."""

    def __init__(self, settings: ImageSettings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self._client = client

    async def generate(self, prompt: ImagePrompt, until: float) -> GeneratedImage:
        """One picture for `prompt`, as kept, had by `until` (the running loop's time) at
        the latest. Raises ImageFailed saying why there is none. Tells what it is billed
        for (`billing`): one picture once the service answered with any, none before."""
        bill("images", 0)
        try:
            async with asyncio.timeout_at(until):
                if self.settings.api_format == "openai":
                    picture = await self._openai(prompt)
                else:
                    picture = await self._novelai(prompt)
        except (TimeoutError, httpx.TimeoutException) as e:
            raise ImageFailed("timeout", f"生图服务没有及时回应：{e!r}") from e
        except httpx.HTTPError as e:
            raise ImageFailed("service_error", f"无法连接生图服务：{e!r}") from e
        # On a thread: decoding and encoding take a while, which the event loop cannot spare.
        return GeneratedImage(await asyncio.to_thread(kept_as_webp, picture, prompt.size))

    async def _novelai(self, prompt: ImagePrompt) -> bytes:
        body = generation_request(
            self.settings.model, prompt, random.SystemRandom().randint(0, MAX_SEED)
        )
        res = await self._client.post(
            f"{self.settings.base_url}/ai/generate-image", json=body, headers=self._auth()
        )
        _check_status(res)
        pictures = files_in(res.content)
        if pictures:
            bill("images", 1)
        if len(pictures) != 1:
            raise _bad_image(f"ZIP 里有 {len(pictures)} 个文件")
        return pictures[0]

    async def _openai(self, prompt: ImagePrompt) -> bytes:
        res = await self._client.post(
            f"{self.settings.base_url}/images/generations",
            json=openai_request(self.settings.model, prompt),
            headers=self._auth(),
        )
        return await _openai_picture(self._client, res)

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.api_key}"}


def openai_request(model: str, prompt: ImagePrompt) -> dict:
    """The body OpenAI's image format, `/images/generations`, is sent for `prompt` with
    `model`: what it asks for at the top level, as relays read it."""
    return {
        "model": model,
        "prompt": prompt.positive,
        "negative_prompt": prompt.negative,
        "size": "{}x{}".format(*prompt.size),
        "n": 1,
        "response_format": "b64_json",
    }


async def try_image_service(generator: ImageGenerator) -> None:
    """Generate one picture, from a fixed prompt in the art style of `generator`'s settings,
    as a change to an image service is tried; raises ImageFailed saying why there is none.
    Billed for nothing and recorded nowhere: no `billing` is open for it, nor is it timed
    into the activity log."""
    until = asyncio.get_running_loop().time() + TIME_LIMIT
    await generator.generate(check_prompt(generator.settings.style), until)


class GptImageGenerator:
    """Generates moments' pictures no one is in at GPT Image as `settings` name it, over
    `client`; whoever made the client closes it."""

    def __init__(self, settings: GptImageSettings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self._client = client

    async def generate(self, prompt: GptPrompt, until: float) -> GeneratedImage:
        """One picture for `prompt`, as kept, had by `until` (the running loop's time) at
        the latest: of the size asked for, or cut to its shape and scaled to it. Raises
        ImageFailed saying why there is none. Billed as `ImageGenerator.generate` is."""
        bill("images", 0)
        try:
            async with asyncio.timeout_at(until):
                res = await self._client.post(
                    f"{self.settings.base_url}/images/generations",
                    json=gpt_image_request(self.settings, prompt),
                    headers={"Authorization": f"Bearer {self.settings.api_key}"},
                )
                picture = await _openai_picture(self._client, res)
        except (TimeoutError, httpx.TimeoutException) as e:
            raise ImageFailed("timeout", f"生图服务没有及时回应：{e!r}") from e
        except httpx.HTTPError as e:
            raise ImageFailed("service_error", f"无法连接生图服务：{e!r}") from e
        return GeneratedImage(
            await asyncio.to_thread(kept_as_webp, picture, prompt.size, fit=True)
        )


def gpt_image_request(settings: GptImageSettings, prompt: GptPrompt) -> dict:
    """The body GPT Image's `/images/generations` is sent for `prompt`: nothing but what
    OpenAI takes, answering in base64 by default."""
    return {
        "model": settings.model,
        "prompt": prompt.text,
        "size": "{}x{}".format(*prompt.size),
        "quality": settings.quality,
        "n": 1,
    }


TRIED_SCENERY = PictureTag(
    "scenery", None, ("street", "dusk"), (), ("sidewalk", "power lines", "vending machine")
)
"""What a change to GPT Image is tried with: a street at dusk, seen from the sidewalk."""
TRIED_AT = datetime(2026, 11, 3, 17, 0, tzinfo=TOKYO)


async def try_gpt_image(generator: GptImageGenerator) -> None:
    """Generate one picture of fixed scenery in the art style of `generator`'s settings, as
    a change to GPT Image is tried; raises ImageFailed saying why there is none. Billed for
    nothing and recorded nowhere, as `try_image_service`."""
    prompt = gpt_picture_prompt(
        TRIED_SCENERY, "回家路上经过的商店街", None, TRIED_AT, Weather("clear", 15),
        generator.settings.style,
    )
    until = asyncio.get_running_loop().time() + GPT_TIME_LIMIT
    await generator.generate(prompt, until)


async def _openai_picture(client: httpx.AsyncClient, res: httpx.Response) -> bytes:
    """The one picture `res`, an answer in OpenAI's image format, gives, downloaded on
    `client` if it gives a URL; billed one picture once there is any."""
    _check_status(res)
    try:
        answer = res.json()
    except ValueError:
        raise _bad_image("不是 JSON") from None
    data = answer.get("data") if isinstance(answer, dict) else None
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise _bad_image("不是 OpenAI 图像格式的返回")
    if not data:
        raise _bad_image("返回了 0 张图")
    picture = await _openai_item(client, data[0])
    bill("images", 1)
    if len(data) != 1:
        raise _bad_image(f"返回了 {len(data)} 张图")
    return picture


async def _openai_item(client: httpx.AsyncClient, item: dict) -> bytes:
    """The picture one item of OpenAI's image format's `data` gives: decoded, or
    downloaded on `client`."""
    if isinstance(encoded := item.get("b64_json"), str):
        return _decoded(encoded)
    if isinstance(url := item.get("url"), str):
        downloaded = await client.get(url)
        _check_status(downloaded)
        return downloaded.content
    raise _bad_image("返回里没有 b64_json，也没有 url")


def _check_status(res: httpx.Response) -> None:
    if res.status_code >= 400:
        raise ImageFailed("service_error", f"生图服务返回 {res.status_code}: {res.text[:300]}")


def _decoded(encoded: str) -> bytes:
    """The picture base64 `encoded`, with a `data:` URL's prefix or without."""
    if encoded.startswith("data:"):
        encoded = encoded.partition(",")[2]
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise _bad_image("b64_json 不是 base64") from None


def files_in(archive: bytes) -> list[bytes]:
    """The files in the ZIP `archive`. Raises ImageFailed if it is not a ZIP."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            return [zipped.read(n) for n in zipped.namelist() if not n.endswith("/")]
    except (zipfile.BadZipFile, OSError) as e:
        raise _bad_image(f"不是 ZIP：{e}") from None


def kept_as_webp(picture: bytes, size: tuple[int, int], fit: bool = False) -> bytes:
    """`picture` as a photo is kept: WebP, nothing but its pixels. Raises ImageFailed unless
    it is a picture of `size`, width by height; or, to `fit`, one of another size is cut to
    its shape about its middle and scaled to it, however it is turned."""
    width, height = size
    try:
        with Image.open(io.BytesIO(picture)) as opened:
            opened.load()
            pixels = opened.convert("RGB")
            if pixels.size != size:
                if not fit:
                    raise _bad_image(f"{opened.size[0]}×{opened.size[1]}，不是 {width}×{height}")
                pixels = ImageOps.fit(pixels, size, Image.Resampling.LANCZOS)
            # Made anew from its pixels alone, so nothing of what came with it is written.
            bare = Image.frombytes("RGB", size, pixels.tobytes())
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise _bad_image(f"不是图片：{e}") from None
    out = io.BytesIO()
    bare.save(out, "WEBP", quality=WEBP_QUALITY)
    return out.getvalue()
