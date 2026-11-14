from aqstudio.clean.normalize import clean_long
from aqstudio.facts.build_facts import FactsResult, build_facts
from aqstudio.ingest.parse_long import parse_long_csv
from aqstudio.ingest.propose import propose_mapping
from aqstudio.quality.detectors import detect_all
from aqstudio.schemas import FlagKind, QualityFlag


def _run(text: str) -> tuple[list[QualityFlag], FactsResult]:
    table = parse_long_csv(text)
    mapping, _ = propose_mapping(table)
    readings = clean_long(table, mapping).readings
    flags = detect_all(readings)
    return flags, build_facts(readings, flags)


def _kinds(flags: list[QualityFlag]) -> set[FlagKind]:
    return {f.kind for f in flags}


def test_reported_aqi_without_its_inputs_is_flagged() -> None:
    rows = ["Station ID,Timestamp,PM2.5 (ug/m3),AQI"] + [
        f"S1,2024-01-01T{h:02d}:00:00Z,40,120" for h in range(24)
    ]
    flags, _ = _run("\n".join(rows))
    orphan = [f for f in flags if f.kind == FlagKind.ORPHAN_AQI]
    assert orphan and "not used" in orphan[0].detail


def test_zero_rainfall_filling_a_gap_is_flagged() -> None:
    rows = ["Station ID,Timestamp,PM2.5 (ug/m3),RF (mm)"] + [
        f"S1,2024-01-01T{h:02d}:00:00Z,,0" for h in range(8)
    ]
    assert FlagKind.ZERO_FILLED in _kinds(_run("\n".join(rows))[0])


def test_us_epa_scale_column_is_flagged_not_mixed() -> None:
    rows = ["Station ID,Timestamp,PM2.5 (ug/m3),US AQI"] + [
        f"S1,2024-01-01T{h:02d}:00:00Z,40,95" for h in range(4)
    ]
    assert FlagKind.SCALE_MISMATCH in _kinds(_run("\n".join(rows))[0])


def _days(stations: dict[str, int], days: int, rising: bool) -> str:
    rows = ["Station ID,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (ug/m3)"]
    for sid, base in stations.items():
        for d in range(days):
            for h in range(24):
                peak = 40 if h == 3 else 0  # 03:00 UTC is 08:30 IST
                level = base + (d * 6 if rising else 0) + peak + h % 3  # vary, so not stuck
                rows.append(f"{sid},2024-01-{d + 1:02d}T{h:02d}:00:00Z,{level},{level * 2},30")
    return "\n".join(rows)


def test_daily_peak_hour_is_found_in_ist() -> None:
    _, built = _run(_days({"S1": 50}, 2, rising=False))
    diurnal = next(
        f for f in built.facts if f.kind == "diurnal" and f.values["pollutant"] == "PM2.5"
    )
    assert diurnal.values["peak_hour"] == 8.0 and "08:00" in str(diurnal.values["peak_window"])


def test_trends_and_citywide_movement_need_enough_days() -> None:
    _, short = _run(_days({"S1": 50}, 2, rising=True))
    assert not [f for f in short.facts if f.kind == "trend"]
    _, built = _run(_days({"S1": 50, "S2": 60, "S3": 70}, 8, rising=True))
    trends = [f for f in built.facts if f.kind == "trend" and f.values["pollutant"] == "PM2.5"]
    assert len(trends) == 3 and all(t.values["direction"] == "higher" for t in trends)
    city = [f for f in built.facts if f.kind == "citywide_pattern"]
    assert city and city[0].values["stations_same_direction"] == 3.0


def test_hourly_grid_keeps_gaps_empty_and_bands_values() -> None:
    rows = ["Station ID,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (ug/m3)"] + [
        f"S1,2024-01-01T{h:02d}:00:00Z,{'' if h == 5 else 45},90,30" for h in range(24)
    ]
    _, built = _run("\n".join(rows))
    [grid] = built.hourly
    assert len(grid.cells) == 24 and grid.pollutant == "PM2.5"
    assert any(c.value is None and c.band is None for c in grid.cells)
    assert {c.band for c in grid.cells if c.value is not None} == {"Satisfactory"}
