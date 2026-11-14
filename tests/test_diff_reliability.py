from datetime import UTC, datetime

from aqstudio.compare.diff import diff_briefs
from aqstudio.quality.reliability import grade_for, station_reliability
from aqstudio.schemas import (
    Brief,
    BriefStatus,
    Fact,
    FlagKind,
    Persona,
    QualityFlag,
    ReliabilityGrade,
    Severity,
)


def _fact(mean: float, coverage: float, fid: str = "F1") -> Fact:
    return Fact(
        id=fid,
        kind="pollutant_mean",
        station_id="S1",
        values={"pollutant": "PM2.5", "mean": mean},
        coverage_pct=coverage,
        reliability_grade=grade_for(coverage),
    )


def _brief(facts: list[Fact], flags: list[QualityFlag] | None = None) -> Brief:
    return Brief(
        id="b",
        created_at=datetime.now(UTC),
        persona=Persona.OTHER,
        facts=facts,
        claims=[],
        actions=[],
        flags=flags or [],
        reliability=[],
        ledger_summary={},
        status=BriefStatus.READY,
    )


def test_genuine_change() -> None:
    diff = diff_briefs(_brief([_fact(50, 95)]), _brief([_fact(80, 94)]))
    assert len(diff.changed) == 1 and not diff.explained_by_coverage
    assert diff.changed[0].delta == 30 and diff.changed[0].delta_pct == 60.0


def test_change_explained_by_coverage_drop() -> None:
    diff = diff_briefs(_brief([_fact(80, 95)]), _brief([_fact(50, 60)]))
    assert not diff.changed and len(diff.explained_by_coverage) == 1
    assert diff.coverage_changes[0].after_pct == 60


def test_no_change_and_flag_movement() -> None:
    flag = QualityFlag(
        id="Q1", kind=FlagKind.GAP, station_id="S1", severity=Severity.WARN, detail="g"
    )
    diff = diff_briefs(_brief([_fact(50, 95)], [flag]), _brief([_fact(51, 95)]))
    assert not diff.changed and len(diff.resolved_flags) == 1 and not diff.new_flags


def test_reliability_scores_penalise_flags() -> None:
    flag = QualityFlag(
        id="Q1", kind=FlagKind.CEILING, station_id="S1", severity=Severity.CRITICAL, detail="c"
    )
    [rel] = station_reliability([_fact(50, 95)], [flag])
    assert rel.score == 80 and rel.grade == ReliabilityGrade.FAIR
