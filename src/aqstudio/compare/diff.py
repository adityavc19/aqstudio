"""Coverage-aware comparison of two briefs."""

from aqstudio.config import COMPARE_MIN_CHANGE_PCT, COVERAGE_SHIFT_PTS
from aqstudio.schemas import (
    Brief,
    CoverageChange,
    Diff,
    Fact,
    FactChange,
    QualityFlag,
    ReliabilityGrade,
)

_HEADLINE_FIELDS = ("mean", "aqi", "ratio")
_BAD = {ReliabilityGrade.POOR, ReliabilityGrade.UNRELIABLE}


def _fact_key(fact: Fact) -> str:
    """Stable identity of a fact across briefs (ids are per-brief)."""
    return "|".join([fact.kind, fact.station_id or "", str(fact.values.get("pollutant", ""))])


def _flag_key(flag: QualityFlag) -> tuple[str, str, str]:
    """Stable identity of a flag across briefs."""
    return (flag.kind.value, flag.station_id, flag.pollutant or "")


def _headline(fact: Fact) -> tuple[str, float] | None:
    """The numeric value a fact is compared on."""
    for name in _HEADLINE_FIELDS:
        value = fact.values.get(name)
        if isinstance(value, int | float):
            return name, float(value)
    return None


def diff_briefs(before: Brief, after: Brief) -> Diff:
    """Compare facts and flags; label value changes that coincide with a coverage shift."""
    old = {_fact_key(f): f for f in before.facts}
    changed: list[FactChange] = []
    explained: list[FactChange] = []
    coverage: list[CoverageChange] = []
    for fact in after.facts:
        key = _fact_key(fact)
        prev = old.get(key)
        if prev is None:
            continue
        if prev.coverage_pct != fact.coverage_pct:
            coverage.append(
                CoverageChange(key=key, before_pct=prev.coverage_pct, after_pct=fact.coverage_pct)
            )
        now, then = _headline(fact), _headline(prev)
        if now is None or then is None or now[0] != then[0]:
            continue
        delta = now[1] - then[1]
        pct = None if then[1] == 0 else round(100 * delta / abs(then[1]), 1)
        if (pct is None and delta == 0) or (pct is not None and abs(pct) < COMPARE_MIN_CHANGE_PCT):
            continue
        change = FactChange(
            key=key,
            before_fact_id=prev.id,
            after_fact_id=fact.id,
            field=now[0],
            before=then[1],
            after=now[1],
            delta=round(delta, 2),
            delta_pct=pct,
        )
        coverage_driven = (
            abs(fact.coverage_pct - prev.coverage_pct) >= COVERAGE_SHIFT_PTS
            or fact.reliability_grade in _BAD
            or prev.reliability_grade in _BAD
        )
        (explained if coverage_driven else changed).append(change)
    old_flags = {_flag_key(f): f for f in before.flags}
    new_flags = {_flag_key(f): f for f in after.flags}
    appeared = [f for k, f in new_flags.items() if k not in old_flags]
    resolved = [f for k, f in old_flags.items() if k not in new_flags]
    return Diff(
        changed=changed,
        new_flags=appeared,
        resolved_flags=resolved,
        coverage_changes=coverage,
        explained_by_coverage=explained,
        summary_inputs={
            "genuine_changes": len(changed),
            "coverage_explained_changes": len(explained),
            "new_flags": len(appeared),
            "resolved_flags": len(resolved),
            "compared_facts": len(old.keys() & {_fact_key(f) for f in after.facts}),
        },
    )
