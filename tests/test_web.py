from fastapi.testclient import TestClient

from aqstudio.llm.base import LLMError
from aqstudio.schemas import ClaimDraft, Fact, Persona
from aqstudio.web.app import create_app


def _csv() -> str:
    rows = ["Station ID,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (ug/m3)"]
    for h in range(24):
        rows.append(f"S1,2024-01-01T{h:02d}:00:00Z,{30 + h},{60 + h},{20 + h}")
    return "\n".join(rows)


class FakeInterpreter:
    def interpret_facts(
        self, facts: list[Fact], flag_summary: dict[str, int], persona: Persona
    ) -> list[ClaimDraft]:
        return [
            ClaimDraft(text="Grounded claim", cited_fact_ids=[facts[0].id], confidence=0.8),
            ClaimDraft(text="Invented claim", cited_fact_ids=["ghost.fact"], confidence=0.9),
        ]


class FailingInterpreter:
    def interpret_facts(
        self, facts: list[Fact], flag_summary: dict[str, int], persona: Persona
    ) -> list[ClaimDraft]:
        raise LLMError("The AI service request failed (APIError).")


def test_full_flow_marks_bad_citation_unverified() -> None:
    client = TestClient(create_app(FakeInterpreter()))
    resp = client.post("/brief", data={"persona": "ward_officer", "pasted": _csv()})
    assert resp.status_code == 200
    assert "Verified" in resp.text and "Unknown fact id: ghost.fact" in resp.text
    assert "S1.PM2.5.mean" in resp.text and "S1.aqi.latest" in resp.text
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_llm_failure_shows_honest_error_without_brief() -> None:
    client = TestClient(create_app(FailingInterpreter()))
    resp = client.post("/brief", data={"persona": "school", "pasted": _csv()})
    assert resp.status_code == 502
    assert "No brief was produced" in resp.text and "Computed facts" not in resp.text


def test_rejects_wrong_type_oversize_and_escapes_html() -> None:
    client = TestClient(create_app(FakeInterpreter()))
    wrong = client.post(
        "/brief", data={"persona": "school"}, files={"file": ("x.exe", b"a,b", "text/plain")}
    )
    assert wrong.status_code == 415
    big = client.post(
        "/brief",
        data={"persona": "school"},
        files={"file": ("x.csv", b"a" * (5 * 1024 * 1024 + 10), "text/csv")},
    )
    assert big.status_code == 413
    html_cell = _csv().replace("S1,", "<script>alert(1)</script>,", 1)
    ok = client.post("/brief", data={"persona": "school", "pasted": html_cell})
    assert "<script>alert(1)</script>" not in ok.text


def test_no_api_key_is_reported_honestly() -> None:
    client = TestClient(create_app(None))
    resp = client.post("/brief", data={"persona": "school", "pasted": _csv()})
    assert resp.status_code == 503
