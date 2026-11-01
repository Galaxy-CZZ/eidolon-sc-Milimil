"""A user's own limits: an admin may set how many turns and calls an hour a user may take,
a number, unlimited, or 0, on their own keys only, each apart, with a note; whichever is
not set follows the deployment's. The user refused is told the number that holds for
them. Taken off, the deployment's hold again; deleted with the user."""

from dataclasses import replace
from datetime import datetime, timedelta

import httpx
import pytest

from eidolon.config import Settings, UsageLimits
from tests.browser import open_browser
from tests.conftest import ClientFactory
from tests.fakes import START, FakeClock, FakeIdentityProvider, FakeLLM, FakeLLMService, FakeSpeech
from tests.test_admin_users import ADMIN, admin_client, find
from tests.test_delete_account import rows_mentioning
from tests.test_own_llm import LLM
from tests.test_rate_limit import REPLY, post_turn
from tests.test_text_turn import send_turn, start_conversation


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With an admin, and the deployment's limits: 2 turns and 1 call an hour."""
    return replace(
        settings,
        admins=frozenset({ADMIN}),
        usage_limits=UsageLimits(turns_per_hour=2, calls_per_hour=1),
    )


async def set_limits(admin: httpx.AsyncClient, user_id: str, **limits) -> dict:
    res = await admin.put(f"/api/admin/users/{user_id}/limits", json=limits)
    assert res.status_code == 200, res.text
    return res.json()


async def test_a_user_set_to_1_turn_is_told_1_and_back_to_the_deployments_once_taken_off(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    clock = FakeClock()
    admin = await admin_client(make_client, github, clock=clock)
    producer = make_client(FakeLLM(REPLY, REPLY, REPLY), clock=clock)
    conversation_id = await start_conversation(producer)
    producer_id = (await find(admin, "producer"))["id"]

    shown = await set_limits(admin, producer_id, turns_per_hour=1, note="测试者，先收紧")
    await send_turn(producer, conversation_id, "早上好")
    clock.advance(minutes=10)
    refused = await post_turn(producer, conversation_id)

    limits = {"turns_per_hour": 1, "calls_per_hour": None, "note": "测试者，先收紧",
              "updated_at": START.isoformat(), "photos_per_hour": None, "visits_per_hour": None,
              "read_alouds_per_hour": None}
    assert shown["limits"] == limits
    assert (await find(admin, "producer"))["limits"] == limits
    assert (await find(admin, "boss"))["limits"] is None
    assert refused.status_code == 429
    assert "每小时 1 次" in refused.json()["detail"]
    assert datetime.fromisoformat(refused.json()["retry_at"]) == START + timedelta(hours=1)

    res = await admin.delete(f"/api/admin/users/{producer_id}/limits")

    assert res.status_code == 200, res.text
    assert res.json()["limits"] is None
    assert (await send_turn(producer, conversation_id, "在吗"))[-1]["type"] == "done"
    refused = await post_turn(producer, conversation_id)
    assert refused.status_code == 429
    assert "每小时 2 次" in refused.json()["detail"]


async def test_a_user_set_to_unlimited_turns_goes_past_the_deployments(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    admin = await admin_client(make_client, github)
    producer = make_client(FakeLLM(REPLY, REPLY, REPLY), clock=FakeClock())
    conversation_id = await start_conversation(producer)
    await set_limits(admin, (await find(admin, "producer"))["id"], turns_per_hour="unlimited")

    for n in range(3):
        assert (await send_turn(producer, conversation_id, "在吗"))[-1]["type"] == "done", n


async def test_a_user_set_to_0_turns_has_only_their_own_llm(
    make_client: ClientFactory, github: FakeIdentityProvider, own_llm: FakeLLMService
):
    admin = await admin_client(make_client, github)
    deployers = FakeLLM(REPLY)
    producer = make_client(deployers, clock=FakeClock())
    conversation_id = await start_conversation(producer)
    await set_limits(admin, (await find(admin, "producer"))["id"], turns_per_hour=0)

    refused = await post_turn(producer, conversation_id)

    assert refused.status_code == 429
    assert "只能用自带密钥" in refused.json()["detail"]
    assert refused.json()["retry_at"] is None
    assert "Retry-After" not in refused.headers
    assert deployers.prompts == []
    own_llm.llm = FakeLLM(REPLY)
    assert (await send_turn(producer, conversation_id, "在吗", own_llm=LLM))[-1]["type"] == "done"


async def test_with_only_turns_set_calls_follow_the_deployments(
    make_client: ClientFactory, github: FakeIdentityProvider, speech: FakeSpeech
):
    admin = await admin_client(make_client, github)
    producer = make_client(FakeLLM(REPLY), clock=FakeClock())
    conversation_id = await start_conversation(producer)
    await set_limits(admin, (await find(admin, "producer"))["id"], turns_per_hour="unlimited")
    async with open_browser() as first:
        assert (await first.call(producer, conversation_id=conversation_id)).status_code == 200

    async with open_browser() as second:
        refused = await second.call(producer, conversation_id=conversation_id)

    assert refused.status_code == 429
    assert "语音通话" in refused.json()["detail"] and "每小时 1 次" in refused.json()["detail"]


async def test_a_users_own_limits_are_deleted_with_them(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    admin = await admin_client(make_client, github)
    make_client(FakeLLM())
    producer_id = (await find(admin, "producer"))["id"]
    await set_limits(admin, producer_id, calls_per_hour=3, note="不会留下")

    await admin.delete(f"/api/admin/users/{producer_id}")

    assert rows_mentioning(settings.database_path, producer_id) == {}
    assert rows_mentioning(settings.database_path, "不会留下") == {}
