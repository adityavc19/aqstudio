import pytest

from aqstudio.clean.normalize import clean_long
from aqstudio.ingest.errors import IngestError
from aqstudio.ingest.parse_long import parse_long_csv
from aqstudio.ingest.propose import propose_mapping, validate_mapping
from aqstudio.ingest.sniff import DetectedFormat, detect_format
from aqstudio.quality.detectors import detect_all, detect_gaps
from aqstudio.schemas import FlagKind

HEADER = "Station ID,Station Name,Timestamp,PM2.5 (ug/m3),Benzene (ug/m3)"


def _clean(rows: list[str], header: str = HEADER, ist: bool = False):  # type: ignore[no-untyped-def]
    table = parse_long_csv("\n".join([header, *rows]))
    mapping, _ = propose_mapping(table)
    return clean_long(table, mapping, ist)


def _hourly(values: list[str], start_hour: int = 0) -> list[str]:
    return [
        f"S1,Peenya,2024-01-0{1 + (start_hour + i) // 24}T{(start_hour + i) % 24:02d}:00:00Z,{v},"
        for i, v in enumerate(values)
    ]


def test_utc_to_ist_units_and_naive_ist_override() -> None:
    reading = next(r for r in _clean(_hourly(["10"])).readings if r.pollutant == "PM2.5")
    assert (reading.ts.hour, reading.ts.minute, reading.unit) == (5, 30, "ug/m3")
    naive = ["S1,P,2024-01-01 12:00:00,10,"]
    utc_hour = next(r for r in _clean(naive).readings if r.pollutant == "PM2.5").ts.hour
    ist_hour = next(r for r in _clean(naive, ist=True).readings if r.pollutant == "PM2.5").ts.hour
    assert (utc_hour, ist_hour) == (17, 12)


def test_divider_row_survives_and_bad_value_ledgered_not_zeroed() -> None:
    result = _clean(["S1,P,2017,,", *_hourly(["abc", "-"])])
    rules = [e.rule for e in result.ledger]
    assert "drop_non_timestamp_row" in rules and rules.count("non_numeric_to_missing") == 1
    assert len(result.readings) == 4 and all(
        r.value is None for r in result.readings if r.pollutant == "PM2.5"
    )


def test_ceiling_stuck_gap_empty_detectors() -> None:
    kinds = lambda vals: {f.kind for f in detect_all(_clean(_hourly(vals)).readings)}  # noqa: E731
    assert FlagKind.CEILING in kinds(["500"] * 10) and FlagKind.STUCK not in kinds(["500"] * 10)
    assert FlagKind.STUCK in kinds(["42"] * 9)
    assert FlagKind.CEILING not in kinds(["500", "500", "30"])
    assert FlagKind.EMPTY_COLUMN in kinds(["10", "11"])
    gap = _hourly(["10"]) + _hourly(["12"], start_hour=30)
    assert [f.kind for f in detect_gaps(_clean(gap).readings)] == [FlagKind.GAP]


def test_implausible_and_unit_mismatch_and_ids() -> None:
    header = "Station ID,Timestamp,PM2.5 (ug/m3),CO (ug/m3)"
    rows = [f"S1,2024-01-01T0{h}:00:00Z,{5000 if h == 2 else 20},1" for h in range(4)]
    flags = detect_all(_clean(rows, header).readings)
    kinds = {f.kind for f in flags}
    assert {FlagKind.IMPLAUSIBLE, FlagKind.UNIT_MISMATCH} <= kinds
    assert [f.id for f in flags] == [f"Q{i}" for i in range(1, len(flags) + 1)]


def test_sniff_and_mapping_validation() -> None:
    assert detect_format("Station ID,Timestamp,PM2.5\n") == DetectedFormat.LONG_CSV
    assert detect_format("Year,2017\nJanuary-2017,00:00:00,01:00:00") == DetectedFormat.WIDE_GRID
    assert detect_format("hello") == DetectedFormat.UNKNOWN
    table = parse_long_csv("\n".join([HEADER, *_hourly(["1"])]))
    mapping, assumptions = propose_mapping(table)
    assert {a.id for a in assumptions} == {"timezone"}
    validate_mapping(table, mapping)
    with pytest.raises(IngestError):
        validate_mapping(table, [m for m in mapping if m.meaning != "timestamp"])
    with pytest.raises(IngestError):
        parse_long_csv("")
