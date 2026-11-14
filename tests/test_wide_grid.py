from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aqstudio.config import Settings
from aqstudio.ingest.errors import IngestError
from aqstudio.ingest.parse_wide import WideLabels, wide_to_long
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM

GRID = (Path(__file__).parent / "fixtures" / "wide_grid.csv").read_text()
LABELS = WideLabels("Peenya", "PM2.5", "ug/m3")


def test_grid_becomes_long_rows_with_ist_times_and_skips_impossible_dates() -> None:
    table, skipped = wide_to_long(GRID, LABELS)
    assert table.columns == ["Station ID", "Timestamp", "PM2.5 (ug/m3)"]
    assert table.rows[0] == ["Peenya", "2017-01-01T00:00:00+05:30", "40"]
    assert len(table.rows) == 24 * 4 and skipped == 1  # 3 January days + 1 Feb; 30 Feb skipped
    assert ["Peenya", "2017-01-03T05:00:00+05:30", ""] in table.rows  # blank day kept as missing


def test_grid_without_day_rows_is_rejected() -> None:
    with pytest.raises(IngestError):
        wide_to_long("Year,2017\nnothing here\n", LABELS)


def test_api_asks_for_labels_then_runs_the_normal_pipeline(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    ask = client.post("/api/uploads", json={"text": GRID})
    assert ask.status_code == 422 and ask.json()["error"]["code"] == "labels_required"
    body = {"text": GRID, "station": "Peenya", "pollutant": "PM2.5", "unit": "ug/m3"}
    upload = client.post("/api/uploads", json=body).json()
    assert upload["detected_format"] == "wide_grid" and upload["stats"]["stations"] == ["Peenya"]
    assert any("IST" in w for w in upload["warnings"]) and any(
        "impossible" in w for w in upload["warnings"]
    )
    assert "ceiling" in {f["kind"] for f in upload["early_flags"]}  # the 500 day is caught
    brief = client.post("/api/briefs", json={"upload_id": upload["upload_id"], "persona": "school"})
    state = client.get(f"/api/briefs/{brief.json()['brief_id']}").json()
    assert state["status"] == "ready"
    assert state["brief"]["summary"]["worst_category"] == "insufficient_data"  # one pollutant only


def test_multipart_upload_accepts_labels(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    resp = client.post(
        "/api/uploads",
        files={"file": ("grid.csv", GRID.encode(), "text/csv")},
        data={"station": "Peenya", "pollutant": "PM10", "unit": "ug/m3"},
    )
    assert resp.status_code == 200 and resp.json()["stats"]["pollutants"] == ["PM10"]
