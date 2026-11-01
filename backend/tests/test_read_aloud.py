"""Her words read aloud (GLOSSARY.md「朗读」): a reply of hers or a reach-out, in any of the
user's conversations with her, voiced whole in one request to Fish Audio's HTTP API at its
best quality, a line to each segment, its delivery cues as the model voicing it reads them
and the readings as its pronunciation dictionary, and answered as mp3, nothing of it kept.
On the user's own key for speech synthesis with the model they chose, counting towards
nothing; else on the deployer's with the deployer's model, counting towards the user's
read-alouds an hour, given back if Fish Audio fails. Each is a service call of speech
synthesis, billed as a call's is.

Driven through the backend's external API, Fish Audio faked at its transport."""

import sqlite3
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest

from eidolon.config import Settings, UsageLimits
from eidolon.reply_format import DIRECTED_FORMAT_INSTRUCTIONS
from tests.conftest import CharacterConfig, ClientFactory, activity_in
from tests.fakes import (
    DEPLOYER_FISH_KEY,
    FAKE_JUDGE,
    START,
    FakeClock,
    FakeFishAudio,
    FakeLLM,
    system_of,
)
from tests.test_affinity import keep
from tests.test_own_speech_keys import MY_FISH
from tests.test_reach_outs_in_turns import reached_out
from tests.test_text_turn import send_turn, start_conversation

SHY = "<ja>[shyly] えへへ……</ja><zh>嘿嘿……</zh><ja>283プロ、<whisper>大好き</whisper>だよ</ja><zh>最喜欢283了</zh>"
"""Her reply: a cue for the whole of its first segment, a paired tag in its second, and a
name with a reading."""
READING = '[[readings]]\nwritten = "283プロ"\nkana = "つばさぷろ"\nphonemes = "tsu1ba0sa0pu0ro0"\n'
DICTIONARY = [{"items": [{"key": "283プロ", "value": "tsu1ba0sa0pu0ro0", "case_sensitive": True}]}]
MINE = {"own_keys": {"tts": {"api_key": MY_FISH, "model": "drama-3"}}}


def faked(fish: FakeFishAudio) -> httpx.MockTransport:
    return httpx.MockTransport(fish.handle)


async def her_reply(client: httpx.AsyncClient, conversation: str) -> int:
    """The id of her last reply in the conversation."""
    record = (await client.get(f"/api/conversations/{conversation}/messages")).json()
    return [m for m in record if m.get("role") == "character"][-1]["id"]


async def read_aloud(
    client: httpx.AsyncClient, conversation: str, message: int, body: dict | None = None
) -> httpx.Response:
    return await client.post(
        f"/api/conversations/{conversation}/messages/{message}/read-aloud", json=body or {}
    )


async def test_her_reply_is_voiced_whole_at_fish_audios_best_quality_cues_and_readings_and_all(
    make_client: ClientFactory, settings: Settings, characters: CharacterConfig
):
    characters.write("readings.toml", READING)
    fish = FakeFishAudio()
    clock = FakeClock()
    client = make_client(FakeLLM([SHY]), clock=clock, fish_transport=faked(fish))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "喜欢事务所吗")

    res = await read_aloud(client, conversation, await her_reply(client, conversation))

    # The deployer's model reads no paired tags: they are left out, the words kept. A cue
    # opening a line goes without the space after it, as in calls.
    said = "[shyly]えへへ……\n283プロ、大好きだよ"
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "audio/mpeg"
    assert res.headers["cache-control"] == "no-store"
    assert res.content == FakeFishAudio.audio(said, "mano-voice")
    assert fish.requests == [{
        "key": DEPLOYER_FISH_KEY, "model": "s2.1-pro-free", "text": said,
        "reference_id": "mano-voice", "format": "mp3", "sample_rate": 44100,
        "mp3_bitrate": 128, "latency": "normal", "pronunciation_dictionary": DICTIONARY,
    }]
    async with activity_in(settings.database_path, clock) as activity:
        _, calls = await activity.since(START - timedelta(minutes=1))
    [tts] = [c for c in calls if c.service == "tts"]
    assert (tts.provider, tts.model, tts.own_key, tts.error) == (
        FakeFishAudio.HOST, "s2.1-pro-free", False, None
    )
    assert (tts.usage_unit, tts.usage_input) == ("bytes", len(said.encode()))


async def test_on_the_users_own_key_it_is_voiced_with_their_model_and_billed_as_it_bills(
    make_client: ClientFactory, settings: Settings
):
    fish = FakeFishAudio()
    clock = FakeClock()
    client = make_client(FakeLLM([SHY]), clock=clock, fish_transport=faked(fish))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "喜欢事务所吗")

    res = await read_aloud(client, conversation, await her_reply(client, conversation), MINE)

    # Drama 3 reads the paired tags.
    said = "[shyly]えへへ……\n283プロ、<whisper>大好き</whisper>だよ"
    assert res.status_code == 200, res.text
    assert [(r["key"], r["model"], r["text"]) for r in fish.requests] == [(MY_FISH, "drama-3", said)]
    async with activity_in(settings.database_path, clock) as activity:
        _, calls = await activity.since(START - timedelta(minutes=1))
    [tts] = [c for c in calls if c.service == "tts"]
    assert (tts.model, tts.own_key, tts.usage_unit, tts.usage_input) == (
        "drama-3", True, "characters", len(said)
    )


async def test_read_alouds_on_the_deployers_key_are_limited_an_hour_apart_from_turns(
    make_client: ClientFactory, settings: Settings
):
    two = replace(settings, usage_limits=UsageLimits(read_alouds_per_hour=2))
    clock = FakeClock()
    client = make_client(
        FakeLLM([SHY], [SHY]), settings=two, clock=clock, fish_transport=faked(FakeFishAudio())
    )
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "喜欢事务所吗")
    reply = await her_reply(client, conversation)

    first = await read_aloud(client, conversation, reply)
    mine = await read_aloud(client, conversation, reply, MINE)
    clock.advance(minutes=10)
    second = await read_aloud(client, conversation, reply)
    refused = await read_aloud(client, conversation, reply)
    still_mine = await read_aloud(client, conversation, reply, MINE)
    turn = await send_turn(client, conversation, "再说一遍")

    assert [r.status_code for r in (first, mine, second, still_mine)] == [200] * 4
    assert refused.status_code == 429
    assert refused.json() == {
        "detail": "这一小时的朗读次数已经用完了（每小时 2 次）",
        "retry_at": (START + timedelta(hours=1)).isoformat(),
    }
    assert turn[-1]["type"] == "done"


async def test_fish_audio_failing_is_given_back_and_on_the_users_own_key_says_why_key_masked(
    make_client: ClientFactory, settings: Settings
):
    one = replace(settings, usage_limits=UsageLimits(read_alouds_per_hour=1))
    fish = FakeFishAudio()
    fish.refuses["mano-voice"] = 503

    def answer(request: httpx.Request) -> httpx.Response:
        key = request.headers["authorization"].removeprefix("Bearer ")
        if key == MY_FISH:  # a service may repeat the key it turns down
            return httpx.Response(401, json={"message": f"invalid api key {key}"})
        return fish.handle(request)

    clock = FakeClock()
    client = make_client(
        FakeLLM([SHY]), settings=one, clock=clock, fish_transport=httpx.MockTransport(answer)
    )
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "喜欢事务所吗")
    reply = await her_reply(client, conversation)

    failed = await read_aloud(client, conversation, reply)
    own_failed = await read_aloud(client, conversation, reply, MINE)
    del fish.refuses["mano-voice"]
    after = await read_aloud(client, conversation, reply)

    assert (failed.status_code, failed.json()) == (502, {"detail": "没能合成语音，过一会儿再试"})
    assert own_failed.status_code == 502
    own = own_failed.json()
    assert own["code"] == "own_key"
    assert own["detail"].startswith("你的语音合成（Fish Audio）密钥调用失败：Fish Audio 返回 401")
    assert MY_FISH not in own["detail"] and "***" in own["detail"]
    assert after.status_code == 200, after.text  # the failed one was given back
    async with activity_in(settings.database_path, clock) as activity:
        _, calls = await activity.since(START - timedelta(minutes=1))
    assert [c.error for c in calls if c.service == "tts"] == ["server_error", "unauthorized", None]


async def test_only_her_words_in_the_users_own_conversations_are_read_aloud(
    make_client: ClientFactory,
):
    fish = FakeFishAudio()
    client = make_client(FakeLLM([SHY]), fish_transport=faked(fish))
    other = make_client(FakeLLM(), user="other", fish_transport=faked(fish))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "喜欢事务所吗")
    reply = await her_reply(client, conversation)
    elsewhere = await start_conversation(client, "kogane")
    record = (await client.get(f"/api/conversations/{conversation}/messages")).json()
    [users] = [m["id"] for m in record if m.get("role") == "user"]

    assert (await read_aloud(client, conversation, users)).status_code == 404, "the user's words"
    assert (await read_aloud(client, elsewhere, reply)).status_code == 404, "another conversation's"
    assert (await read_aloud(other, conversation, reply)).status_code == 404, "another user's"
    assert fish.requests == []


async def test_without_the_deployers_key_only_the_users_own_reads_aloud(
    make_client: ClientFactory,
):
    fish = FakeFishAudio()
    client = make_client(FakeLLM([SHY]), voice_configured=False, fish_transport=faked(fish))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "喜欢事务所吗")
    reply = await her_reply(client, conversation)

    refused = await read_aloud(client, conversation, reply)
    mine = await read_aloud(client, conversation, reply, MINE)

    assert (await client.get("/api/account")).json()["deployer_tts"] is False
    assert (refused.status_code, refused.json()) == (503, {"detail": "这个部署没有语音合成，朗读不了"})
    assert mine.status_code == 200, mine.text
    assert [r["key"] for r in fish.requests] == [MY_FISH]


async def test_reading_aloud_is_no_turn_so_a_past_conversation_she_ended_is_read_while_she_cools(
    make_client: ClientFactory, settings: Settings
):
    cooling = replace(settings, judge=FAKE_JUDGE, affinity_and_gifts=True)
    clock = FakeClock()
    client = make_client(FakeLLM([SHY]), settings=cooling, clock=clock, fish_transport=faked(FakeFishAudio()))
    ended = await start_conversation(client)
    await send_turn(client, ended, "喜欢事务所吗")
    reply = await her_reply(client, ended)
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            "INSERT INTO conversation_events (conversation_id, kind, created_at) VALUES (?, 'ended', ?)",
            (ended, clock.now.isoformat()),
        )
    current = await start_conversation(client)
    keep(settings.database_path, "producer", 0, clock.now, cooling=True)

    turn = await client.post(f"/api/conversations/{current}/turns", json={"text": "在吗"})
    res = await read_aloud(client, ended, reply)

    assert turn.status_code == 409  # she is cooling down
    assert res.status_code == 200, res.text


@pytest.fixture
def directed(settings: Settings) -> Settings:
    """Reach-outs on, the deployer voicing with Drama 3."""
    return replace(settings, reach_outs=True, fish_audio_model="drama-3")


async def test_her_reach_out_is_read_aloud_as_written_for_the_deployers_model(
    make_client: ClientFactory, directed: Settings
):
    fish = FakeFishAudio()
    client, llm, _, conversation, _ = await reached_out(
        make_client, directed, fish_transport=faked(fish)
    )
    record = (await client.get(f"/api/conversations/{conversation}/messages")).json()
    [reach_out] = [e["id"] for e in record if e.get("type") == "reach_out"]

    res = await client.post(
        f"/api/conversations/{conversation}/reach-outs/{reach_out}/read-aloud", json={}
    )
    missing = await client.post(
        f"/api/conversations/{conversation}/reach-outs/{reach_out + 1}/read-aloud", json={}
    )

    assert DIRECTED_FORMAT_INSTRUCTIONS in system_of(llm.prompts[1])  # her reach-out's
    assert res.status_code == 200, res.text
    assert [(r["model"], r["text"]) for r in fish.requests] == [
        ("drama-3", "[happily]プロデューサーさん！\nレッスン終わったよ")
    ]
    assert missing.status_code == 404
