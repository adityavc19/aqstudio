"""Data-quality detectors over tidy Readings."""

from collections import defaultdict
from itertools import groupby

from aqstudio.config import (
    CEILING_MIN_HOURS,
    CEILING_MIN_RUN,
    CEILING_SENTINEL,
    EXPECTED_UNITS,
    GAP_MIN_HOURS,
    PLAUSIBLE_RANGES,
    STUCK_MIN_HOURS,
    STUCK_MIN_RUN,
    ZERO_RUN_OK,
)
from aqstudio.schemas import FlagKind, QualityFlag, Reading, Severity

_Series = dict[tuple[str, str], list[Reading]]


def _by_series(readings: list[Reading]) -> _Series:
    """Group readings by (station, pollutant), ordered by time."""
    series: _Series = defaultdict(list)
    for reading in readings:
        series[(reading.station_id, reading.pollutant)].append(reading)
    return {key: sorted(rs, key=lambda r: r.ts) for key, rs in series.items()}


def _flag(kind: FlagKind, severity: Severity, detail: str, run: list[Reading]) -> QualityFlag:
    """Build a flag spanning a run of readings from one series."""
    return QualityFlag(
        kind=kind,
        station_id=run[0].station_id,
        pollutant=run[0].pollutant,
        start=run[0].ts,
        end=run[-1].ts,
        severity=severity,
        detail=detail,
        row_refs=[run[0].row_ref, run[-1].row_ref],
    )


def _value_runs(series: _Series) -> list[tuple[float, list[Reading]]]:
    """Runs of identical non-missing consecutive values across every series."""
    runs: list[tuple[float, list[Reading]]] = []
    for items in series.values():
        for value, group in groupby(items, key=lambda r: r.value):
            if value is not None:
                runs.append((value, list(group)))
    return runs


def _hours(run: list[Reading]) -> float:
    """Duration of a run of readings in hours."""
    return (run[-1].ts - run[0].ts).total_seconds() / 3600


def detect_ceiling(readings: list[Reading]) -> list[QualityFlag]:
    """Flag long runs of the sentinel ceiling value as probable sensor faults."""
    return [
        _flag(
            FlagKind.CEILING,
            Severity.CRITICAL,
            f"{len(run)} consecutive readings at the {CEILING_SENTINEL:g} ceiling "
            "(probable sensor fault).",
            run,
        )
        for value, run in _value_runs(_by_series(readings))
        if value == CEILING_SENTINEL
        and len(run) >= CEILING_MIN_RUN
        and _hours(run) >= CEILING_MIN_HOURS
    ]


def detect_stuck(readings: list[Reading]) -> list[QualityFlag]:
    """Flag long runs of identical values, excluding the sentinel ceiling."""
    return [
        _flag(
            FlagKind.STUCK,
            Severity.WARN,
            f"{len(run)} consecutive identical readings of {value:g} (stuck sensor?).",
            run,
        )
        for value, run in _value_runs(_by_series(readings))
        if value != CEILING_SENTINEL
        and len(run) >= STUCK_MIN_RUN
        and _hours(run) >= STUCK_MIN_HOURS
        and not (value == 0 and run[0].pollutant in ZERO_RUN_OK)
    ]


def _gap(
    items: list[Reading], start: Reading, end: Reading, hours: float, kind: str
) -> QualityFlag:
    """A gap flag between two readings (or between the upload edge and a reading)."""
    return QualityFlag(
        kind=FlagKind.GAP,
        station_id=items[0].station_id,
        pollutant=items[0].pollutant,
        start=start.ts,
        end=end.ts,
        severity=Severity.WARN,
        detail=f"No valid data for {hours:.0f} hours ({kind}).",
        row_refs=[start.row_ref, end.row_ref],
    )


def detect_gaps(readings: list[Reading]) -> list[QualityFlag]:
    """Flag silences over the configured gap, also at the start and end of the upload."""
    if not readings:
        return []
    first_row = min(readings, key=lambda r: r.ts)
    last_row = max(readings, key=lambda r: r.ts)
    flags: list[QualityFlag] = []
    for items in _by_series(readings).values():
        valid = [r for r in items if r.value is not None]
        if not valid:
            continue
        lead = (valid[0].ts - first_row.ts).total_seconds() / 3600
        if lead > GAP_MIN_HOURS:
            flags.append(_gap(items, first_row, valid[0], lead, "at the start"))
        for before, after in zip(valid, valid[1:], strict=False):
            hours = (after.ts - before.ts).total_seconds() / 3600
            if hours > GAP_MIN_HOURS:
                flags.append(_gap(items, before, after, hours, "between readings"))
        trail = (last_row.ts - valid[-1].ts).total_seconds() / 3600
        if trail > GAP_MIN_HOURS:
            flags.append(_gap(items, valid[-1], last_row, trail, "at the end"))
    return flags


def detect_empty_columns(readings: list[Reading]) -> list[QualityFlag]:
    """Flag pollutants with no valid reading at all for a station."""
    return [
        _flag(FlagKind.EMPTY_COLUMN, Severity.INFO, "No valid readings in this column.", items)
        for items in _by_series(readings).values()
        if all(r.value is None for r in items)
    ]


def detect_implausible(readings: list[Reading]) -> list[QualityFlag]:
    """Flag runs of values outside configured physical ranges; values are kept, not deleted."""
    flags: list[QualityFlag] = []
    for (_, pollutant), items in _by_series(readings).items():
        bounds = PLAUSIBLE_RANGES.get(pollutant)
        if bounds is None:
            continue
        low, high = bounds
        for outside, group in groupby(
            items, key=lambda r: r.value is not None and not low <= r.value <= high
        ):
            if outside:
                run = list(group)
                flags.append(
                    _flag(
                        FlagKind.IMPLAUSIBLE,
                        Severity.WARN,
                        f"{len(run)} reading(s) outside the plausible range {low:g} to {high:g}.",
                        run,
                    )
                )
    return flags


def detect_unit_mismatch(readings: list[Reading]) -> list[QualityFlag]:
    """Flag series whose unit differs from CPCB's; they are excluded, never converted."""
    return [
        _flag(
            FlagKind.UNIT_MISMATCH,
            Severity.CRITICAL,
            f"{pollutant} is labelled '{items[0].unit}' but CPCB uses "
            f"'{EXPECTED_UNITS[pollutant]}'. Excluded from statistics and AQI; not converted.",
            items,
        )
        for (_, pollutant), items in _by_series(readings).items()
        if pollutant in EXPECTED_UNITS
        and items[0].unit != "unknown"
        and items[0].unit != EXPECTED_UNITS[pollutant]
    ]


def assign_flag_ids(flags: list[QualityFlag]) -> list[QualityFlag]:
    """Give flags sequential ids (Q1, Q2, ...) in list order."""
    return [f.model_copy(update={"id": f"Q{i}"}) for i, f in enumerate(flags, start=1)]


def detect_all(readings: list[Reading]) -> list[QualityFlag]:
    """Run every detector and return all flags with sequential ids (Q1, Q2, ...)."""
    return assign_flag_ids(
        [
            *detect_ceiling(readings),
            *detect_stuck(readings),
            *detect_gaps(readings),
            *detect_empty_columns(readings),
            *detect_implausible(readings),
            *detect_unit_mismatch(readings),
        ]
    )
