"""Finding the producer's city over HTTP (GLOSSARY.md「制作人档案」), on the deployer's QWeather
account: `/api/cities?q=` the cities by a name, `/api/cities/nearest?latitude=&longitude=` the
one nearest where the browser says the user is, its spot never kept. The browser never asks
QWeather itself. Without the account there are no cities to find (409); QWeather failing, 502.
Each user may ask `PER_HOUR` times an hour at most (429), so that no one spends the account's
monthly allowance."""

from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query

from eidolon.assembly import Backend
from eidolon.clock import Clock
from eidolon.qweather import QWeatherFailed
from eidolon.sessions import UserId

PER_HOUR = 60
"""How many times a user may look for a city an hour."""

MAX_QUERY = 40
"""How long a name looked for may be, in characters."""


class _Asking:
    """How often each user has asked in the last hour, as `clock` tells."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._asked: dict[str, deque[datetime]] = {}

    def ask(self, user_id: str) -> None:
        """Count the user's asking; raises 429 past `PER_HOUR` in the hour."""
        now = self._clock()
        asked = self._asked.setdefault(user_id, deque())
        while asked and now - asked[0] >= timedelta(hours=1):
            asked.popleft()
        if len(asked) >= PER_HOUR:
            raise HTTPException(429, "找城市太频繁了，过一会儿再试")
        asked.append(now)


def add_city_routes(app: FastAPI, backend: Backend) -> None:
    qweather = backend.config.qweather
    asking = _Asking(backend.clock)

    def ready(user_id: str) -> None:
        if not qweather.on:
            raise HTTPException(409, "这个部署没有配置和风天气")
        asking.ask(user_id)

    @app.get("/api/cities")
    async def search(
        user_id: UserId, q: str = Query(min_length=1, max_length=MAX_QUERY)
    ) -> dict:
        ready(user_id)
        if not (name := q.strip()):
            return {"cities": []}
        try:
            return {"cities": [asdict(c) for c in await qweather.search(name)]}
        except QWeatherFailed as e:
            raise HTTPException(502, str(e)) from None

    @app.get("/api/cities/nearest")
    async def nearest(
        user_id: UserId,
        latitude: float = Query(ge=-90, le=90),
        longitude: float = Query(ge=-180, le=180),
    ) -> dict:
        ready(user_id)
        try:
            city = await qweather.nearest(latitude, longitude)
        except QWeatherFailed as e:
            raise HTTPException(502, str(e)) from None
        return {"city": asdict(city) if city is not None else None}
