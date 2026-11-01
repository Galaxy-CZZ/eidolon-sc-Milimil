"""Users once had to bring their own LLM where the deployer required it (「必须自带 LLM」,
since taken out; no turn or call is refused for want of it, and only the limit holds them).
What is left of it from then: `.env`'s `EIDOLON_OWN_LLM_REQUIRED`, only warned of as the
server starts, and a database that kept the admin console's switch and a user's own limits
letting them use the deployer's LLM, forgetting both as it is opened. Driven through the
backend's external API."""

import logging
import sqlite3
from dataclasses import replace

import pytest

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import START, FakeClock, FakeIdentityProvider, FakeLLM
from tests.test_admin_users import ADMIN, admin_client, details, find


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, admins=frozenset({ADMIN}))


def limits_url(user_id: str) -> str:
    return f"/api/admin/users/{user_id}/limits"


async def test_a_database_from_then_forgets_the_switch_and_the_letting_and_keeps_the_rest(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    admin = await admin_client(make_client, github, clock=clock)
    make_client(FakeLLM(), clock=clock)
    producer_id = (await find(admin, "producer"))["id"]
    with sqlite3.connect(settings.database_path) as db:  # kept as they were then
        db.execute(
            "ALTER TABLE user_limits ADD COLUMN deployer_llm_allowed INTEGER NOT NULL DEFAULT 0"
        )
        db.execute(
            "INSERT INTO user_limits (user_id, turns_per_hour, calls_per_hour, note,"
            " updated_at, deployer_llm_allowed) VALUES (?, -1, NULL, '老数据', ?, 1)",
            (producer_id, START.isoformat()),
        )
        db.executemany(
            "INSERT INTO config_overrides (name, value, updated_at) VALUES (?, ?, ?)",
            [
                ("limits.own_llm_required", "true", START.isoformat()),
                ("limits.turns_per_hour", "3", START.isoformat()),
            ],
        )
    db.close()

    for start in ["first", "again"]:
        upgraded = await admin_client(make_client, github, clock=clock)

        with sqlite3.connect(settings.database_path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(user_limits)")}
            overrides = [row[0] for row in db.execute("SELECT name FROM config_overrides")]
        db.close()
        assert "deployer_llm_allowed" not in columns, start
        assert overrides == ["limits.turns_per_hour"], start
        assert (await details(upgraded, producer_id))["limits"] == {
            "turns_per_hour": "unlimited", "calls_per_hour": None, "note": "老数据",
            "updated_at": START.isoformat(), "photos_per_hour": None, "visits_per_hour": None,
            "read_alouds_per_hour": None,
        }, start
        limits = (await upgraded.get("/api/admin/config")).json()["limits"]
        assert limits["override"] == {"turns_per_hour": 3}, start

    changed = await upgraded.put(limits_url(producer_id), json={"calls_per_hour": 2})
    assert changed.status_code == 200, changed.text
    assert changed.json()["limits"]["calls_per_hour"] == 2


def test_env_still_setting_it_starts_all_the_same_warning_it_does_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("CHAT_LLM_API_KEY", "sk-deployer")
    monkeypatch.setenv("CHAT_LLM_MODEL", "deployer-model")
    caplog.set_level(logging.WARNING)
    monkeypatch.delenv("EIDOLON_OWN_LLM_REQUIRED", raising=False)
    Settings.from_env()
    assert "EIDOLON_OWN_LLM_REQUIRED" not in caplog.text

    # Left empty, as `.env.example` had it.
    monkeypatch.setenv("EIDOLON_OWN_LLM_REQUIRED", "")
    Settings.from_env()
    assert "EIDOLON_OWN_LLM_REQUIRED" in caplog.text
