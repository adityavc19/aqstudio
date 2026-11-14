"""Interface for LLM-backed functions; implementations are injected."""

from typing import Protocol

from aqstudio.schemas import ActionDraft, ClaimDraft, Fact, Persona


class LLMError(RuntimeError):
    """Raised when the LLM call fails or returns output that cannot be validated."""


class LLMClient(Protocol):
    """Turns computed facts into cited claims; never computes numbers itself."""

    def interpret_facts(
        self, facts: list[Fact], persona: Persona, context: str | None
    ) -> list[ClaimDraft]:
        """Return claims, each citing fact ids."""
        ...

    def rank_actions(
        self, facts: list[Fact], persona: Persona, context: str | None
    ) -> list[ActionDraft]:
        """Return persona-specific actions, each citing fact ids."""
        ...
