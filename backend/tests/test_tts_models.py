"""Fish Audio's models (`config.FishAudioModel`): the deployer's, as `.env` or the admin
console has it, and the one a user chose with their own key, the free one unless they
chose another. Fish Audio voices a model it does not know with its paid S2.1 Pro, saying
nothing, so only those there are are taken. A paid one needs API credit: a key without any
is turned down as it is tried, rather than in a call. A call voiced with Drama 3 has her
direct her voice as it reads (`reply_format.DIRECTED_FORMAT_INSTRUCTIONS`), and is billed
for the characters it is given (see test_call_records); a text turn, as the model it would be
read aloud with reads (GLOSSARY.md「朗读」): that of the user's own key, which their browser
names, else the deployer's."""

from dataclasses import replace

import httpx
import pytest

from eidolon.call import SpeechServices
from eidolon.config import DEFAULT_FISH_AUDIO_MODEL, Settings, fish_audio_model_from_env
from eidolon.own_keys import OwnKeyRejected
from eidolon.reply_format import DIRECTED_FORMAT_INSTRUCTIONS, FORMAT_INSTRUCTIONS
from tests.browser import Browser
from tests.conftest import ClientFactory
from tests.fakes import DEPLOYER_FISH_KEY, FakeLLM, FakeSpeech, system_of
from tests.test_own_speech_keys import MY_FISH
from tests.test_text_turn import send_turn, start_conversation

CHECK = "/api/account/keys/tts/check"


@pytest.fixture
def paid(settings: Settings) -> Settings:
    """The deployer voicing with a paid model."""
    return replace(settings, fish_audio_model="s2.1-pro")


async def test_a_users_own_fish_key_speaks_with_the_model_they_chose(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser, paid: Settings
):
    client = make_client(FakeLLM(), settings=paid)

    await browser.call(
        client,
        conversation_id=await start_conversation(client),
        own_keys={"tts": {"api_key": MY_FISH, "model": "drama-3"}},
    )

    assert [(tts.api_key, tts.model) for tts in speech.ttss] == [(MY_FISH, "drama-3")]


async def test_an_own_fish_key_kept_before_models_could_be_chosen_speaks_with_the_free_one(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser, paid: Settings
):
    client = make_client(FakeLLM(), settings=paid)

    await browser.call(
        client, conversation_id=await start_conversation(client), own_keys={"tts": {"api_key": MY_FISH}}
    )

    assert [(tts.api_key, tts.model) for tts in speech.ttss] == [(MY_FISH, DEFAULT_FISH_AUDIO_MODEL)]


async def test_the_deployers_fish_key_speaks_with_the_deployers_model(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser, paid: Settings
):
    client = make_client(FakeLLM(), settings=paid)

    await browser.call(client, conversation_id=await start_conversation(client))

    assert [(tts.api_key, tts.model) for tts in speech.ttss] == [(DEPLOYER_FISH_KEY, "s2.1-pro")]


async def test_a_call_voiced_with_drama_3_has_her_direct_her_voice_and_a_text_turn_read_aloud_with_another_not(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    llm = FakeLLM(
        ["<ja>うん</ja><zh>嗯</zh>"],
        ["<ja>[small laugh] <whisper>内緒</whisper>だよ</ja><zh>保密哦</zh>"],
    )
    client = make_client(llm)
    conversation_id = await start_conversation(client)
    await send_turn(client, conversation_id, "嗯")
    await browser.call(
        client,
        conversation_id=conversation_id,
        own_keys={"tts": {"api_key": MY_FISH, "model": "drama-3"}},
    )
    await browser.connect()

    await speech.stts[-1].hear("秘密？")
    await browser.turn()

    typed, called = (system_of(prompt) for prompt in llm.prompts)
    assert FORMAT_INSTRUCTIONS in typed and DIRECTED_FORMAT_INSTRUCTIONS not in typed
    assert DIRECTED_FORMAT_INSTRUCTIONS in called


async def test_a_text_turn_has_her_write_cues_as_its_reply_would_be_read_aloud(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(["<ja>うん</ja><zh>嗯</zh>"], ["<ja>うん</ja><zh>嗯</zh>"])
    client = make_client(llm, settings=replace(settings, fish_audio_model="drama-3"))
    conversation_id = await start_conversation(client)

    await send_turn(client, conversation_id, "嗯")
    await send_turn(client, conversation_id, "嗯", read_aloud_model=DEFAULT_FISH_AUDIO_MODEL)

    deployers, own = (system_of(prompt) for prompt in llm.prompts)
    assert DIRECTED_FORMAT_INSTRUCTIONS in deployers
    assert FORMAT_INSTRUCTIONS in own and DIRECTED_FORMAT_INSTRUCTIONS not in own


async def test_an_own_fish_key_is_tried_with_the_model_chosen(
    make_client: ClientFactory, speech: FakeSpeech
):
    client = make_client(FakeLLM())

    chosen = await client.post(CHECK, json={"api_key": MY_FISH, "model": "drama-3"})
    unchosen = await client.post(CHECK, json={"api_key": MY_FISH})

    assert (chosen.status_code, unchosen.status_code) == (200, 200)
    assert speech.tts_models == ["drama-3", DEFAULT_FISH_AUDIO_MODEL]


async def test_a_paid_model_needs_api_credit_and_the_free_one_none(monkeypatch: pytest.MonkeyPatch):
    credit = "0.000000"
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, json={"credit": credit, "cumulative_top_up": "0"})

    monkeypatch.setattr(
        "eidolon.call.open_client",
        lambda proxy, timeout: httpx.AsyncClient(transport=httpx.MockTransport(answer)),
    )
    speech = SpeechServices()

    await speech.check_tts("fish-key", DEFAULT_FISH_AUDIO_MODEL, own=True)
    with pytest.raises(OwnKeyRejected, match="余额是 0.*drama-3"):
        await speech.check_tts("fish-key", "drama-3", own=True)
    credit = "1.250000"
    await speech.check_tts("fish-key", "drama-3", own=True)

    assert asked == [SpeechServices.FISH_CREDIT_URL] * 3


def test_env_sets_the_deployers_model_from_those_there_are(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FISH_AUDIO_MODEL", " drama-3 ")
    assert fish_audio_model_from_env() == "drama-3"
    monkeypatch.setenv("FISH_AUDIO_MODEL", "")
    assert fish_audio_model_from_env() == DEFAULT_FISH_AUDIO_MODEL
    monkeypatch.setenv("FISH_AUDIO_MODEL", "drama3")
    with pytest.raises(RuntimeError, match="FISH_AUDIO_MODEL.*drama-3"):
        fish_audio_model_from_env()
