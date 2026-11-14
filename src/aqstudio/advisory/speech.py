"""Text to speech through Sarvam Bulbul, used for the citizen advisory's Listen button."""

import base64
import time
from collections.abc import Callable
from typing import Protocol

import httpx

from aqstudio.config import SARVAM_BASE_URL, SARVAM_TIMEOUT_S, SARVAM_TTS_MODEL, TTS_MAX_CHARS


class SpeechError(RuntimeError):
    """Raised when the speech service fails."""


class Speaker(Protocol):
    """Turns text in a language (e.g. hi-IN) into WAV audio bytes."""

    def speak(self, text: str, language: str) -> bytes:
        """Return WAV audio."""
        ...


def fit_for_speech(text: str) -> str:
    """Trim text to the speech limit at a sentence boundary, so audio never cuts mid-sentence."""
    if len(text) <= TTS_MAX_CHARS:
        return text
    cut = text[:TTS_MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("। "), cut.rfind("? "))
    return cut[: end + 1] if end > 0 else cut


class SarvamSpeaker:
    """Calls Sarvam's /text-to-speech with retry on rate limits and overload."""

    def __init__(
        self,
        api_key: str,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Keep the key private; the HTTP client and sleep are injectable for tests."""
        self._key = api_key
        self._http = http or httpx.Client(timeout=SARVAM_TIMEOUT_S)
        self._sleep = sleep

    def speak(self, text: str, language: str) -> bytes:
        """Synthesize speech for text in the given language."""
        body = {"text": text, "target_language_code": language, "model": SARVAM_TTS_MODEL}
        for attempt in range(3):
            try:
                response = self._http.post(
                    f"{SARVAM_BASE_URL}/text-to-speech",
                    headers={"api-subscription-key": self._key},
                    json=body,
                )
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise SpeechError(f"Speech failed ({type(exc).__name__}).") from exc
            else:
                if response.status_code == 200:
                    return base64.b64decode(response.json()["audios"][0])
                if response.status_code not in (429, 503) or attempt == 2:
                    raise SpeechError(f"Speech failed (HTTP {response.status_code}).")
            self._sleep(2.0**attempt)
        raise SpeechError("Speech failed.")
