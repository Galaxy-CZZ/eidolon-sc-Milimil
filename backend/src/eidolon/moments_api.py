"""Moments over HTTP (GLOSSARY.md「朋友圈」): `/api/moments` reads the signed-in user's
timeline, the latest first, all of it at once, which has them seen; `/api/moments/unseen`
says whether anything that lights the dot on 「朋友圈」 has shown since.
`/api/moments/{id}/image` is the picture of one on it (GLOSSARY.md「配图」, ADR-0024), the
user's alone to read: to anyone else, admins too, there is no such picture (404), and it is
the browser's alone to keep, never a shared cache's.
`/api/moments/{id}/like` likes one (PUT) or no longer (DELETE), as often as he likes;
`/api/moments/{id}/comment` comments on one (POST), once (409 again), 1 to 140 characters but
for the spaces around them (422 else), or deletes the comment (DELETE). A moment not on his
timeline, another's, not shown yet or gone, is none (404). While the deployer has moments
off, or the user their own switch for them, each is refused with 409."""

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from eidolon.assembly import Backend
from eidolon.moments import AlreadyCommented, CommentInvalid, MomentsOff, NoMoment
from eidolon.sessions import UserId


_PICTURE_CACHE = {"Cache-Control": "private, max-age=31536000, immutable"}
"""A moment's picture never changes once posted."""


class CommentInput(BaseModel):
    """The producer's comment on a moment, as he wrote it."""

    text: str


def add_moment_routes(app: FastAPI, backend: Backend) -> None:
    @app.exception_handler(MomentsOff)
    async def moments_off(_: Request, e: MomentsOff) -> JSONResponse:
        return JSONResponse({"detail": "朋友圈没有开放"}, status_code=409)

    @app.exception_handler(NoMoment)
    async def no_moment(_: Request, e: NoMoment) -> JSONResponse:
        return JSONResponse({"detail": "动态不存在"}, status_code=404)

    @app.get("/api/moments")
    async def timeline(user_id: UserId) -> dict:
        """The user's moments that have shown within the last 30 days, the latest first."""
        map_site = backend.moments.map_site
        return {"moments": [m.shown(map_site) for m in await backend.moments.timeline(user_id)]}

    @app.get("/api/moments/unseen")
    async def unseen(user_id: UserId) -> dict:
        """Whether a moment, or her reply to his comment, has shown since he last read the
        timeline (`/api/moments`), on any device."""
        return {"unseen": await backend.moments.unseen(user_id)}

    @app.get("/api/moments/{moment_id}/image")
    async def read_picture(moment_id: int, user_id: UserId) -> Response:
        image = await backend.moments.picture(user_id, moment_id)
        if image is None:
            raise HTTPException(404, "配图不存在")
        return Response(image, media_type="image/webp", headers=_PICTURE_CACHE)

    @app.put("/api/moments/{moment_id}/like", status_code=204)
    async def like(moment_id: int, user_id: UserId) -> None:
        await backend.moments.like(user_id, moment_id, True)

    @app.delete("/api/moments/{moment_id}/like", status_code=204)
    async def unlike(moment_id: int, user_id: UserId) -> None:
        await backend.moments.like(user_id, moment_id, False)

    @app.post("/api/moments/{moment_id}/comment", status_code=201)
    async def comment(moment_id: int, body: CommentInput, user_id: UserId) -> dict:
        """The comment, as it is kept."""
        try:
            return (await backend.moments.comment(user_id, moment_id, body.text)).shown()
        except CommentInvalid:
            raise HTTPException(422, "评论需要 1 到 140 个字") from None
        except AlreadyCommented:
            raise HTTPException(409, "已经评论过这条动态了") from None

    @app.delete("/api/moments/{moment_id}/comment", status_code=204)
    async def uncomment(moment_id: int, user_id: UserId) -> None:
        await backend.moments.uncomment(user_id, moment_id)
