"""QWeather (和风天气), for where the producer is (GLOSSARY.md「制作人档案」): finding a city by
its name or nearest a spot, in Chinese, and the weather warnings in force where a spot is, as
she talks (GLOSSARY.md「此刻」). Open-Meteo has no warnings and finds no city by a spot; the
weather itself is Open-Meteo's (`weather`). Only with the deployer's account: without it, the
producer has no city.

Each request is signed with a JSON Web Token (Ed25519; QWeather limits API keys from 2027) on
the account's own API host. Fetched as the weather is: direct, never through the proxy, not a
service the status page or activity records know of. The warnings at a spot are kept in
memory, by the grid cell, for `KEPT_WARNINGS`, waited on no longer than the caller says, the
fetch going on to be kept all the same; one failing, none is asked for again of that cell for
`RETRY_AFTER`."""

import asyncio
import base64
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from eidolon.clock import Clock
from eidolon.config import QWeatherSettings
from eidolon.producer import City
from eidolon.weather import RETRY_AFTER, Spot

log = logging.getLogger(__name__)

KEPT_WARNINGS = timedelta(hours=1)
"""How long the warnings fetched at a spot are kept."""

TOKEN_LASTS = timedelta(minutes=15)
"""How long each token signed holds; a new one is signed a minute before."""

MAX_CITIES = 10
"""How many cities a search answers with at most."""

TRIED_AT = (39.92, 116.41)
"""Where a change to the account is tried: Beijing."""


def private_key_body(value: str) -> str:
    """The private key as it may be written, in PEM (its line breaks maybe written `\\n`) or
    its base64 alone, as its base64 alone: what is kept, its last 4 characters shown. Pasted
    into one line, as a browser's input field has it, its line breaks are gone."""
    value = re.sub(r"-----(?:BEGIN|END)[A-Z ]*-----", " ", value.replace("\\n", "\n"))
    return "".join(value.split())


def private_key_pem(value: str) -> str:
    """The private key as it may be written (`private_key_body`), in PEM."""
    return f"-----BEGIN PRIVATE KEY-----\n{private_key_body(value)}\n-----END PRIVATE KEY-----\n"


class QWeatherFailed(Exception):
    """QWeather could not be asked, or answered with an error, saying which."""


@dataclass(frozen=True)
class _KeptWarnings:
    headlines: tuple[str, ...]
    fetched_at: datetime


class QWeather:
    """The deployer's QWeather account as `settings` has it now (None without one), asked
    over `transport` (QWeather's own by default), kept by `clock`."""

    def __init__(
        self,
        settings: Callable[[], QWeatherSettings | None],
        clock: Clock,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._http = httpx.AsyncClient(
            transport=transport, timeout=10, headers={"User-Agent": "eidolon-sc"},
            trust_env=False,
        )
        self._token: tuple[QWeatherSettings, str, datetime] | None = None
        self._warnings: dict[tuple[float, float], _KeptWarnings] = {}
        self._warnings_failed: dict[tuple[float, float], datetime] = {}
        self._fetching: dict[tuple[float, float], asyncio.Task[tuple[str, ...] | None]] = {}

    @property
    def on(self) -> bool:
        """Whether the deployer has an account in effect now."""
        return self._settings() is not None

    async def search(self, name: str) -> list[City]:
        """The cities by `name`, the likeliest first, `MAX_CITIES` at most. Raises
        QWeatherFailed."""
        return await self._lookup(name, settings=None)

    async def nearest(self, latitude: float, longitude: float) -> City | None:
        """The city, district or county nearest the spot; None if none. Raises
        QWeatherFailed."""
        found = await self._lookup(_location(latitude, longitude), settings=None)
        return found[0] if found else None

    async def tried(self, settings: QWeatherSettings) -> None:
        """Try the account `settings` has, finding the city at `TRIED_AT`. Raises
        QWeatherFailed saying why it does not work."""
        if not await self._lookup(_location(*TRIED_AT), settings=settings):
            raise QWeatherFailed("找不到北京，账号可能有问题")

    async def warnings(self, spot: Spot, wait: float) -> tuple[str, ...] | None:
        """The headlines of the weather warnings in force at `spot` now: as kept, or fetched
        now, waited on for no longer than `wait` seconds; None if they cannot be had by then
        or without an account."""
        if self._settings() is None:
            return None
        now = self._clock()
        kept = self._warnings.get(spot.cell)
        if kept is not None and now - kept.fetched_at < KEPT_WARNINGS:
            return kept.headlines
        failed_at = self._warnings_failed.get(spot.cell)
        if failed_at is not None and now - failed_at < RETRY_AFTER:
            return None
        fetching = self._fetching.get(spot.cell)
        if fetching is None:
            fetching = asyncio.create_task(self._fetch_warnings(spot))
            self._fetching[spot.cell] = fetching
        done, _ = await asyncio.wait({fetching}, timeout=wait)
        return fetching.result() if done else None

    async def _fetch_warnings(self, spot: Spot) -> tuple[str, ...] | None:
        latitude, longitude = spot.cell
        try:
            answer = await self._get(
                f"/weatheralert/v1/current/{latitude:.2f}/{longitude:.2f}", {"lang": "zh"}
            )
            headlines = tuple(
                alert["headline"] for alert in answer.get("alerts") or ()
                if (alert.get("messageType") or {}).get("code") != "cancel"
                and isinstance(alert.get("headline"), str) and alert["headline"].strip()
            )
        except (QWeatherFailed, KeyError, TypeError, AttributeError) as e:
            log.warning("could not fetch the weather warnings: %s", e)
            self._warnings_failed[spot.cell] = self._clock()
            return None
        finally:
            self._fetching.pop(spot.cell, None)
        now = self._clock()
        self._warnings = {
            k: v for k, v in self._warnings.items() if now - v.fetched_at < KEPT_WARNINGS
        }
        self._warnings[spot.cell] = _KeptWarnings(headlines, now)
        return headlines

    async def _lookup(self, location: str, settings: QWeatherSettings | None) -> list[City]:
        answer = await self._get(
            "/geo/v2/city/lookup",
            {"location": location, "lang": "zh", "number": str(MAX_CITIES)},
            settings,
        )
        code = answer.get("code")
        if code == "404":
            return []
        if code != "200":
            raise QWeatherFailed(f"和风天气答复 {code}")
        try:
            return [
                City(
                    found["name"], found.get("adm2") or "", found.get("adm1") or "",
                    found.get("country") or "", float(found["lat"]), float(found["lon"]),
                )
                for found in answer.get("location") or ()
            ]
        except (KeyError, TypeError, ValueError) as e:
            raise QWeatherFailed(f"和风天气的答复看不懂：{type(e).__name__}") from None

    async def _get(
        self, path: str, params: dict[str, str], settings: QWeatherSettings | None = None
    ) -> dict:
        settings = settings or self._settings()
        if settings is None:
            raise QWeatherFailed("还没有配置和风天气")
        token = self._signed(settings)
        try:
            response = await self._http.get(
                f"https://{settings.host}{path}", params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as e:
            raise QWeatherFailed(f"连不上和风天气：{type(e).__name__}") from None
        try:
            answer = response.json()
        except ValueError:
            answer = None
        if response.status_code != 200 or not isinstance(answer, dict):
            raise QWeatherFailed(f"和风天气答复 HTTP {response.status_code}{_why(answer)}")
        return answer

    def _signed(self, settings: QWeatherSettings) -> str:
        now = self._clock()
        if self._token is not None:
            signed_for, token, until = self._token
            if signed_for == settings and now < until - timedelta(minutes=1):
                return token
        try:
            key = load_pem_private_key(private_key_pem(settings.private_key).encode(), None)
        except (ValueError, TypeError):
            raise QWeatherFailed("私钥读不出来，需要是 Ed25519 私钥（PEM）") from None
        if not isinstance(key, Ed25519PrivateKey):
            raise QWeatherFailed("私钥需要是 Ed25519 的")
        issued = int(now.timestamp()) - 30
        until = now + TOKEN_LASTS
        header = _b64(json.dumps({"alg": "EdDSA", "kid": settings.key_id}).encode())
        payload = _b64(json.dumps({
            "sub": settings.project_id, "iss": settings.developer_id,
            "iat": issued, "exp": int(until.timestamp()),
        }).encode())
        signing = f"{header}.{payload}"
        token = f"{signing}.{_b64(key.sign(signing.encode()))}"
        self._token = (settings, token, until)
        return token

    async def aclose(self) -> None:
        for fetching in list(self._fetching.values()):
            fetching.cancel()
        await self._http.aclose()


def _location(latitude: float, longitude: float) -> str:
    """A spot as QWeather takes it to look a city up: the longitude first."""
    return f"{longitude:.2f},{latitude:.2f}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _why(answer: object) -> str:
    """What QWeather said was wrong, if it said: its error's title and detail."""
    if isinstance(answer, dict) and isinstance(error := answer.get("error"), dict):
        said = "：".join(str(error[k]) for k in ("title", "detail") if error.get(k))
        return f"，{said}" if said else ""
    return ""
