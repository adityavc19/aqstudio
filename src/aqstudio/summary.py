"""Code-built station list and one-line brief summary (no LLM involved)."""

from aqstudio.config import AQI_CATEGORIES
from aqstudio.schemas import (
    BriefSummary,
    Fact,
    ReliabilityGrade,
    StationInfo,
    StationLocation,
    StationReliability,
)

INSUFFICIENT = "insufficient_data"
_CATEGORY_ORDER = [name for _, name in AQI_CATEGORIES]


def station_infos(
    locations: list[StationLocation], facts: list[Fact], reliability: list[StationReliability]
) -> list[StationInfo]:
    """Combine uploaded locations with each station's latest AQI and reliability grade."""
    latest = {f.station_id: f for f in facts if f.kind == "aqi_latest"}
    grades = {r.station_id: r.grade for r in reliability}
    infos: list[StationInfo] = []
    for loc in locations:
        fact = latest.get(loc.station_id)
        aqi = fact.values.get("aqi") if fact else None
        category = fact.values.get("category") if fact else None
        infos.append(
            StationInfo(
                station_id=loc.station_id,
                name=loc.name,
                lat=loc.lat,
                lon=loc.lon,
                aqi=float(aqi) if isinstance(aqi, int | float) else None,
                category=str(category) if category else INSUFFICIENT,
                reliability_grade=grades.get(loc.station_id, ReliabilityGrade.UNRELIABLE),
            )
        )
    return infos


def summarize(stations: list[StationInfo]) -> BriefSummary:
    """Build e.g. 'Poor at 3 of 5 stations, 1 unreliable' from station categories and grades."""
    total = len(stations)
    noun = "station" if total == 1 else "stations"
    unreliable = sum(s.reliability_grade == ReliabilityGrade.UNRELIABLE for s in stations)
    ranked = [s.category for s in stations if s.category in _CATEGORY_ORDER]
    if total == 0:
        line, worst = "No stations found in the data", INSUFFICIENT
    elif not ranked:
        line, worst = f"AQI not computable at any of {total} {noun}", INSUFFICIENT
    else:
        worst = max(ranked, key=_CATEGORY_ORDER.index)
        line = f"{worst} at {ranked.count(worst)} of {total} {noun}"
    if unreliable:
        line += f", {unreliable} unreliable"
    return BriefSummary(status_line=line, worst_category=worst, unreliable_count=unreliable)
