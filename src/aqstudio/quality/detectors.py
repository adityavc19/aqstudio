"""Data-quality detectors over tidy Readings."""

from collections import defaultdict
from itertools import groupby

from aqstudio.config import (
    CEILING_MIN_RUN,
    CEILING_SENTINEL,
    GAP_MIN_HOURS,
    PLAUSIBLE_RANGES,
    STUCK_MIN_RUN,
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
        if value == CEILING_SENTINEL and len(run) >= CEILING_MIN_RUN
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
        if value != CEILING_SENTINEL and len(run) >= STUCK_MIN_RUN
    ]


def detect_gaps(readings: list[Reading]) -> list[QualityFlag]:
    """Flag silences longer than the configured gap between valid readings."""
    flags: list[QualityFlag] = []
    for items in _by_series(readings).values():
        valid = [r for r in items if r.value is not None]
        for before, after in zip(valid, valid[1:], strict=False):
            hours = (after.ts - before.ts).total_seconds() / 3600
            if hours > GAP_MIN_HOURS:
                flags.append(
                    _flag(
                        FlagKind.GAP,
                        Severity.WARN,
                        f"No valid data for {hours:.0f} hours.",
                        [before, after],
                    )
                )
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
    """Flag CO reported in micrograms; CPCB expects mg/m3 and the AQI would be wrong."""
    return [
        _flag(
            FlagKind.UNIT_MISMATCH,
            Severity.CRITICAL,
            "CO is labelled in micrograms; CPCB uses mg/m3. Excluded from AQI.",
            items,
        )
        for (_, pollutant), items in _by_series(readings).items()
        if pollutant == "CO" and items[0].unit.lower().replace("µ", "u").startswith("ug")
    ]


def detect_all(readings: list[Reading]) -> list[QualityFlag]:
    """Run every detector and return all flags with sequential ids (Q1, Q2, ...)."""
    flags = [
        *detect_ceiling(readings),
        *detect_stuck(readings),
        *detect_gaps(readings),
        *detect_empty_columns(readings),
        *detect_implausible(readings),
        *detect_unit_mismatch(readings),
    ]
    return [f.model_copy(update={"id": f"Q{i}"}) for i, f in enumerate(flags, start=1)]
