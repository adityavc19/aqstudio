from fastapi.testclient import TestClient

from aqstudio.config import Settings
from aqstudio.schemas import ReliabilityGrade, StationInfo
from aqstudio.summary import summarize
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM, hourly_csv


def _info(sid: str, category: str, grade: ReliabilityGrade = ReliabilityGrade.GOOD) -> StationInfo:
    return StationInfo(
        station_id=sid,
        name=sid,
        lat=None,
        lon=None,
        aqi=None,
        category=category,
        reliability_grade=grade,
    )


def test_status_line_is_deterministic_and_matches_spec_example() -> None:
    stations = [
        _info("a", "Poor"),
        _info("b", "Poor"),
        _info("c", "Poor", ReliabilityGrade.UNRELIABLE),
        _info("d", "Moderate"),
        _info("e", "Good"),
    ]
    first, second = summarize(stations), summarize(list(reversed(stations)))
    assert first == second
    assert first.status_line == "Poor at 3 of 5 stations, 1 unreliable"
    assert (first.worst_category, first.unreliable_count) == ("Poor", 1)


def test_insufficient_data_and_singular_noun() -> None:
    none = summarize([_info("a", "insufficient_data", ReliabilityGrade.UNRELIABLE)])
    assert none.worst_category == "insufficient_data"
    assert none.status_line == "AQI not computable at any of 1 station, 1 unreliable"
    assert summarize([]).worst_category == "insufficient_data"
    assert summarize([_info("a", "Severe")]).status_line == "Severe at 1 of 1 station"


def test_list_endpoint_returns_new_fields_without_reading_brief_json(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    upload = client.post("/api/uploads", json={"text": hourly_csv()}).json()["upload_id"]
    client.post("/api/briefs", json={"upload_id": upload, "persona": "school"})
    [item] = client.get("/api/briefs").json()
    assert {"id", "created_at", "persona", "label"} <= item.keys()
    assert item["status_line"] == "Satisfactory at 1 of 1 station"
    assert item["worst_category"] == "Satisfactory" and item["unreliable_count"] == 0
    props = client.get("/openapi.json").json()["components"]["schemas"]["BriefListItem"][
        "properties"
    ]
    assert {"status_line", "worst_category", "unreliable_count"} <= props.keys()


def test_insufficient_data_brief_lists_insufficient(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    one_pollutant = "Station ID,Timestamp,PM2.5 (ug/m3)\n" + "\n".join(
        f"S1,2024-01-01T{h:02d}:00:00Z,{30 + h}" for h in range(24)
    )
    upload = client.post("/api/uploads", json={"text": one_pollutant}).json()["upload_id"]
    client.post("/api/briefs", json={"upload_id": upload, "persona": "school"})
    [item] = client.get("/api/briefs").json()
    assert item["worst_category"] == "insufficient_data"
    assert item["status_line"].startswith("AQI not computable")
