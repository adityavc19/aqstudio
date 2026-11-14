import io
from datetime import datetime

from fastapi.testclient import TestClient
from openpyxl import Workbook

from aqstudio.config import Settings
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM


def _workbook(with_empty_first_sheet: bool = False) -> bytes:
    book = Workbook()
    sheet = book.active
    if with_empty_first_sheet:
        sheet = book.create_sheet("Data")
    sheet.append(["Station ID", "Timestamp", "PM2.5 (ug/m3)", "PM10 (ug/m3)", "NO2 (ug/m3)"])
    for h in range(24):
        sheet.append(["S1", datetime(2024, 1, 1, h), 40 + h, 90 + h, "=1+1" if h == 0 else 25])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _upload(client: TestClient, data: bytes, name: str = "readings.xlsx") -> dict[str, object]:
    resp = client.post("/api/uploads", files={"file": (name, data, "application/octet-stream")})
    return {"status": resp.status_code, **resp.json()}


def test_xlsx_first_sheet_with_data_is_read_and_formulas_are_not_run(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    for data in (_workbook(), _workbook(with_empty_first_sheet=True)):
        upload = _upload(client, data)
        assert upload["status"] == 200 and upload["stats"]["rows"] == 24  # type: ignore[index]
        # Formulas are never evaluated: with no cached value the cell is read as missing.
        assert upload["preview"]["rows"][0][4] == ""  # type: ignore[index]


def test_corrupt_xlsx_is_rejected_cleanly(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    bad = _upload(client, b"not a zip file")
    assert bad["status"] == 422 and bad["error"]["code"] == "invalid_table"  # type: ignore[index]
