from fastapi.testclient import TestClient

from aqstudio.config import Settings
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM, hourly_csv


def _brief(client: TestClient) -> str:
    upload = client.post("/api/uploads", json={"text": hourly_csv()}).json()["upload_id"]
    return str(
        client.post("/api/briefs", json={"upload_id": upload, "persona": "citizen"}).json()[
            "brief_id"
        ]
    )


def test_owner_shares_and_anyone_with_link_sees_only_public_view(settings: Settings) -> None:
    owner = TestClient(create_app(settings, FakeLLM()))
    brief_id = _brief(owner)
    created = owner.post(f"/api/briefs/{brief_id}/share").json()
    assert created["url"] == f"/#/c/{created['share_id']}" and len(created["share_id"]) >= 20
    assert owner.post(f"/api/briefs/{brief_id}/share").json() == created  # idempotent
    stranger = TestClient(create_app(settings, FakeLLM()))
    page = stranger.get(f"/api/share/{created['share_id']}").json()
    assert page["status_line"] and page["stations"][0]["station_id"] == "S1"
    assert "Unofficial" in page["notice"] and "ledger" not in page and "facts" not in page
    advisory = stranger.get(f"/api/share/{created['share_id']}/advisory").json()
    assert advisory["format"] == "citizen" and len(advisory["sections"]) == 6


def test_share_guards(settings: Settings) -> None:
    owner = TestClient(create_app(settings, FakeLLM()))
    brief_id = _brief(owner)
    stranger = TestClient(create_app(settings, FakeLLM()))
    assert stranger.post(f"/api/briefs/{brief_id}/share").status_code == 403
    assert stranger.get("/api/share/not-a-real-link").status_code == 404


def test_citizen_view_exists_automatically_when_a_brief_is_ready(settings: Settings) -> None:
    owner = TestClient(create_app(settings, FakeLLM()))
    brief_id = _brief(owner)
    state = owner.get(f"/api/briefs/{brief_id}").json()
    assert state["share_id"] and owner.get(f"/api/share/{state['share_id']}").status_code == 200
    [item] = owner.get("/api/briefs").json()
    assert item["share_id"] == state["share_id"]
    assert owner.post(f"/api/briefs/{brief_id}/share").json()["share_id"] == state["share_id"]
