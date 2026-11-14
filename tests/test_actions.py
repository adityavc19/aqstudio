from aqstudio.schemas import Fact, Persona, ReliabilityGrade
from aqstudio.verify.actions import GATED, verify_actions
from tests.conftest import _action

GOOD = Fact(
    id="F1",
    kind="pollutant_mean",
    values={"mean": 50.0},
    coverage_pct=95,
    reliability_grade=ReliabilityGrade.GOOD,
)
WEAK = Fact(
    id="F2",
    kind="pollutant_mean",
    values={"mean": 90.0},
    coverage_pct=40,
    reliability_grade=ReliabilityGrade.UNRELIABLE,
)


def test_unknown_citations_dropped_and_weak_data_actions_gated() -> None:
    actions = verify_actions(
        [_action(["F1"]), _action(["F999"]), _action(["F2"]), _action(["F2"], effect="evidence")],
        [GOOD, WEAK],
        Persona.SCHOOL,
    )
    assert [a.fact_ids for a in actions] == [["F1"], ["F2"], ["F2"]]
    assert actions[0].tier.value == "now" and actions[0].gated_reason is None
    assert actions[1].tier.value == "escalate" and actions[1].gated_reason == GATED
    assert actions[2].gated_reason is None and actions[0].id == "A1"


def test_actions_with_invented_numbers_are_dropped() -> None:
    bad = _action(["F1"]).model_copy(update={"text": "Cut PM2.5 by 70 today"})
    assert verify_actions([bad], [GOOD], Persona.SCHOOL) == []
