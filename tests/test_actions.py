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


def test_actions_can_be_replanned_for_another_audience(settings) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from aqstudio.web.app import create_app
    from tests.conftest import FakeLLM, hourly_csv

    client = TestClient(create_app(settings, FakeLLM()))
    upload = client.post("/api/uploads", json={"text": hourly_csv()}).json()["upload_id"]
    created = client.post("/api/briefs", json={"upload_id": upload})  # no persona needed
    brief = client.get(f"/api/briefs/{created.json()['brief_id']}").json()["brief"]
    assert brief["persona"] == "ward_officer"
    school = client.get(f"/api/briefs/{brief['id']}/actions", params={"persona": "school"}).json()
    assert school and all(a["persona"] == "school" for a in school)
    same = client.get(
        f"/api/briefs/{brief['id']}/actions", params={"persona": "ward_officer"}
    ).json()
    assert [a["id"] for a in same] == [a["id"] for a in brief["actions"]]
