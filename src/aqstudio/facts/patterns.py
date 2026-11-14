"""Patterns over time: daily peak hours, trends, citywide movement, and the hourly grid."""

from typing import cast

import pandas as pd

from aqstudio.config import (
    CITYWIDE_SHARE,
    DIURNAL_MIN_DAYS,
    HOURLY_GRID_HOURS,
    HOURLY_GRID_POLLUTANT,
    PATTERN_POLLUTANTS,
    TREND_MIN_CHANGE_PCT,
    TREND_MIN_DAYS_PER_HALF,
)
from aqstudio.facts.aqi import category_for, sub_index
from aqstudio.quality.reliability import grade_for
from aqstudio.schemas import Fact, HourCell, StationHours


def diurnal_facts(
    hourly: pd.DataFrame, period: str, coverage: dict[tuple[str, str], float]
) -> list[Fact]:
    """Hour of day (IST) with the highest and lowest average, when at least two days exist."""
    facts: list[Fact] = []
    for (station, pollutant), grp in hourly.groupby(["station", "pollutant"]):
        if pollutant not in PATTERN_POLLUTANTS or grp["slot"].dt.date.nunique() < DIURNAL_MIN_DAYS:
            continue
        by_hour = grp.groupby(grp["slot"].dt.hour)["value"].mean()
        peak, low = cast(int, by_hour.idxmax()), cast(int, by_hour.idxmin())
        cov = coverage.get((str(station), str(pollutant)), 0.0)
        facts.append(
            Fact(
                kind="diurnal",
                station_id=str(station),
                period=period,
                values={
                    "pollutant": str(pollutant),
                    "peak_hour": float(peak),
                    "peak_mean": round(float(by_hour[peak]), 2),
                    "low_hour": float(low),
                    "low_mean": round(float(by_hour[low]), 2),
                    "days": float(grp["slot"].dt.date.nunique()),
                    "peak_window": f"{peak:02d}:00 to {(peak + 1) % 24:02d}:00 IST",
                },
                coverage_pct=cov,
                reliability_grade=grade_for(cov),
                evidence=[str(grp["ref"].iloc[0]), str(grp["ref"].iloc[-1])],
            )
        )
    return facts


def trend_facts(daily: pd.DataFrame, period: str, expected_days: int) -> list[Fact]:
    """First-half versus second-half daily averages, only with enough complete days."""
    facts: list[Fact] = []
    for (station, pollutant), grp in daily.groupby(["station", "pollutant"]):
        values = grp.sort_values("date")["value"].astype(float).tolist()
        half = len(values) // 2
        if pollutant not in PATTERN_POLLUTANTS or half < TREND_MIN_DAYS_PER_HALF:
            continue
        first = sum(values[:half]) / half
        second = sum(values[-half:]) / half
        change = round(100 * (second - first) / first, 1) if first else 0.0
        direction = (
            "similar" if abs(change) < TREND_MIN_CHANGE_PCT else "higher" if change > 0 else "lower"
        )
        cov = min(round(100 * len(values) / max(expected_days, 1), 1), 100.0)
        facts.append(
            Fact(
                kind="trend",
                station_id=str(station),
                period=period,
                values={
                    "pollutant": str(pollutant),
                    "first_half_mean": round(first, 2),
                    "second_half_mean": round(second, 2),
                    "change_pct": change,
                    "days": float(len(values)),
                    "direction": direction,
                },
                coverage_pct=cov,
                reliability_grade=grade_for(cov),
            )
        )
    return facts


def citywide_facts(trends: list[Fact]) -> list[Fact]:
    """Report when most stations moved the same way: a regional or weather driver, not one site."""
    facts: list[Fact] = []
    for pollutant in PATTERN_POLLUTANTS:
        moving = [t for t in trends if t.values["pollutant"] == pollutant]
        if len(moving) < 2:
            continue
        for direction in ("higher", "lower"):
            same = [t for t in moving if t.values["direction"] == direction]
            if len(same) / len(moving) >= CITYWIDE_SHARE:
                facts.append(
                    Fact(
                        kind="citywide_pattern",
                        values={
                            "pollutant": pollutant,
                            "direction": direction,
                            "stations_same_direction": float(len(same)),
                            "stations_compared": float(len(moving)),
                            "hint": "Most stations moved together, which points to a regional or "
                            "weather driver rather than one local source (hint only).",
                        },
                        coverage_pct=min(t.coverage_pct for t in same),
                        reliability_grade=min(
                            (t.reliability_grade for t in same), key=lambda g: g.value
                        ),
                    )
                )
    return facts


def hourly_grid(hourly: pd.DataFrame, end: pd.Timestamp) -> list[StationHours]:
    """The last hours of PM2.5 per station, with indicative category bands; gaps stay empty."""
    window = pd.date_range(end=end.floor("h"), periods=HOURLY_GRID_HOURS, freq="h")
    grids: list[StationHours] = []
    subset = hourly[hourly["pollutant"] == HOURLY_GRID_POLLUTANT]
    for station, grp in subset.groupby("station"):
        series = grp.set_index("slot")["value"].reindex(window)
        cells = []
        for ts, value in zip(window, series.to_numpy(), strict=True):
            index = sub_index(HOURLY_GRID_POLLUTANT, float(value)) if pd.notna(value) else None
            cells.append(
                HourCell(
                    ts=ts.isoformat(),
                    value=None if pd.isna(value) else round(float(value), 1),
                    band=None if index is None else category_for(round(index)),
                )
            )
        grids.append(
            StationHours(station_id=str(station), pollutant=HOURLY_GRID_POLLUTANT, cells=cells)
        )
    return grids
