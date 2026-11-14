"""Interface for LLM-backed functions; implementations are injected."""

from typing import Protocol

from aqstudio.schemas import ClaimDraft, Fact, Persona, QualityFlag, StationReliability


class LLMError(RuntimeError):
    """Raised when the LLM call fails or returns output that cannot be validated."""


class LLMClient(Protocol):
    """Turns computed facts into cited claims; never computes numbers itself."""

    def interpret_facts(
        self,
        facts: list[Fact],
        flags: list[QualityFlag],
        reliability: list[StationReliability],
        persona: Persona,
        context: str | None,
    ) -> list[ClaimDraft]:
        """Return claims, each citing fact ids."""
        ...
