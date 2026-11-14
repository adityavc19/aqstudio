"""Sarvam-hosted open-weight models through the OpenAI-compatible /v2 chat API."""

import httpx

from aqstudio.config import SARVAM_BASE_URL, SARVAM_MAX_TOKENS, SARVAM_TIMEOUT_S
from aqstudio.llm.client import LLMError
from aqstudio.llm.interpret import build_user_prompt, interpret_with_retry
from aqstudio.llm.prompts.interpret import SYSTEM
from aqstudio.schemas import (
    ClaimDraft,
    Fact,
    InterpretationOutput,
    Persona,
    QualityFlag,
    StationReliability,
)

# Models whose docs allow reasoning_effort "none"; thinking tokens otherwise dominate latency.
_REASONING_OFF = frozenset({"sarvam-105b", "deepseekv4.1-flash-1017"})


class SarvamClient:
    """Calls a Sarvam-hosted chat model with json_schema structured output."""

    def __init__(self, api_key: str, model: str, http: httpx.Client | None = None) -> None:
        """Keep the key private; the HTTP client is injectable for tests."""
        self._key = api_key
        self._model = model
        self._http = http or httpx.Client(timeout=SARVAM_TIMEOUT_S)

    def interpret_facts(
        self,
        facts: list[Fact],
        flags: list[QualityFlag],
        reliability: list[StationReliability],
        persona: Persona,
        context: str | None,
    ) -> list[ClaimDraft]:
        """Ask the model for cited claims about the facts."""
        prompt = build_user_prompt(facts, flags, reliability, persona, context)
        return interpret_with_retry(prompt, self._call)

    def _call(self, prompt: str) -> object:
        """One chat completion; returns the raw JSON text for validation."""
        body: dict[str, object] = {
            "model": self._model,
            "max_tokens": SARVAM_MAX_TOKENS,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "claims",
                    "schema": InterpretationOutput.model_json_schema(),
                    "strict": True,
                },
            },
        }
        if self._model in _REASONING_OFF:
            body["reasoning_effort"] = "none"
        try:
            response = self._http.post(
                f"{SARVAM_BASE_URL}/v2/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"The AI service request failed ({type(exc).__name__}).") from exc
        if response.status_code != 200:
            raise LLMError(f"The AI service request failed (HTTP {response.status_code}).")
        choice = response.json()["choices"][0]
        content = choice["message"].get("content") or ""
        if not content:
            raise LLMError("The model returned no content (it may have run out of token budget).")
        return str(content)
