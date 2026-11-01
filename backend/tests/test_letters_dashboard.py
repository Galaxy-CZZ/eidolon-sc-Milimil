"""The dashboard's「信」section (GLOSSARY.md「看板」「信」): over the dashboard's range, how many
letters were written, and how many times writing one failed. Not by character; and where the
deployer has letters off and none were recorded in the range, there is no section.

Driven through the backend's external API, the letters' ticks taken by hand, as in
`test_letters`."""

from dataclasses import replace

import httpx
import pytest

from eidolon.config import Settings
from eidolon.llm import LLMError
from tests.conftest import ClientFactory
from tests.fakes import FAKE_JUDGE, FakeIdentityProvider
from tests.test_activity_records import dashboard
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_letters import LETTERS, close_with_mano, written
from tests.test_reach_outs import backend_of


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With an admin, the judge model, affinity and gifts, and letters on in `.env`."""
    return replace(
        settings, admins=frozenset({ADMIN}), judge=FAKE_JUDGE, affinity_and_gifts=True,
        letters=True,
    )


async def section(client: httpx.AsyncClient, github: FakeIdentityProvider) -> dict | None:
    async with admin_beside(client, github) as admin:
        return (await dashboard(admin))["letters"]


async def test_it_counts_the_letters_written_and_the_times_writing_one_failed(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client, _, clock, _ = await close_with_mano(
        make_client, settings, LLMError("模型返回 503: overloaded"), written()
    )
    letters_of = backend_of(client).letters
    await letters_of.run_due()  # fails, tried again in 10 minutes
    failed = await section(client, github)
    clock.advance(minutes=10)

    await letters_of.run_due()

    assert failed == {"succeeded": 0, "failed": 1}
    assert await section(client, github) == {"succeeded": 1, "failed": 1}


async def test_with_letters_off_and_none_in_the_range_there_is_no_section(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client, _, clock, _ = await close_with_mano(make_client, settings, written())
    on_and_none = await section(client, github)
    await backend_of(client).letters.run_due()

    async with admin_beside(client, github) as admin:
        res = await admin.put(LETTERS, json={"enabled": False})
        assert res.status_code == 200, res.text
        off_with_one = (await dashboard(admin))["letters"]
        clock.advance(hours=25)  # out of the last 24 hours
        off_and_none = (await dashboard(admin))["letters"]

    assert on_and_none == {"succeeded": 0, "failed": 0}
    assert off_with_one == {"succeeded": 1, "failed": 0}
    assert off_and_none is None
