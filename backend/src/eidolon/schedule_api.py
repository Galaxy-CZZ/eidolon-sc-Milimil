"""Schedules over HTTP (GLOSSARY.md「日程」), for users who agreed to the terms: the user's
week and the next once published at `/api/schedule`, the week's jobs drawn as first read;
saving jobs into a week at `/api/schedule/weeks/{week}`, the week named by its Monday's date.
Both in the producer's time zone, their profile's, else their device's (`X-Timezone`). What
is saved cannot be changed or taken back: there is no route to. While schedules are off,
reading says so, and saving is refused with 409 and `schedule_closed`."""

from datetime import date

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from eidolon.assembly import Backend
from eidolon.job_list import SLOTS
from eidolon.schedule import DAYS, Placement, ScheduleClosed
from eidolon.sessions import DeviceTimezone, UserId


class PlacementInput(BaseModel):
    job_id: str
    day: int = Field(ge=0, lt=DAYS)
    """0 for Monday."""
    slot: int = Field(ge=0, lt=len(SLOTS))
    """The slot the job starts in, 0 for the morning."""


class SaveInput(BaseModel):
    placements: list[PlacementInput]
    """Those new in this saving, in the order to save them."""


class UnsaveInput(BaseModel):
    jobs: list[str]
    """Which of the week's jobs to take back out of the schedule."""


def add_schedule_routes(app: FastAPI, backend: Backend) -> None:
    schedules = backend.schedules

    @app.exception_handler(ScheduleClosed)
    async def schedule_closed(_: Request, e: ScheduleClosed) -> JSONResponse:
        return JSONResponse({"detail": str(e), "schedule_closed": True}, status_code=409)

    @app.get("/api/schedule")
    async def read(user_id: UserId, device_timezone: DeviceTimezone = None) -> dict:
        """The user's week and the next once published, each with its jobs and what the user
        saved of it; or only that schedules are off."""
        view = await schedules.read(user_id, device_timezone)
        return view.shown() if view is not None else {"enabled": False}

    @app.post("/api/schedule/weeks/{week}")
    async def save(
        week: str, body: SaveInput, user_id: UserId, device_timezone: DeviceTimezone = None
    ) -> dict:
        """Save what can be of the placements into the week: those saved, and those handed
        back, each with why."""
        try:
            monday = date.fromisoformat(week)
        except ValueError:
            raise HTTPException(404, "没有这一周") from None
        if monday.weekday() != 0 or monday.isoformat() != week:
            raise HTTPException(404, "没有这一周")
        placements = [Placement(p.job_id, p.day, p.slot) for p in body.placements]
        return (await schedules.save(user_id, monday, placements, device_timezone)).shown()

    @app.delete("/api/schedule/weeks/{week}")
    async def unsave(
        week: str, body: UnsaveInput, user_id: UserId, device_timezone: DeviceTimezone = None
    ) -> dict:
        """Take those of the week's jobs out of the user's schedule, so that the slots they
        held are free: the way to move one, or to lay the week out again."""
        try:
            monday = date.fromisoformat(week)
        except ValueError:
            raise HTTPException(404, "没有这一周") from None
        if monday.weekday() != 0 or monday.isoformat() != week:
            raise HTTPException(404, "没有这一周")
        view = await schedules.unsave(
            user_id, monday, [job for job in body.jobs], device_timezone
        )
        return view.shown()
