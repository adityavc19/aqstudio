"""Anthropic-backed LLM client using forced tool use and pydantic validation."""

import anthropic

from aqstudio.llm.client import LLMError
from aqstudio.llm.interpret import build_user_prompt, interpret_with_retry, structured_with_retry
from aqstudio.llm.prompts.actions import SYSTEM as ACTIONS_SYSTEM
from aqstudio.llm.prompts.interpret import SYSTEM
from aqstudio.schemas import (
    ActionDraft,
    ActionsOutput,
    ClaimDraft,
    Fact,
    InterpretationOutput,
    Persona,
)

_TOOL = "report_claims"


class AnthropicClient:
    """Calls Claude with a schema-constrained tool."""

    def __init__(self, client: anthropic.Anthropic, model: str) -> None:
        """Store the injected SDK client and model name."""
        self._client = client
        self._model = model

    def interpret_facts(
        self, facts: list[Fact], persona: Persona, context: str | None
    ) -> list[ClaimDraft]:
        """Ask Claude for cited claims about the facts."""
        prompt = build_user_prompt(facts, persona, context)
        return interpret_with_retry(prompt, self._call)

    def rank_actions(
        self, facts: list[Fact], persona: Persona, context: str | None
    ) -> list[ActionDraft]:
        """Ask Claude for persona-specific actions citing facts."""
        prompt = build_user_prompt(facts, persona, context)
        call = lambda p: self._call(p, ACTIONS_SYSTEM, ActionsOutput)  # noqa: E731
        return structured_with_retry(prompt, call, ActionsOutput).actions

    def _call(
        self,
        prompt: str,
        system: str = SYSTEM,
        schema: type[InterpretationOutput] | type[ActionsOutput] = InterpretationOutput,
    ) -> object:
        """Make one forced tool call and return the tool input."""
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=3000,
                system=f"{system} Report only via the {_TOOL} tool.",
                messages=[{"role": "user", "content": prompt}],
                tools=[
                    {
                        "name": _TOOL,
                        "description": "Report cited claims about the facts.",
                        "input_schema": schema.model_json_schema(),
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
