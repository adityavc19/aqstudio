"""Facts derived from quality flags and reliability, so every number the LLM sees is citable."""

from aqstudio.config import MAX_FLAG_FACTS
from aqstudio.schemas import (
    Fact,
    FlagKind,
    QualityFlag,
    ReliabilityGrade,
    Severity,
    StationReliability,
)

_SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.WARN: 1, Severity.INFO: 2}


def reliability_facts(
    reliability: list[StationReliability], flags: list[QualityFlag]
) -> list[Fact]:
    """One fact per station with its reliability score and grade."""
    return [
        Fact(
            kind="station_reliability",
            station_id=r.station_id,
            values={"score": r.score, "grade": r.grade.value, "summary": " ".join(r.reasons)},
            coverage_pct=r.coverage_pct,
            reliability_grade=r.grade,
            evidence=[
                f.id for f in flags if f.station_id == r.station_id and f.kind != FlagKind.NO_COORDS
            ],
        )
        for r in reliability
    ]


def flag_facts(flags: list[QualityFlag]) -> list[Fact]:
    """The most severe quality flags as facts (capped), excluding map-only flags."""
    chosen = sorted(
        (f for f in flags if f.kind != FlagKind.NO_COORDS),
        key=lambda f: (_SEVERITY_RANK[f.severity], f.station_id, f.id),
    )[:MAX_FLAG_FACTS]
    return [
        Fact(
            kind="quality_flag",
            station_id=f.station_id,
            values={
                "kind": f.kind.value,
                "pollutant": f.pollutant or "",
                "severity": f.severity.value,
                "duration_hours": (
                    round((f.end - f.start).total_seconds() / 3600, 1)
                    if f.start and f.end
                    else None
                ),
                "detail": f.detail,
            },
            coverage_pct=100.0,
            reliability_grade=ReliabilityGrade.GOOD,
            evidence=[f.id],
        )
        for f in chosen
    ]
