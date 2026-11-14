"""Interface for LLM-backed interpretation; implementations are injected."""

from typing import Protocol

from aqstudio.schemas import ClaimDraft, Fact, Persona


class LLMError(RuntimeError):
    """Raised when the LLM call fails or returns output that cannot be validated."""


class Interpreter(Protocol):
    """Turns computed facts into cited claims; never computes numbers itself."""

    def interpret_facts(
        self, facts: list[Fact], flag_summary: dict[str, int], persona: Persona
    ) -> list[ClaimDraft]:
        """Return claims, each citing fact ids."""
        ...
