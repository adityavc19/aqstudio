"""Anthropic-backed LLM client using forced tool use and pydantic validation."""

import json

import anthropic
from pydantic import ValidationError

from aqstudio.llm.client import LLMError
from aqstudio.llm.prompts.interpret import SYSTEM
from aqstudio.schemas import (
    ClaimDraft,
    Fact,
    InterpretationOutput,
    Persona,
    QualityFlag,
    StationReliability,
)

_TOOL = "report_claims"
_MAX_FLAGS_SENT = 20


class AnthropicClient:
    """Calls Claude with a schema-constrained tool and retries once on invalid output."""

    def __init__(self, client: anthropic.Anthropic, model: str) -> None:
        """Store the injected SDK client and model name."""
        self._client = client
        self._model = model

    def interpret_facts(
        self,
        facts: list[Fact],
        flags: list[QualityFlag],
        reliability: list[StationReliability],
        persona: Persona,
        context: str | None,
    ) -> list[ClaimDraft]:
        """Ask Claude for cited claims about the facts (aggregates only, never raw rows)."""
        payload = json.dumps(
            {
                "facts": [f.model_dump(exclude={"evidence", "spatial_note"}) for f in facts],
                "station_reliability": [r.model_dump() for r in reliability],
                "quality_flags": [
                    f.model_dump(
                        include={"id", "kind", "station_id", "pollutant", "severity", "detail"}
                    )
                    for f in flags[:_MAX_FLAGS_SENT]
                ],
                "quality_flag_total": len(flags),
            },
            default=str,
        )
        user = f"Audience: {persona.value}.\n<facts>\n{payload}\n</facts>"
        if context:
            user += f"\n<context>\n{context}\n</context>"
        messages: list[anthropic.types.MessageParam] = [{"role": "user", "content": user}]
        for attempt in range(2):
            output = self._call(messages)
            try:
                return InterpretationOutput.model_validate(output).claims
            except ValidationError as exc:
                if attempt == 1:
                    break
                messages = [
                    {
                        "role": "user",
                        "content": f"{user}\nYour last output was invalid: {exc}\n"
                        f"Call {_TOOL} again with valid output.",
                    }
                ]
        raise LLMError("The model returned output that failed validation twice.")

    def _call(self, messages: list[anthropic.types.MessageParam]) -> object:
        """Make one forced tool call and return the tool input."""
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=3000,
                system=SYSTEM,
                messages=messages,
                tools=[
                    {
                        "name": _TOOL,
                        "description": "Report cited claims about the facts.",
                        "input_schema": InterpretationOutput.model_json_schema(),
                    }
                ],
                tool_choice={"type": "tool", "name": _TOOL},
            )
        except anthropic.APIError as exc:
            raise LLMError(f"The AI service request failed ({type(exc).__name__}).") from exc
        for block in response.content:
            if block.type == "tool_use":
                return block.input
        raise LLMError("The model did not return a structured result.")
