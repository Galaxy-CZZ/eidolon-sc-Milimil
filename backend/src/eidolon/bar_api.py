"""The bar over HTTP (GLOSSARY.md「酒吧」「光顾」), for users who agreed to the terms:
`/api/bar` reads it; `/api/bar/visits` begins a visit, each of whose drinks is served at
`/api/bar/visits/{visit_id}/serves`, on the keys it came in with, the call it stopped before,
failing, tried again at `/api/bar/visits/{visit_id}/retry`, and which is left by deleting it.
Beginning a visit, serving a drink and trying again answer with the call they set off, as
server-sent events (`bar.BarEvent`): the call tried again from its first line on, with
nothing sent before it.

Refused: coming in while the bar is closed (409 `bar_closed`), or over the limit (429, as any
use is); any visit but the user's under way (410 `visit_gone`); serving while she is not
waiting for a drink (409 `not_waiting`), or what is none of the drinks (422
`broken_drink`); trying again while no call failed (409 `not_failed`)."""

import json
from collections.abc import AsyncIterator
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, model_validator
from starlette.types import Receive, Scope, Send

from eidolon.account_api import OwnKeysInput
from eidolon.assembly import Backend
from eidolon.bar import BarCall, BarClosed, BrokenDrink, NotFailed, NotWaiting, VisitGone
from eidolon.drink_catalog import Mixture
from eidolon.greetings import FishAudioSettings, _voice
from eidolon.own_keys import BroughtKeys
from eidolon.readings import load_readings, pronunciation_dictionary, readings_path, used_in
from eidolon.sessions import DeviceTimezone, UserId


class VisitInput(BaseModel):
    own_keys: OwnKeysInput | None = None
    """The user's own keys, which their browser keeps, for the visit's calls to run on, as
    text turns bring them; only the LLMs are used, held until the visit is over."""


class ServeInput(BaseModel):
    """What the bar counter holds as it is served: the parts of each ingredient, whether on
    ice and aged, and how it was shaken; or, `method` being `bottle`, which bottled drink."""

    method: Literal["mix", "blend", "bottle"]
    bottle: str | None = None
    adelhyde: int = 0
    bronson_extract: int = 0
    powdered_delta: int = 0
    flanergide: int = 0
    karmotrine: int = 0
    ice: bool = False
    aged: bool = False

    @model_validator(mode="after")
    def _bottle_or_not(self) -> "ServeInput":
        if (self.method == "bottle") != (self.bottle is not None):
            raise ValueError("瓶装的要说是哪一瓶，调制的不要说")
        return self

    def served(self) -> Mixture | str:
        if self.method == "bottle":
            assert self.bottle is not None
            return self.bottle
        return Mixture(
            self.adelhyde, self.bronson_extract, self.powdered_delta, self.flanergide,
            self.karmotrine, self.ice, self.aged, self.method,
        )


class TtsInput(BaseModel):
    """A line of hers to voice: which character, and what she says."""

    character_id: str
    text: str


def add_bar_routes(app: FastAPI, backend: Backend) -> None:
    bar = backend.bar
    # 她念名字的读音（readings.toml），照招呼和通话一样交给 Fish Audio。
    readings = load_readings(readings_path(backend.settings.characters_path))

    def refused(status: int, code: str):
        async def handler(_: Request, e: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(e), "code": code}, status_code=status)
        return handler

    app.add_exception_handler(BarClosed, refused(409, "bar_closed"))
    app.add_exception_handler(VisitGone, refused(410, "visit_gone"))
    app.add_exception_handler(NotWaiting, refused(409, "not_waiting"))
    app.add_exception_handler(NotFailed, refused(409, "not_failed"))
    app.add_exception_handler(BrokenDrink, refused(422, "broken_drink"))

    @app.get("/api/bar")
    async def read(user_id: UserId) -> dict:
        """Whether the bar is open and, if it is, its drinks in catalog order, and whether a
        visit done today would be rewarded."""
        return await bar.read(user_id)

    @app.post("/api/bar/tts")
    async def tts(body: TtsInput, user_id: UserId) -> Response:
        """`text` said in the character's voice, as mp3; 422 for a character the bar has not,
        or nothing said; 503 when this deployment has no speech synthesis."""
        character = bar.character(body.character_id)
        if character is None or not body.text.strip() or not character.voice_id.strip():
            raise HTTPException(422, "要说是哪位角色、说什么")
        try:
            fish = FishAudioSettings.from_env()
        except Exception:
            raise HTTPException(503, "这个部署没有配语音合成") from None
        dictionary = pronunciation_dictionary(used_in(body.text, readings))
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                audio = await _voice(client, fish, body.text, character.voice_id, dictionary)
            except Exception as e:
                raise HTTPException(502, f"语音合成失败：{e}") from None
        return Response(audio, media_type="audio/mpeg")

    @app.post("/api/bar/visits")
    async def enter(
        body: VisitInput, user_id: UserId, device_timezone: DeviceTimezone = None
    ) -> StreamingResponse:
        """A visit begun, any of the user's under way done away with."""
        return _events(await bar.enter(user_id, _brought(body.own_keys), device_timezone))

    @app.post("/api/bar/visits/{visit_id}/serves")
    async def serve(visit_id: str, body: ServeInput, user_id: UserId) -> StreamingResponse:
        """A drink served her."""
        return _events(await bar.serve(user_id, visit_id, body.served()))

    @app.post("/api/bar/visits/{visit_id}/retry")
    async def retry(visit_id: str, user_id: UserId) -> StreamingResponse:
        """The call the visit stopped before, failing, tried again."""
        return _events(await bar.retry(user_id, visit_id))

    @app.delete("/api/bar/visits/{visit_id}", status_code=204)
    async def leave(visit_id: str, user_id: UserId) -> None:
        """The visit left: over, and not to be come back to."""
        await bar.leave(user_id, visit_id)


def _brought(own_keys: OwnKeysInput | None) -> BroughtKeys:
    return own_keys.brought() if own_keys else BroughtKeys()


def _events(call: BarCall) -> StreamingResponse:
    async def sent() -> AsyncIterator[str]:
        async for event in call:
            yield f"data: {json.dumps(event.shown(), ensure_ascii=False)}\n\n"

    return _CallResponse(sent(), call)


class _CallResponse(StreamingResponse):
    """A call's events, the call closed once they are sent or the page is gone, even gone
    before they began, when the stream of them never runs: so that a call left part-way stops
    at once, and its visit is left."""

    def __init__(self, events: AsyncIterator[str], call: BarCall) -> None:
        super().__init__(
            events, media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        self._call = call

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._call.aclose()
