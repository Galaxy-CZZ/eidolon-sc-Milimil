"""The group chats over HTTP: the user's groups, one group with its whole history, starting
one (拉群), renaming it, turning its scheduler on or off, dissolving it (解散), the user's own
line, and raising a topic by hand (the scheduler raises them on its own, about every four
hours)."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from eidolon.assembly import Backend
from eidolon.sessions import UserId


class NewGroup(BaseModel):
    """A group to start: what to call it and who is in it, by character id."""

    name: str = "群聊"
    character_ids: list[str] = []


class NameInput(BaseModel):
    """What to call the group now."""

    name: str


class OnInput(BaseModel):
    """Whether the group's scheduler runs."""

    on: bool


class SayInput(BaseModel):
    """What the user says in the group, as one of its members."""

    text: str


class MembersInput(BaseModel):
    """Who is in the group, by character id."""

    character_ids: list[str]


def add_group_routes(app: FastAPI, backend: Backend) -> None:
    groups = backend.groups

    async def shown(user_id: str, group_id: str) -> dict:
        group = await groups.read(user_id, group_id)
        if group is None:
            raise HTTPException(404, "群聊不存在")
        return group

    @app.get("/api/groups")
    async def list_groups(user_id: UserId) -> list[dict]:
        """The user's groups, newest first, each with a preview of its latest line."""
        return await groups.for_user(user_id)

    @app.post("/api/groups", status_code=201)
    async def create_group(body: NewGroup, user_id: UserId) -> dict:
        """Start a group with the chosen members (拉群), its first topic raised right away."""
        group_id = await groups.create(user_id, body.name, body.character_ids)
        if group_id is None:
            raise HTTPException(400, "群聊里至少要有一个人")
        return await shown(user_id, group_id)

    @app.get("/api/group/{group_id}")
    async def read_group(group_id: str, user_id: UserId) -> dict:
        """One group: its name, members, switch, and its whole history."""
        return await shown(user_id, group_id)

    @app.post("/api/group/{group_id}/name")
    async def rename_group(group_id: str, body: NameInput, user_id: UserId) -> dict:
        """Give the group a new name."""
        await groups.rename(user_id, group_id, body.name)
        return await shown(user_id, group_id)

    @app.post("/api/group/{group_id}/on")
    async def set_on(group_id: str, body: OnInput, user_id: UserId) -> dict:
        """Turn the group's scheduler on or off; nothing is deleted either way."""
        await groups.set_on(user_id, group_id, body.on)
        return await shown(user_id, group_id)

    @app.post("/api/group/{group_id}/members")
    async def set_members(group_id: str, body: MembersInput, user_id: UserId) -> dict:
        """Set who is in the group."""
        await groups.set_members(user_id, group_id, body.character_ids)
        return await shown(user_id, group_id)

    @app.post("/api/group/{group_id}/messages")
    async def say(group_id: str, body: SayInput, user_id: UserId) -> dict:
        """The user says a line, an ordinary member's, and the others answer by relevance."""
        await groups.say(user_id, group_id, body.text)
        return await shown(user_id, group_id)

    @app.post("/api/group/{group_id}/topic")
    async def raise_topic(group_id: str, user_id: UserId) -> dict:
        """Raise a topic now, as the scheduler does."""
        await groups.raise_topic(user_id, group_id)
        return await shown(user_id, group_id)

    @app.delete("/api/group/{group_id}", status_code=204)
    async def dissolve(group_id: str, user_id: UserId) -> None:
        """Dissolve the group (解散); it leaves the list and its history is hidden."""
        await groups.dissolve(user_id, group_id)
