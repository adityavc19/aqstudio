"""Translation through Sarvam Translate, with a digit check so numbers survive translation."""

import re
import time
import unicodedata
from collections.abc import Callable
from typing import Protocol

import httpx

from aqstudio.config import SARVAM_BASE_URL, SARVAM_TIMEOUT_S, SARVAM_TRANSLATE_MODEL


class TranslationError(RuntimeError):
    """Raised when the translation service fails."""


class Translator(Protocol):
    """Translates English text into one target language code (e.g. hi-IN)."""

    def translate(self, text: str, target: str) -> str:
        """Return the translated text."""
        ...


def _western(text: str) -> str:
    """Replace native-script digits (e.g. Devanagari) with 0-9."""
    return "".join(
        str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() else ch for ch in text
    )


def numbers_preserved(source: str, translated: str) -> bool:
    """True when both texts contain the same numbers, in any digit script."""
    find = re.compile(r"\d+(?:[.,]\d+)?")
    return sorted(find.findall(source)) == sorted(find.findall(_western(translated)))


class SarvamTranslator:
    """Calls Sarvam's /translate endpoint with retry on rate limits and overload."""

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

    def translate(self, text: str, target: str) -> str:
        """Translate English text into the target language."""
        body = {
            "input": text,
            "source_language_code": "en-IN",
            "target_language_code": target,
            "model": SARVAM_TRANSLATE_MODEL,
        }
        for attempt in range(3):
            try:
                response = self._http.post(
                    f"{SARVAM_BASE_URL}/translate",
                    headers={"api-subscription-key": self._key},
                    json=body,
                )
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise TranslationError(f"Translation failed ({type(exc).__name__}).") from exc
            else:
                if response.status_code == 200:
                    return str(response.json()["translated_text"])
                if response.status_code not in (429, 503) or attempt == 2:
                    raise TranslationError(f"Translation failed (HTTP {response.status_code}).")
            self._sleep(2.0**attempt)
        raise TranslationError("Translation failed.")
