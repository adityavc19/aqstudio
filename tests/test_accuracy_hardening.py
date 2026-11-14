from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from aqstudio.clean.normalize import clean_long
from aqstudio.config import Settings
from aqstudio.facts.build_facts import build_facts
from aqstudio.ingest.errors import IngestError
from aqstudio.ingest.parse_long import parse_long_csv
from aqstudio.ingest.propose import propose_mapping
from aqstudio.pipeline import build_brief
from aqstudio.quality.detectors import detect_all
from aqstudio.schemas import FlagKind, Persona
from aqstudio.store.db import Database
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM, hourly_csv, station_csv

H = "Station ID,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (ug/m3)\n"


def _run(text: str, day_first: bool | None = None):  # type: ignore[no-untyped-def]
    table = parse_long_csv(text)
    mapping, _ = propose_mapping(table)
    cleaned = clean_long(table, mapping, False, day_first)
    flags = detect_all(cleaned.readings)
    facts, daily = build_facts(cleaned.readings, flags)
    return cleaned, flags, facts, daily


def _rows(sid: str, day: int, hours: range, gap: str = "") -> str:
    return "".join(
        f"{sid},2024-01-{day:02d}T{h:02d}:00:00Z,{40 + h},{90 + h},{gap or 25 + h}\n" for h in hours
    )


def test_coverage_is_measured_against_the_whole_upload_not_the_stations_own_span() -> None:
    text = H + "".join(_rows("S1", d, range(24)) for d in range(1, 31)) + _rows("S2", 1, range(24))
    _, _, facts, _ = _run(text)
    cover = {f.station_id: f for f in facts if f.values.get("pollutant") == "PM2.5"}
    assert cover["S1"].coverage_pct == 100.0 and cover["S2"].coverage_pct < 10
    assert cover["S2"].reliability_grade.value == "unreliable"


def test_wrong_units_are_flagged_and_excluded_not_mixed_into_aqi() -> None:
    _, flags, facts, _ = _run(H.replace("NO2 (ug/m3)", "NO2 (ppb)") + _rows("S1", 1, range(24)))
    assert FlagKind.UNIT_MISMATCH in {f.kind for f in flags}
    assert not any(f.values.get("pollutant") == "NO2" for f in facts)
    assert {f.kind for f in facts} >= {"aqi_insufficient"} and "aqi_latest" not in {
        f.kind for f in facts
    }


def test_unit_spelling_variants_are_normalised_and_greek_mu_co_is_caught() -> None:
    text = H.replace("PM2.5 (ug/m3)", "PM2.5 (µg/m³)").replace("NO2 (ug/m3)", "CO (μg/m3)")
    cleaned, flags, _, _ = _run(text + _rows("S1", 1, range(24)))
    assert {r.unit for r in cleaned.readings if r.pollutant == "PM2.5"} == {"ug/m3"}
    assert any(e.rule == "normalize_unit" for e in cleaned.ledger)
    assert [f.pollutant for f in flags if f.kind == FlagKind.UNIT_MISMATCH] == ["CO"]


def test_day_first_dates_need_the_assumption_and_unreadable_dates_fail_loudly() -> None:
    text = H + "".join(f"S1,03/04/2024 {h:02d}:00,{40 + h},{90 + h},{25 + h}\n" for h in range(24))
    with pytest.raises(IngestError) as info:
        _run(text)
    assert info.value.code == "invalid_timestamps" and "03/04/2024" in str(info.value)
    _, assumptions = propose_mapping(parse_long_csv(text))
    assert "date_order" in {a.id for a in assumptions}
    day_first = _run(text, day_first=True)[0].readings[0].ts
    month_first = _run(text, day_first=False)[0].readings[0].ts
    assert (day_first.month, month_first.month) == (4, 3)


def test_daily_readings_are_treated_as_daily_not_as_one_hour_of_data() -> None:
    text = H + "".join(f"S1,2024-01-{d:02d},{40 + d},{90 + d},{25 + d}\n" for d in range(1, 31))
    _, _, facts, daily = _run(text)
    mean = next(f for f in facts if f.values.get("pollutant") == "PM2.5")
    assert daily and mean.coverage_pct == 100.0 and mean.values["valid_days"] == 30.0
    assert "aqi_latest" in {f.kind for f in facts}


def test_stuck_rules_use_duration_and_ignore_zero_rain() -> None:
    hourly = [f"S1,2024-01-01T{h:02d}:00:00Z,42,50,60\n" for h in range(9)]
    assert FlagKind.STUCK in {f.kind for f in _run(H + "".join(hourly))[1]}
    quarter = [f"S1,2024-01-01T00:{m:02d}:00Z,42,50,60\n" for m in (0, 15, 30, 45)]
    assert FlagKind.STUCK not in {f.kind for f in _run(H + "".join(quarter))[1]}
    rain = "Station ID,Timestamp,RF (mm)\n" + "".join(
        f"S1,2024-01-01T{h:02d}:00:00Z,0\n" for h in range(12)
    )
    assert FlagKind.STUCK not in {f.kind for f in _run(rain)[1]}


def test_data_that_stops_early_is_flagged_as_a_trailing_gap() -> None:
    text = H + _rows("S1", 1, range(24)) + "".join(_rows("S2", d, range(24)) for d in range(1, 6))
    gaps = [f for f in _run(text)[1] if f.kind == FlagKind.GAP and f.station_id == "S1"]
    assert gaps and all("at the end" in g.detail for g in gaps)


def test_every_number_the_model_sees_is_a_citable_fact_and_fact_cap_is_reported() -> None:
    llm = FakeLLM()
    table = parse_long_csv(station_csv([(f"S{i}", f"N{i}", "", "") for i in range(30)], False))
    mapping, assumptions = propose_mapping(table)
    brief, _ = build_brief(
        table, mapping, assumptions, False, None, frozenset(), {}, Persona.OTHER, None, None, llm
    )
    kinds = {f.kind for f in brief.facts}
    assert {"station_reliability", "pollutant_mean", "aqi_latest"} <= kinds
    assert [f.id for f in brief.facts[:3]] == ["F1", "F2", "F3"]
    assert llm.fact_counts == [150] and "150 of" in brief.notes[0]


def _client(settings: Settings, llm: FakeLLM | None = None) -> TestClient:
    return TestClient(create_app(settings, llm or FakeLLM()))


def _state(client: TestClient, text: str, **body: object) -> dict[str, object]:
    upload = client.post("/api/uploads", json={"text": text}).json()["upload_id"]
    resp = client.post("/api/briefs", json={"upload_id": upload, "persona": "school", **body})
    state = client.get(f"/api/briefs/{resp.json()['brief_id']}").json()
    assert isinstance(state, dict)
    return state


def test_unusable_uploads_fail_honestly_before_any_llm_call(settings: Settings) -> None:
    llm = FakeLLM()
    client = _client(settings, llm)
    long_id = client.post("/api/uploads", json={"text": H + _rows("X" * 65, 1, range(24))})
    assert long_id.status_code == 422 and long_id.json()["error"]["code"] == "invalid_table"
    bad_dates = client.post("/api/uploads", json={"text": H + "S1,not-a-date,1,2,3\n" * 5})
    assert bad_dates.json()["error"]["code"] == "invalid_timestamps"
    empty = _state(client, H + "".join(f"S1,2024-01-01T{h:02d}:00:00Z,,,\n" for h in range(24)))
    assert empty["error"]["code"] == "no_data" and llm.calls == 0  # type: ignore[index]


def test_oversized_cell_count_and_upload_flood_are_rejected(settings: Settings) -> None:
    client = _client(settings)
    wide = "Station ID,Timestamp," + ",".join(f"P{i} (ug/m3)" for i in range(30)) + "\n"
    body = wide + "".join(f"S1,2024-01-01T00:00:00Z,{','.join(['1'] * 30)}\n" for _ in range(9000))
    huge = client.post("/api/uploads", json={"text": body})
    assert huge.status_code == 413 and huge.json()["error"]["code"] == "file_too_large"
    codes = [
        client.post("/api/uploads", json={"text": hourly_csv()}).status_code for _ in range(61)
    ]
    assert codes.count(200) == 59 and codes[-1] == 429  # the 413 above used one slot


def test_stuck_processing_briefs_time_out_and_restarts_orphan_them(settings: Settings) -> None:
    client = _client(settings)
    deps = client.app.state.deps  # type: ignore[attr-defined]
    stale = deps.briefs.create_processing("sid", Persona.SCHOOL, None)
    with deps.db.connect() as conn:
        conn.execute("UPDATE briefs SET created_at = ? WHERE id = ?", (1.0, stale))
    state = client.get(f"/api/briefs/{stale}").json()
    assert state["status"] == "failed" and state["error"]["code"] == "timeout"
    fresh = deps.briefs.create_processing("sid", Persona.SCHOOL, None)
    restarted = _client(settings)
    assert restarted.get(f"/api/briefs/{fresh}").json()["error"]["code"] == "interrupted"


def test_expired_uploads_and_cache_are_purged(settings: Settings) -> None:
    db = Database(settings.database_path)
    old = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    with db.connect() as conn:
        conn.execute("INSERT INTO uploads VALUES ('old', ?, 'long_csv', 'x')", (old,))
        conn.execute("INSERT INTO llm_cache (key, value, created_at) VALUES ('k', '[]', ?)", (old,))
    db.purge_expired(datetime.now(UTC).timestamp())
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0
