"""Data-quality detectors over tidy Readings."""

from collections import defaultdict
from itertools import groupby

from aqstudio.config import (
    CEILING_MIN_RUN,
    CEILING_SENTINEL,
    GAP_MIN_HOURS,
    STUCK_MIN_RUN,
)
from aqstudio.schemas import FlagKind, QualityFlag, Reading, Severity

_Series = dict[tuple[str, str], list[Reading]]


def _by_series(readings: list[Reading]) -> _Series:
    """Group readings by (station, pollutant), ordered by time."""
    series: _Series = defaultdict(list)
    for reading in readings:
        series[(reading.station_id, reading.pollutant)].append(reading)
    return {key: sorted(rs, key=lambda r: r.timestamp) for key, rs in series.items()}


def _run_flags(
    series: _Series, kind: FlagKind, min_run: int, severity: Severity, only: float | None
) -> list[QualityFlag]:
    """Flag runs of identical non-missing values; restrict to value `only` when given."""
    flags: list[QualityFlag] = []
    for (station, _), items in series.items():
        for value, group in groupby(items, key=lambda r: r.value):
            run = list(group)
            if value is None or len(run) < min_run or (only is not None and value != only):
                continue
            flags.append(
                QualityFlag(
                    kind=kind,
                    station_id=station,
                    start=run[0].timestamp,
                    end=run[-1].timestamp,
                    severity=severity,
                    evidence_refs=[run[0].source_row_ref, run[-1].source_row_ref],
                )
            )
    return flags


def detect_ceiling(readings: list[Reading]) -> list[QualityFlag]:
    """Flag long runs of the sentinel ceiling value as sensor faults."""
    return _run_flags(
        _by_series(readings), FlagKind.CEILING, CEILING_MIN_RUN, Severity.CRITICAL, CEILING_SENTINEL
    )


def detect_stuck(readings: list[Reading]) -> list[QualityFlag]:
    """Flag long runs of identical values, excluding the sentinel ceiling."""
    flags = _run_flags(_by_series(readings), FlagKind.STUCK, STUCK_MIN_RUN, Severity.WARNING, None)
    return [f for f in flags if not _is_ceiling(readings, f)]


def _is_ceiling(readings: list[Reading], flag: QualityFlag) -> bool:
    """Return True when the flagged run is the ceiling sentinel (reported separately)."""
    return any(
        r.source_row_ref == flag.evidence_refs[0] and r.value == CEILING_SENTINEL for r in readings
    )


def detect_gaps(readings: list[Reading]) -> list[QualityFlag]:
    """Flag silences longer than the configured gap between valid readings."""
    flags: list[QualityFlag] = []
    for (station, _), items in _by_series(readings).items():
        valid = [r for r in items if r.value is not None]
        for before, after in zip(valid, valid[1:], strict=False):
            hours = (after.timestamp - before.timestamp).total_seconds() / 3600
            if hours > GAP_MIN_HOURS:
                flags.append(
                    QualityFlag(
                        kind=FlagKind.GAP,
                        station_id=station,
                        start=before.timestamp,
                        end=after.timestamp,
                        severity=Severity.WARNING,
                        evidence_refs=[before.source_row_ref, after.source_row_ref],
                    )
                )
    return flags


def detect_empty_columns(readings: list[Reading]) -> list[QualityFlag]:
    """Flag pollutants with no valid reading at all for a station."""
    return [
        QualityFlag(
            kind=FlagKind.EMPTY_COLUMN,
            station_id=station,
            severity=Severity.INFO,
            evidence_refs=[items[0].source_row_ref],
        )
        for (station, _), items in _by_series(readings).items()
        if all(r.value is None for r in items)
    ]


def detect_all(readings: list[Reading]) -> list[QualityFlag]:
    """Run every detector and return all flags."""
    return [
        *detect_ceiling(readings),
        *detect_stuck(readings),
        *detect_gaps(readings),
        *detect_empty_columns(readings),
    ]
