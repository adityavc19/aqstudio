"""CPCB AQI sub-index and overall index computation."""

from pydantic import BaseModel

from aqstudio.config import (
    AQI_BREAKPOINTS,
    AQI_CATEGORIES,
    INDEX_EDGES,
    MIN_AQI_POLLUTANTS,
    PARTICULATES,
)


class AqiResult(BaseModel):
    """An overall AQI with the pollutant that set it."""

    aqi: int
    category: str
    dominant: str


def sub_index(pollutant: str, concentration: float) -> float | None:
    """Linear CPCB sub-index for one pollutant, capped at 500; None if unsupported."""
    edges = AQI_BREAKPOINTS.get(pollutant)
    if edges is None or concentration < 0:
        return None
    points = (*edges, edges[5] + (edges[5] - edges[4]))
    for k in range(6):
        if concentration <= points[k + 1]:
            span = points[k + 1] - points[k]
            frac = (concentration - points[k]) / span
            return INDEX_EDGES[k] + frac * (INDEX_EDGES[k + 1] - INDEX_EDGES[k])
    return 500.0


def category_for(aqi: int) -> str:
    """Name the CPCB category for an AQI value."""
    for upper, name in AQI_CATEGORIES:
        if aqi <= upper:
            return name
    return AQI_CATEGORIES[-1][1]


def overall_aqi(concentrations: dict[str, float]) -> AqiResult | None:
    """Worst sub-index wins; None when CPCB minimum-data rules are not met."""
    subs = {p: s for p, c in concentrations.items() if (s := sub_index(p, c)) is not None}
    if len(subs) < MIN_AQI_POLLUTANTS or not PARTICULATES & subs.keys():
        return None
    dominant = max(subs, key=lambda p: subs[p])
    aqi = round(subs[dominant])
    return AqiResult(aqi=aqi, category=category_for(aqi), dominant=dominant)
