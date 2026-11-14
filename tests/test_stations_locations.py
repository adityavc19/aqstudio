from fastapi.testclient import TestClient

from aqstudio.config import Settings
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM, station_csv


def _brief(
    client: TestClient, text: str, **body: object
) -> tuple[dict[str, object], dict[str, object]]:
    upload = client.post("/api/uploads", json={"text": text}).json()
    resp = client.post(
        "/api/briefs", json={"upload_id": upload["upload_id"], "persona": "school", **body}
    )
    assert resp.status_code == 202, resp.text
    state = client.get(f"/api/briefs/{resp.json()['brief_id']}").json()
    assert state["status"] == "ready", state
    return upload, state["brief"]


def _flags(brief: dict[str, object], kind: str) -> list[str]:
    return [f["station_id"] for f in brief["flags"] if f["kind"] == kind]  # type: ignore[attr-defined]


def test_coordinates_present_are_used_as_uploaded(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    _, brief = _brief(client, station_csv([("S1", "Peenya", "13.03", "77.52")]))
    [station] = brief["stations"]  # type: ignore[misc]
    assert (station["lat"], station["lon"], station["name"]) == (13.03, 77.52, "Peenya")
    assert brief["coordinates_source"] == "uploaded" and _flags(brief, "no_coords") == []
    assert station["category"] == "Satisfactory" and station["reliability_grade"] == "good"


def test_names_only_means_no_coordinates_and_flag(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    text = station_csv([("S1", "Peenya", "", "")], with_coords=False)
    _, brief = _brief(client, text)
    [station] = brief["stations"]  # type: ignore[misc]
    assert station["lat"] is None and brief["coordinates_source"] == "none"
    assert _flags(brief, "no_coords") == ["S1"]


def test_partial_and_invalid_coordinates(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    text = station_csv(
        [
            ("S1", "A", "13.0", "77.5"),
            ("S2", "B", "", ""),
            ("S3", "C", "0", "0"),
            ("S4", "D", "x", "y"),
        ]
    )
    _, brief = _brief(client, text)
    by_id = {s["station_id"]: s for s in brief["stations"]}  # type: ignore[attr-defined]
    assert by_id["S1"]["lat"] == 13.0 and all(by_id[k]["lat"] is None for k in ("S2", "S3", "S4"))
    assert brief["coordinates_source"] == "uploaded"
    assert sorted(_flags(brief, "no_coords")) == ["S2", "S3", "S4"]


def test_swapped_coordinates_become_an_assumption_not_a_silent_fix(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    text = station_csv([("S1", "Peenya", "77.52", "13.03")])
    upload, brief = _brief(client, text)
    proposal = next(a for a in upload["assumptions"] if a["id"] == "coordinates_swapped")  # type: ignore[attr-defined]
    assert proposal["status"] == "proposed" and proposal["proposed"]["station_ids"] == ["S1"]
    assert brief["stations"][0]["lat"] is None and _flags(brief, "no_coords") == ["S1"]  # type: ignore[index]
    _, fixed = _brief(
        client, text, assumptions=[{"id": "coordinates_swapped", "status": "confirmed"}]
    )
    assert (fixed["stations"][0]["lat"], fixed["stations"][0]["lon"]) == (13.03, 77.52)  # type: ignore[index]


def test_locations_endpoint_matches_by_id_and_name_without_rerunning_llm(
    settings: Settings,
) -> None:
    llm = FakeLLM()
    client = TestClient(create_app(settings, llm))
    text = station_csv(
        [("S1", "Peenya Ind", "", ""), ("S2", "Jayanagar", "", "")], with_coords=False
    )
    _, brief = _brief(client, text)
    calls = llm.calls
    brief_id = brief["id"]
    csv_text = "station_id,lat,lon\ns1,13.03,77.52\nJAYANAGAR,12.93,77.58\nGhost,1,2\nS1,0,0\n"
    resp = client.post(f"/api/briefs/{brief_id}/locations", json={"text": csv_text})
    assert resp.status_code == 200
    body = resp.json()
    assert [m["station_id"] for m in body["matched"]] == ["S1", "S2"]
    assert [(u["row"], u["file_station"]) for u in body["unmatched"]] == [(4, "Ghost"), (5, "S1")]
    assert "placeholder" in body["unmatched"][1]["reason"]
    assert body["coordinates_source"] == "stations_file"
    assert {s["station_id"]: s["lat"] for s in body["stations"]} == {"S1": 13.03, "S2": 12.93}
    assert llm.calls == calls  # analysis and LLM were not re-run
    stored = client.get(f"/api/briefs/{brief_id}").json()["brief"]
    assert _flags(stored, "no_coords") == [] and stored["coordinates_source"] == "stations_file"
    assert len(stored["facts"]) == len(brief["facts"])  # analysis unchanged  # type: ignore[arg-type]


def test_locations_endpoint_guards(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    _, brief = _brief(client, station_csv([("S1", "Peenya", "", "")]))
    url = f"/api/briefs/{brief['id']}/locations"
    assert (
        client.post(url, json={"text": "a,b\n1,2"}).json()["error"]["code"] == "invalid_locations"
    )
    stranger = TestClient(create_app(settings, FakeLLM()))
    assert stranger.post(url, json={"text": "station_id,lat,lon\nS1,13,77"}).status_code == 403
    assert client.post("/api/briefs/nope/locations", json={"text": "x"}).status_code == 404
    swapped = client.post(url, json={"text": "station_id,lat,lon\nS1,77.5,13.0"}).json()
    assert swapped["matched"] == [] and "swapped" in swapped["unmatched"][0]["reason"]
    assert swapped["coordinates_source"] == "none"
