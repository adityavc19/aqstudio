from pathlib import Path

import pytest

from aqstudio.config import Settings
from aqstudio.schemas import ClaimDraft, Fact, Persona, QualityFlag, QuotedValue, StationReliability


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_path=str(tmp_path / "test.sqlite3"),
        frontend_dir=str(tmp_path / "none"),
    )


class FakeLLM:
    """Cites the first fact correctly and one invented fact."""

    def interpret_facts(
        self,
        facts: list[Fact],
        flags: list[QualityFlag],
        reliability: list[StationReliability],
        persona: Persona,
        context: str | None,
    ) -> list[ClaimDraft]:
        first = facts[0]
        quote = QuotedValue(fact_id=first.id, field="mean", value=float(first.values["mean"] or 0))
        return [
            ClaimDraft(text="Grounded", fact_ids=[first.id], confidence=0.8, quoted_values=[quote]),
            ClaimDraft(text="Invented", fact_ids=["F999"], confidence=0.9),
        ]


def hourly_csv(base: int = 30, hours: int = 24, day: int = 1) -> str:
    rows = ["Station ID,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (ug/m3)"]
    for h in range(hours):
        rows.append(f"S1,2024-01-{day:02d}T{h:02d}:00:00Z,{base + h},{base * 2 + h},{20 + h}")
    return "\n".join(rows)
