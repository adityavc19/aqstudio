"""Provider-independent parts of fact interpretation: prompt building and validated retry."""

import json
from collections.abc import Callable

from pydantic import ValidationError

from aqstudio.llm.client import LLMError
from aqstudio.schemas import ClaimDraft, Fact, InterpretationOutput, Persona


def build_user_prompt(facts: list[Fact], persona: Persona, context: str | None) -> str:
    """Aggregated facts only (never raw rows), with untrusted content in delimited blocks."""
    payload = json.dumps(
        [f.model_dump(exclude={"evidence", "spatial_note"}) for f in facts], default=str
    )
    prompt = f"Audience: {persona.value}.\n<facts>\n{payload}\n</facts>"
    if context:
        prompt += f"\n<context>\n{context}\n</context>"
    return prompt


def interpret_with_retry(prompt: str, call_model: Callable[[str], object]) -> list[ClaimDraft]:
    """Validate the model's output; on failure retry once with the error, then raise LLMError."""
    attempt_prompt = prompt
    for attempt in range(2):
        raw = call_model(attempt_prompt)
        try:
            if isinstance(raw, str):
                return InterpretationOutput.model_validate_json(raw).claims
            return InterpretationOutput.model_validate(raw).claims
        except ValidationError as exc:
            if attempt == 1:
                break
            attempt_prompt = f"{prompt}\nYour last output was invalid: {exc}\nReturn valid output."
    raise LLMError("The model returned output that failed validation twice.")
