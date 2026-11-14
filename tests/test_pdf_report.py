import csv
import io

import pytest
from fastapi.testclient import TestClient

from aqstudio.config import Settings
from aqstudio.ingest.errors import IngestError
from aqstudio.ingest.parse_pdf import report_text_to_csv
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM

# Synthetic pages shaped like a state board monthly report (not real data).
PAGE_A = """Sample Station Alpha – May 2026
Date PM SO NO CO AQI
10 2 2
µg/m³ µg/m³ µg/m³ mg/m³
01-05-2026 106.9 7.6 57.2 1.10 105
02-05-2026 - 7.6 56.2 * 106
03-05-2026 107.8 7.6
Minimum 95.1 7.3 34.9 0.92 *
Average 110.6 9.7 52.1 1.27 *"""

PAGE_B = """Sample Station Beta - May 2026
Date PM PM SO NO CO O NH Benzene Temp R H AQI
10 2.5 2 2 3 3
µg/m3 µg/m3 µg/m3 µg/m3 mg/m3 µg/m3 µg/m3 µg/m3 oC %
01-05-2026 80.0 40.0 5.0 20.0 0.5 30.0 10.0 1.0 26.1 55 80"""


def test_report_pages_become_one_long_table() -> None:
    text, skipped = report_text_to_csv([PAGE_A, "Inference: narrative text only", PAGE_B])
    rows = list(csv.DictReader(io.StringIO(text)))
    header = next(csv.reader(io.StringIO(text)))
    assert header[:2] == ["Station ID", "Timestamp"]
    assert {
        "PM10 (µg/m³)",
        "PM2.5 (µg/m³)",
        "O3 (µg/m³)",
        "NH3 (µg/m³)",
        "RH (%)",
        "Temp (°C)",
    } <= set(header)
    assert [r["Station ID"] for r in rows] == ["Sample Station Alpha"] * 2 + ["Sample Station Beta"]
    assert rows[0]["Timestamp"] == "2026-05-01T00:00:00+05:30" and rows[0]["AQI"] == "105"
    assert rows[1]["PM10 (µg/m³)"] == "-" and rows[1]["CO (mg/m³)"] == "*"  # missing stays missing
    assert skipped == 1  # the short 03-05 row; Minimum/Average rows are not data


def test_pdf_without_station_tables_is_rejected() -> None:
    with pytest.raises(IngestError):
        report_text_to_csv(["Just a narrative article about air quality."])


def test_unreadable_pdf_upload_fails_cleanly(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    resp = client.post(
        "/api/uploads", files={"file": ("report.pdf", b"%PDF-1.4 broken", "application/pdf")}
    )
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_table"
