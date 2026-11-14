"""Per-station reliability from fact coverage and quality flags."""

from aqstudio.config import FLAG_PENALTY, RELIABILITY_GRADES
from aqstudio.schemas import Fact, QualityFlag, ReliabilityGrade, StationReliability


def grade_for(score: float) -> ReliabilityGrade:
    """Map a 0-100 score or coverage to a reliability grade."""
    for threshold, name in RELIABILITY_GRADES:
        if score >= threshold:
            return ReliabilityGrade(name)
    return ReliabilityGrade.UNRELIABLE


def station_reliability(facts: list[Fact], flags: list[QualityFlag]) -> list[StationReliability]:
    """Score each station: mean pollutant coverage minus flag penalties."""
    coverage: dict[str, list[float]] = {}
    for fact in facts:
        if fact.kind == "pollutant_mean" and fact.station_id:
            coverage.setdefault(fact.station_id, []).append(fact.coverage_pct)
    results: list[StationReliability] = []
    for station, values in coverage.items():
        mean_cov = round(sum(values) / len(values), 1)
        station_flags = [f for f in flags if f.station_id == station]
        penalty = sum(FLAG_PENALTY[f.severity.value] for f in station_flags)
        score = round(max(0.0, min(100.0, mean_cov - penalty)), 1)
        reasons = [f"Mean pollutant coverage {mean_cov}%."]
        reasons += [
            f"{sum(f.severity.value == sev for f in station_flags)} {sev} flag(s)."
            for sev in ("critical", "warn")
            if any(f.severity.value == sev for f in station_flags)
        ]
        results.append(
            StationReliability(
                station_id=station,
                coverage_pct=mean_cov,
                score=score,
                grade=grade_for(score),
                reasons=reasons,
            )
        )
    return results
