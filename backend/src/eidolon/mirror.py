"""The ShinyColorsDB mirror of the game's decoded scripts and Spine stands, and its API
(ADR-0004, ADR-0011), with the game's own asset server behind it (ADR-0032).

The API (`api.shinycolors.moe`) lists every idol and her cards, and each card's
episodes with the game script they are in and their title, and the stands each of her
dresses has; the viewer (`viewer.shinycolors.moe`) serves the scripts themselves, as
the game does, and the CDN (`cf-static.shinycolors.moe`) the stands' files. Neither
publishes terms or a rate limit and both are run by volunteers, so requests go out
one at a time, about a second apart, and a script already downloaded can be asked
for conditionally, on its ETag, as can an album. Keeping the scripts is not the
mirror's business: that is `script_cache`.

A script or a stand's file the mirror does not have, or cannot send, is asked of the
game's asset server (`official_cdn`), which the mirror copies them from: new ones are
often there first. Only the files: which cards there are, their episodes and dresses,
come from the API alone. The server answers a file it does not have with the game's
page, as it would answer everything while down for maintenance; so when the mirror
could not be reached, that page means the server has no such file only once it has
sent a file this time, and until then it is the mirror's error.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from eidolon import official_cdn

log = logging.getLogger(__name__)

API_URL = "https://api.shinycolors.moe"
VIEWER_URL = "https://viewer.shinycolors.moe/json"
STATIC_URL = "https://cf-static.shinycolors.moe"
ALBUM_URL = f"{STATIC_URL}/albums/album"
ALBUM_IDOLS = range(1, 29)
"""The idols with an album: 28 of them, as of its last update."""
DEFAULT_INTERVAL = 1.0
"""Seconds between requests."""
_USER_AGENT = "eidolon-sc story and stand sync (weekly, one request a second)"


class MirrorError(RuntimeError):
    """The API or the viewer could not be reached, or answered with something unexpected."""


@dataclass(frozen=True)
class Card:
    uuid: str
    name: str
    """As the game names it, 【card name】idol name, which is also how SCTranslationData
    names the card's directory."""
    type: str
    """`P_SSR`, `S_SR` and so on: a produce (P) or support (S) card."""
    version: str
    """Changes whenever the card's data does."""


@dataclass(frozen=True)
class CardEpisode:
    script: str
    """The game script, e.g. `produce_events/200100401`."""
    title: str


@dataclass(frozen=True)
class AlbumEpisode:
    script: str
    """The game script, e.g. `produce_events/100100101`."""
    title: str
    section: str
    """The part of the album it is in, e.g. `W.I.N.G.編`, `2019Xmas スペシャルコミュ`."""


# The script types the album's categories are in, as the mirror's viewer files them.
_ALBUM_SCRIPT_TYPES = {
    "character_event": "produce_events",
    "season_event": "produce_events",
    "unit_event": "produce_events",
    "concert_event": "produce_events",
    "communication_morning": "produce_communications",
    "communication_cheer": "produce_communication_cheers",
    "communication_audition": "produce_communication_auditions",
    "communication_television": "produce_communication_televisions",
    "birthday_event": "special_communications",
    "present_event": "special_communications",
    "seasonal_event": "special_communications",
    "seasonal_present_event": "special_communications",
    "special_communication": "special_communications",
}
_SCRIPT_NUMBER = re.compile(r"\d{8,}")


@dataclass(frozen=True)
class Dress:
    """One of an idol's dresses: a card's, or a costume of its own."""

    enza_id: str
    name: str
    """As the game names it, 【card name】idol name."""
    type: str
    """`P_SSR`, `Special`, `Mizugi` and so on."""
    stands: dict[str, str | None]
    """Where on the CDN each of its stands is, by kind (`stand`, `stand_costume`, `cb`,
    `cb_costume`), e.g. `spine/idols/stand/1030010010/`; None for one the API lists
    without a place, which the CDN does not have."""


@dataclass(frozen=True)
class Script:
    """A game script as the viewer (or the game's asset server) sent it: its frames, as
    JSON. The server's other files come in one too, with their ETag."""

    content: bytes
    etag: str | None


class Mirror:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=30), headers={"User-Agent": _USER_AGENT}
        )
        self._interval = interval
        self._last_request: float | None = None
        self._official_sent = False
        """Whether the game's asset server has sent a file, so is not down for maintenance."""

    async def idols(self) -> list[int]:
        idols = await self._api("/info/idolList")
        with _unexpected("/info/idolList"):
            return [int(idol["idolId"]) for idol in idols]

    async def cards(self, idol_id: int) -> list[Card]:
        info = await self._api("/info/idolInfo", idolId=idol_id)
        with _unexpected("/info/idolInfo"):
            return [
                Card(
                    uuid=card["cardUuid"],
                    name=card["cardName"],
                    type=card["cardType"],
                    version=f"{card.get('cardHash')}/{card.get('lastModified')}",
                )
                for card in info.get("cardLists") or []
            ]

    async def episodes(self, card: Card) -> list[CardEpisode]:
        """The card's episodes, in the order the game numbers them. Some cards have none."""
        if card.type.startswith("P_"):
            path, events, title = "/info/pCardInfo", "cardIdolEvents", "eventTitle"
        elif card.type.startswith("S_"):
            path, events, title = "/info/sCardInfo", "cardSupportEvents", "eventName"
        else:
            return []
        info = await self._api(path, cardId=card.uuid)
        with _unexpected(path):
            return sorted(
                (
                    CardEpisode(f"produce_events/{event['eventId']}", event.get(title) or "")
                    for event in info.get(events) or []
                    if event.get("eventId")
                ),
                key=lambda episode: episode.script,
            )

    async def album(self, idol_id: int, etag: str | None) -> tuple[list[AlbumEpisode] | None, str | None]:
        """The episodes in the idol's album, unless the mirror says the copy matching
        `etag` is still current (then None); returns them with the album's ETag. An idol
        without an album has no episodes. Entries that are not a script of their own (the
        jokes idols play, played from other scripts) are left out."""
        headers = {"If-None-Match": etag} if etag else {}
        url = f"{ALBUM_URL}/{idol_id:02d}.json"
        response = await self._get(url, headers=headers)
        if response.status_code == 304:
            return None, etag
        if response.status_code == 404:
            return [], None
        _check(response)
        try:
            album = response.json()
        except ValueError as e:
            raise MirrorError(f"{url}：相册不是 JSON（{e}）") from e
        with _unexpected(url):
            sections = {s["albumType"]: s["title"] for s in album.get("albumCommunicationTitles") or []}
            episodes = []
            for entry in album["communications"]:
                number, category = str(entry["communicationId"]), entry["communicationCategory"]
                if (kind := _ALBUM_SCRIPT_TYPES.get(category)) is None:
                    log.info("相册 %02d：不认识的分类 %s（%s），已跳过", idol_id, category, number)
                    continue
                if not _SCRIPT_NUMBER.fullmatch(number):
                    continue
                section = sections.get(entry.get("albumType")) or entry.get("albumType") or ""
                episodes.append(AlbumEpisode(f"{kind}/{number}", entry.get("title") or "", section))
        return episodes, response.headers.get("ETag")

    async def script(self, script: str, etag: str | None) -> Script | Literal["unchanged", "missing"]:
        """The script, unless the mirror says the copy matching `etag` is still current
        (`unchanged`). A script neither the mirror nor the game's asset server has is
        `missing`, not an error."""
        headers = {"If-None-Match": etag} if etag else {}
        problem: MirrorError | None = None
        try:
            response = await self._get(f"{VIEWER_URL}/{script}.json", headers=headers)
            if response.status_code == 304:
                return "unchanged"
            if response.status_code != 404:
                _check(response)
                try:
                    return Script(_checked_script(response.content), response.headers.get("ETag"))
                except ValueError as e:
                    raise MirrorError(f"{script}：镜像返回的{e}") from e
        except MirrorError as e:
            problem = e
        return await self._official(f"json/{script}.json", problem, _checked_script) or "missing"

    async def dresses(self, idol_id: int) -> list[Dress]:
        dresses = await self._api("/spine/dresslist", idolId=idol_id)
        with _unexpected("/spine/dresslist"):
            return [
                Dress(
                    enza_id=str(dress["enzaId"]),
                    name=dress.get("dressName") or "",
                    type=dress.get("dressType") or "",
                    stands={
                        asset["type"]: _with_slash(asset.get("path"))
                        for asset in (dress.get("assets") or {}).get("idols") or []
                    },
                )
                for dress in dresses
                if dress.get("enzaId")
            ]

    async def stand_file(self, path: str) -> bytes | None:
        """A stand's file on the CDN, e.g. `spine/idols/stand/1030010010/data.png`; None
        if neither the CDN nor the game's asset server has it."""
        problem: MirrorError | None = None
        try:
            response = await self._get(f"{STATIC_URL}/{path}")
            if response.status_code != 404:
                _check(response)
                if not response.content.lstrip().startswith(b"<"):
                    return response.content
                # An error page: the server's file if it has one, else the page, as before,
                # for the caller to tell it is not one.
                official = await self._official(path, None)
                return response.content if official is None else official.content
        except MirrorError as e:
            problem = e
        official = await self._official(path, problem)
        return None if official is None else official.content

    async def _official(
        self, path: str, problem: MirrorError | None, check: Callable[[bytes], bytes] | None = None
    ) -> Script | None:
        """The file at `path` from the game's asset server, decrypted and passed by
        `check` (which raises ValueError for one that is not what it should be), now that
        the mirror could not give it: `problem` says why, None if it does not have it.

        When the mirror does not have it, the server is only a chance to find it: None if
        the server does not have it either or fails, as before. When the mirror could not
        be reached, the server not having it is believed only once it has sent a file
        this time (see the module); otherwise, and when it fails, raises MirrorError."""
        if problem is not None:
            log.warning("%s；改从官方 CDN 拉取 %s", problem, path)
        try:
            response = await self._get(official_cdn.asset_url(path))
            lacks = response.status_code == 404 or response.headers.get("Content-Type", "").startswith("text/html")
            content = None if lacks else _official_file(path, response, check)
        except MirrorError as failure:
            if problem is not None:
                raise MirrorError(f"{problem}；官方 CDN 也不行：{failure}") from failure
            log.warning("镜像没有 %s，官方 CDN 也拉不到：%s", path, failure)
            return None
        if content is None:
            if problem is not None and not self._official_sent:
                raise MirrorError(f"{problem}；官方 CDN 也没有，可能在维护") from problem
            return None
        self._official_sent = True
        log.info("镜像拿不到 %s，从官方 CDN 拉到了", path)
        return Script(content, response.headers.get("ETag"))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _api(self, path: str, **params: Any) -> Any:
        response = await self._get(API_URL + path, params=params)
        _check(response)
        try:
            return response.json()
        except ValueError as e:
            raise MirrorError(f"{path}：API 返回的不是 JSON（{e}）") from e

    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        if self._last_request is not None:
            wait = self._last_request + self._interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        try:
            return await self._client.get(url, **kwargs)
        except httpx.HTTPError as e:
            raise MirrorError(f"无法连接 {url}：{e!r}") from e
        finally:
            self._last_request = time.monotonic()


def _official_file(path: str, response: httpx.Response, check: Callable[[bytes], bytes] | None) -> bytes:
    _check(response)
    try:
        content = official_cdn.decode(path, response.content)
        return content if check is None else check(content)
    except ValueError as e:
        raise MirrorError(f"官方 CDN 的 {path}：{e}") from e


def _checked_script(content: bytes) -> bytes:
    """The script as sent, having checked it is one: an array of frames, as JSON. Raises
    ValueError if it is not."""
    try:
        frames = json.loads(content)
    except ValueError as e:
        raise ValueError(f"不是 JSON（{e}）") from e
    if not isinstance(frames, list):
        raise ValueError("不是剧本的帧数组")
    return content


def _with_slash(path: str | None) -> str | None:
    if not path:
        return None
    return path if path.endswith("/") else f"{path}/"


@contextmanager
def _unexpected(path: str) -> Iterator[None]:
    """An answer shaped unlike what it used to be is the mirror's error, too."""
    try:
        yield
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise MirrorError(f"{path}：返回的数据结构和预期不同（{e!r}）") from e


def _check(response: httpx.Response) -> None:
    if response.status_code != 200:
        raise MirrorError(f"{response.request.url} 返回 HTTP {response.status_code}")
