from pathlib import Path

from aqstudio.llm.cache import CachedLLMClient
from aqstudio.schemas import ClaimDraft, Fact, Persona, ReliabilityGrade
from aqstudio.store.db import Database

FACT = Fact(
    id="F1",
    kind="pollutant_mean",
    values={"mean": 1.0},
    coverage_pct=90,
    reliability_grade=ReliabilityGrade.GOOD,
)


class CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def interpret_facts(self, *args: object) -> list[ClaimDraft]:
        self.calls += 1
        return [ClaimDraft(text="c", fact_ids=["F1"], confidence=0.5)]


def test_identical_inputs_hit_cache_and_changed_inputs_do_not(tmp_path: Path) -> None:
    inner = CountingLLM()
    client = CachedLLMClient(inner, Database(str(tmp_path / "c.db")), "model-x")  # type: ignore[arg-type]
    first = client.interpret_facts([FACT], Persona.SCHOOL, None)
    again = client.interpret_facts([FACT], Persona.SCHOOL, None)
    assert inner.calls == 1 and first == again
    client.interpret_facts([FACT], Persona.SCHOOL, "different context")
    assert inner.calls == 2
