from fastapi.testclient import TestClient

from aqstudio.advisory.speech import SpeechError, fit_for_speech
from aqstudio.config import TTS_MAX_CHARS, Settings
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM, hourly_csv

WAV = b"RIFF fake wav"


class FakeSpeaker:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def speak(self, text: str, language: str) -> bytes:
        if self.fail:
            raise SpeechError("down")
        self.calls.append((text, language))
        return WAV


def _shared(client: TestClient) -> str:
    upload = client.post("/api/uploads", json={"text": hourly_csv()}).json()["upload_id"]
    brief_id = client.post("/api/briefs", json={"upload_id": upload, "persona": "citizen"}).json()[
        "brief_id"
    ]
    return str(client.post(f"/api/briefs/{brief_id}/share").json()["share_id"])


def test_listen_returns_cached_wav_for_the_chosen_group(settings: Settings) -> None:
    speaker = FakeSpeaker()
    client = TestClient(create_app(settings, FakeLLM(), speaker=speaker))
    share = _shared(client)
    first = client.get(f"/api/share/{share}/audio", params={"group": "children"})
    assert first.status_code == 200 and first.headers["content-type"] == "audio/wav"
    assert first.content == WAV and "Keep sports indoors." in speaker.calls[0][0]
    client.get(f"/api/share/{share}/audio", params={"group": "children"})
    assert len(speaker.calls) == 1  # cached


def test_listen_fails_honestly(settings: Settings) -> None:
    down = TestClient(create_app(settings, FakeLLM(), speaker=FakeSpeaker(fail=True)))
    share = _shared(down)
    assert down.get(f"/api/share/{share}/audio").json()["error"]["code"] == "speech_unavailable"
    none = TestClient(create_app(settings, FakeLLM()))
    assert none.get(f"/api/share/{share}/audio").status_code == 503


def test_long_text_is_trimmed_at_a_sentence_boundary() -> None:
    text = "Short sentence. " * 200
    trimmed = fit_for_speech(text)
    assert len(trimmed) <= TTS_MAX_CHARS and trimmed.endswith(".")
