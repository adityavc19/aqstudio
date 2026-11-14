import pytest

from aqstudio.clean.long import clean_long
from aqstudio.ingest.long_csv import IngestError, parse_long_csv
from aqstudio.quality.detectors import detect_all, detect_gaps
from aqstudio.schemas import FlagKind


def _csv(rows: list[str]) -> str:
    header = "Station ID,Station Name,Timestamp,PM2.5 (ug/m3),Benzene (ug/m3)"
    return "\n".join([header, *rows])


def _hourly(values: list[str], start_hour: int = 0) -> list[str]:
    return [
        f"S1,Peenya,2024-01-0{1 + (start_hour + i) // 24}T{(start_hour + i) % 24:02d}:00:00Z,{v},"
        for i, v in enumerate(values)
    ]


def test_utc_converted_to_ist_and_units_parsed() -> None:
    result = clean_long(parse_long_csv(_csv(_hourly(["10"]))))
    reading = next(r for r in result.readings if r.pollutant == "PM2.5")
    assert reading.timestamp.hour == 5 and reading.timestamp.minute == 30
    assert reading.unit == "ug/m3"
    assert any(e.rule == "utc_to_ist" for e in result.ledger)


def test_divider_row_and_bad_value_are_ledgered_not_zeroed() -> None:
    rows = ["S1,Peenya,2017,,", *_hourly(["abc", "-"])]
    result = clean_long(parse_long_csv(_csv(rows)))
    rules = [e.rule for e in result.ledger]
    assert "drop_non_timestamp_row" in rules
    assert rules.count("non_numeric_to_missing") == 1  # 'abc' only; '-' is a known missing token
    assert all(r.value is None for r in result.readings if r.pollutant == "PM2.5")


def test_ceiling_run_flagged_but_not_as_stuck() -> None:
    flags = detect_all(clean_long(parse_long_csv(_csv(_hourly(["500"] * 10)))).readings)
    kinds = {f.kind for f in flags}
    assert FlagKind.CEILING in kinds and FlagKind.STUCK not in kinds


def test_stuck_run_flagged() -> None:
    flags = detect_all(clean_long(parse_long_csv(_csv(_hourly(["42"] * 9)))).readings)
    assert FlagKind.STUCK in {f.kind for f in flags}


def test_short_ceiling_run_not_flagged() -> None:
    flags = detect_all(clean_long(parse_long_csv(_csv(_hourly(["500", "500", "30"])))).readings)
    assert FlagKind.CEILING not in {f.kind for f in flags}


def test_gap_detected_between_valid_readings() -> None:
    rows = _hourly(["10"]) + _hourly(["12"], start_hour=30)
    flags = detect_gaps(clean_long(parse_long_csv(_csv(rows))).readings)
    assert [f.kind for f in flags] == [FlagKind.GAP]


def test_empty_column_flagged() -> None:
    flags = detect_all(clean_long(parse_long_csv(_csv(_hourly(["10", "11"])))).readings)
    empty = [f for f in flags if f.kind == FlagKind.EMPTY_COLUMN]
    assert len(empty) == 1


def test_empty_file_and_missing_columns_rejected() -> None:
    with pytest.raises(IngestError):
        parse_long_csv("")
    with pytest.raises(IngestError):
        clean_long(parse_long_csv("a,b\n1,2"))
