from fastapi.testclient import TestClient

from aqstudio.config import Settings
from aqstudio.llm.client import LLMError
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM, hourly_csv


class FailingLLM:
    def interpret_facts(self, *args: object) -> list[object]:
        raise LLMError("The AI service request failed (APIError).")

    def rank_actions(self, *args: object) -> list[object]:
        raise LLMError("The AI service request failed (APIError).")


def _upload(client: TestClient, text: str) -> str:
    resp = client.post("/api/uploads", json={"text": text})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["upload_id"])


def _brief(client: TestClient, upload_id: str, **extra: object) -> dict[str, object]:
    resp = client.post(
        "/api/briefs", json={"upload_id": upload_id, "persona": "ward_officer", **extra}
    )
    assert resp.status_code == 202, resp.text
    state = client.get(f"/api/briefs/{resp.json()['brief_id']}").json()
    assert isinstance(state, dict)
    return state


def test_health_and_openapi(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    assert client.get("/api/health").json()["status"] == "ok"
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/briefs/{brief_id}/diff" in paths and "/api/uploads" in paths


def test_upload_preview_mapping_and_assumptions(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    body = client.post("/api/uploads", json={"text": hourly_csv()}).json()
    assert body["detected_format"] == "long_csv" and len(body["preview"]["rows"]) == 10
    assert {m["meaning"] for m in body["mapping"]} == {"station_id", "timestamp", "pollutant"}
    assert body["assumptions"][0]["id"] == "timezone"


def test_full_flow_evidence_and_unverified_claim(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    state = _brief(client, _upload(client, hourly_csv()))
    assert state["status"] == "ready"
    brief = state["brief"]
    assert isinstance(brief, dict)
    statuses = {c["text"]: c["status"] for c in brief["claims"]}
    assert statuses == {"Grounded": "verified", "Invented": "unverified"}
    assert {f["kind"] for f in brief["facts"]} >= {"pollutant_mean", "aqi_latest", "pm_ratio"}
    evidence = client.get(f"/api/briefs/{state['id']}/evidence/F1").json()
    assert evidence["fact"]["id"] == "F1" and evidence["rows"][0]["values"]["Station ID"] == "S1"
    assert client.get(f"/api/briefs/{state['id']}/evidence/F999").status_code == 404
    assert len(client.get("/api/briefs").json()) == 1  # same browser session


def test_comparison_and_session_isolation(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    first = _brief(client, _upload(client, hourly_csv(base=30)))
    second = _brief(client, _upload(client, hourly_csv(base=90)), previous_brief_id=first["id"])
    diff = client.get(f"/api/briefs/{second['id']}/diff", params={"against": first["id"]}).json()
    assert diff["changed"] and diff["summary_inputs"]["genuine_changes"] >= 1
    other = TestClient(create_app(settings, FakeLLM()))
    assert other.get("/api/briefs").json() == []


def test_llm_failure_is_honest(settings: Settings) -> None:
    client = TestClient(create_app(settings, FailingLLM()))  # type: ignore[arg-type]
    state = _brief(client, _upload(client, hourly_csv()))
    assert state["status"] == "failed" and state["brief"] is None
    assert state["error"]["code"] == "llm_unavailable"  # type: ignore[index]


def test_no_api_key_returns_503(settings: Settings) -> None:
    client = TestClient(create_app(settings, None))
    upload_id = _upload(client, hourly_csv())
    resp = client.post("/api/briefs", json={"upload_id": upload_id, "persona": "school"})
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "llm_unavailable"


def test_security_and_error_shape(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    wrong = client.post("/api/uploads", files={"file": ("x.exe", b"a,b", "text/plain")})
    assert wrong.status_code == 415 and wrong.json()["error"]["code"] == "unsupported_format"
    big = client.post(
        "/api/uploads", files={"file": ("x.csv", b"a" * (5 * 1024 * 1024 + 10), "text/csv")}
    )
    assert big.status_code == 413 and big.json()["error"]["code"] == "file_too_large"
    assert client.post("/api/uploads", json={"nope": 1}).status_code == 422
    wide = client.post(
        "/api/uploads", json={"text": "Year,2017\nJanuary-2017,00:00:00,01:00:00\n1,5,6"}
    )
    assert wide.json()["error"]["code"] == "labels_required"
    evil = client.post(
        "/api/uploads", json={"text": hourly_csv()}, headers={"origin": "https://evil.example"}
    )
    assert evil.status_code == 403
    assert client.get("/api/briefs/missing").json()["error"]["code"] == "not_found"
    health = client.get("/api/health")
    assert health.headers["x-content-type-options"] == "nosniff"


def test_html_in_cells_is_returned_as_inert_json_data(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    text = hourly_csv().replace("S1,", "<script>x</script>,", 1)
    upload = client.post("/api/uploads", json={"text": text})
    assert upload.headers["content-type"].startswith("application/json")
    assert upload.json()["preview"]["rows"][0][0] == "<script>x</script>"


def test_per_ip_limit_returns_429(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    upload_id = _upload(client, hourly_csv())
    codes = [
        client.post("/api/briefs", json={"upload_id": upload_id, "persona": "school"}).status_code
        for _ in range(21)
    ]
    assert codes.count(202) == 20 and codes[-1] == 429
