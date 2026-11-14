import pytest
from fastapi.testclient import TestClient

from aqstudio.config import Settings
from aqstudio.quality.units import conversion_for
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM


def test_documented_conversions_are_exact_for_mass_and_approximate_for_gas_fractions() -> None:
    mass = conversion_for("NO2", "mg/m3")
    assert mass and (mass.factor, mass.exact, mass.to_unit) == (1000.0, True, "ug/m3")
    co = conversion_for("CO", "ug/m3")
    assert co and (co.factor, co.to_unit) == (0.001, "mg/m3")
    ppb = conversion_for("NO2", "ppb")
    assert ppb and not ppb.exact and ppb.factor == pytest.approx(1.8817, abs=1e-3)
    co_ppm = conversion_for("CO", "ppm")
    assert co_ppm and co_ppm.factor == pytest.approx(1.1456, abs=1e-3)


@pytest.mark.parametrize(
    ("pollutant", "unit"), [("PM2.5", "ppb"), ("NO2", "ug/m3"), ("NO2", "unknown")]
)
def test_no_conversion_when_none_is_safe_or_needed(pollutant: str, unit: str) -> None:
    assert conversion_for(pollutant, unit) is None


def _csv(no2_unit: str) -> str:
    rows = [f"Station ID,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 ({no2_unit})"]
    for h in range(24):
        no2 = (20 + h) / 1000 if no2_unit == "mg/m3" else 20 + h
        rows.append(f"S1,2024-01-01T{h:02d}:00:00Z,{40 + h},{90 + h},{no2}")
    return "\n".join(rows)


def _brief(client: TestClient, text: str, choices: list[dict[str, str]]) -> dict[str, object]:
    upload = client.post("/api/uploads", json={"text": text}).json()
    body = {"upload_id": upload["upload_id"], "persona": "school", "assumptions": choices}
    resp = client.post("/api/briefs", json=body)
    state = client.get(f"/api/briefs/{resp.json()['brief_id']}").json()
    assert state["status"] == "ready", state
    return state["brief"]  # type: ignore[no-any-return]


def test_conversion_is_proposed_flagged_and_excluded_until_approved(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    upload = client.post("/api/uploads", json={"text": _csv("mg/m3")}).json()
    proposal = next(a for a in upload["assumptions"] if a["kind"] == "unit_conversion")
    assert proposal["default_applied"] is False and proposal["proposed"]["factor"] == 1000.0
    assert proposal["confirm_label"] == "Approve conversion"
    assert "until you approve a conversion" in next(
        f["detail"] for f in upload["early_flags"] if f["kind"] == "unit_mismatch"
    )
    brief = _brief(client, _csv("mg/m3"), [])
    means = [f for f in brief["facts"] if f["kind"] == "pollutant_mean"]  # type: ignore[attr-defined]
    assert not any(f["values"]["pollutant"] == "NO2" for f in means)
    assert "unit_mismatch" in {f["kind"] for f in brief["flags"]}  # type: ignore[attr-defined]


def test_approved_conversion_is_applied_ledgered_and_clears_the_flag(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    upload = client.post("/api/uploads", json={"text": _csv("mg/m3")}).json()
    pid = next(a["id"] for a in upload["assumptions"] if a["kind"] == "unit_conversion")
    brief = _brief(client, _csv("mg/m3"), [{"id": pid, "status": "confirmed"}])
    no2 = next(
        f
        for f in brief["facts"]  # type: ignore[attr-defined]
        if f["kind"] == "pollutant_mean" and f["values"]["pollutant"] == "NO2"
    )
    assert no2["values"]["unit"] == "ug/m3" and no2["values"]["mean"] == pytest.approx(31.5)
    assert "unit_mismatch" not in {f["kind"] for f in brief["flags"]}  # type: ignore[attr-defined]
    entry = next(e for e in brief["ledger"] if e["rule"] == "convert_unit")  # type: ignore[attr-defined]
    assert (entry["before"], entry["after"]) == ("mg/m3", "ug/m3") and "exact" in entry["reason"]
    assert "aqi_latest" in {f["kind"] for f in brief["facts"]}  # type: ignore[attr-defined]
    assert next(a for a in brief["assumptions"] if a["id"] == pid)["status"] == "confirmed"  # type: ignore[attr-defined]


def test_upload_reports_stats_and_early_flags_before_any_brief(settings: Settings) -> None:
    client = TestClient(create_app(settings, FakeLLM()))
    upload = client.post("/api/uploads", json={"text": _csv("ug/m3")}).json()
    stats = upload["stats"]
    assert stats["rows"] == 24 and stats["stations"] == ["S1"]
    assert stats["pollutants"] == ["NO2", "PM10", "PM2.5"]
    assert stats["period_start"].startswith("2024-01-01T05:30") and upload["early_flags"] == []
    bad = client.post(
        "/api/uploads", json={"text": "Station ID,Timestamp,PM2.5\nS1,nonsense,1\n" * 1}
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_timestamps"
