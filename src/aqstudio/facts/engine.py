"""Deterministic facts: coverage-aware pollutant means and CPCB AQI per station."""

import re

import pandas as pd

from aqstudio.config import (
    EIGHT_HOUR_POLLUTANTS,
    MIN_8H_HOURS,
    MIN_COVERAGE_PCT,
    MIN_DAY_HOURS,
    POLLUTANT_ALIASES,
)
from aqstudio.facts.aqi import overall_aqi
from aqstudio.schemas import Fact, FlagKind, QualityFlag, Reading

_FAULT_KINDS = {FlagKind.CEILING, FlagKind.STUCK}


def _slug(text: str) -> str:
    """Make a safe fact-id fragment."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")


def _canonical(pollutant: str) -> str:
    """Normalise pollutant naming (e.g. Ozone -> O3)."""
    key = pollutant.strip().upper()
    return POLLUTANT_ALIASES.get(key, key)


def _frame(readings: list[Reading], flags: list[QualityFlag]) -> pd.DataFrame:
    """Valid readings as a frame, with values inside sensor-fault runs removed."""
    frame = pd.DataFrame(
        [
            (r.station_id, _canonical(r.pollutant), r.timestamp, r.value, r.unit, r.source_row_ref)
            for r in readings
        ],
        columns=["station", "pollutant", "ts", "value", "unit", "ref"],
    )
    for flag in flags:
        if flag.kind in _FAULT_KINDS and flag.start and flag.end and flag.pollutant:
            in_run = (
                (frame["station"] == flag.station_id)
                & (frame["pollutant"] == _canonical(flag.pollutant))
                & frame["ts"].between(flag.start, flag.end)
            )
            frame = frame[~in_run]
    mismatched = {
        (f.station_id, _canonical(f.pollutant or ""))
        for f in flags
        if f.kind == FlagKind.UNIT_MISMATCH
    }
    drop = [(s, p) in mismatched for s, p in zip(frame["station"], frame["pollutant"], strict=True)]
    return frame[~pd.Series(drop, index=frame.index)].dropna(subset=["value"])


def _hourly(frame: pd.DataFrame) -> pd.DataFrame:
    """Hourly means per station and pollutant, keeping first/last source refs."""
    frame = frame.assign(hour=frame["ts"].dt.floor("h"))
    return (
        frame.groupby(["station", "pollutant", "hour"])
        .agg(value=("value", "mean"), unit=("unit", "first"), ref=("ref", "first"))
        .reset_index()
    )


def _daily_values(hourly: pd.DataFrame) -> pd.DataFrame:
    """Daily metric per pollutant: 24h mean, or max rolling 8h mean for CO and O3."""
    rows: list[dict[str, object]] = []
    for (station, pollutant), grp in hourly.groupby(["station", "pollutant"]):
        series = grp.set_index("hour")["value"]
        days = pd.DatetimeIndex(series.index).date
        counts = series.groupby(days).count()
        if pollutant in EIGHT_HOUR_POLLUTANTS:
            full = series.reindex(pd.date_range(series.index.min(), series.index.max(), freq="h"))
            rolled = full.rolling(8, min_periods=MIN_8H_HOURS).mean()
            daily = rolled.groupby(pd.DatetimeIndex(rolled.index).date).max()
        else:
            daily = series.groupby(days).mean()
        rows.extend(
            {"station": station, "pollutant": pollutant, "date": day, "value": value}
            for day, value in daily.items()
            if counts.get(day, 0) >= MIN_DAY_HOURS and pd.notna(value)
        )
    return pd.DataFrame(rows, columns=["station", "pollutant", "date", "value"])


def build_facts(readings: list[Reading], flags: list[QualityFlag]) -> list[Fact]:
    """Compute coverage-aware facts for every station."""
    if not readings:
        return []
    frame = _frame(readings, flags)
    facts: list[Fact] = []
    if frame.empty:
        return facts
    hourly = _hourly(frame)
    daily = _daily_values(hourly)
    for station, st_hours in hourly.groupby("station"):
        station_s = str(station)
        span_hours = max(
            int((st_hours["hour"].max() - st_hours["hour"].min()).total_seconds() // 3600) + 1, 1
        )
        period = f"{st_hours['hour'].min().date()}..{st_hours['hour'].max().date()}"
        refs: dict[str, list[str]] = {}
        for pollutant, grp in st_hours.groupby("pollutant"):
            coverage = round(100 * len(grp) / span_hours, 1)
            refs[str(pollutant)] = [str(grp["ref"].iloc[0]), str(grp["ref"].iloc[-1])]
            facts.append(
                Fact(
                    id=f"{_slug(station_s)}.{_slug(str(pollutant))}.mean",
                    statement_data={
                        "mean": round(float(grp["value"].mean()), 2),
                        "unit": str(grp["unit"].iloc[0]),
                        "valid_hours": float(len(grp)),
                    },
                    station_id=station_s,
                    period=period,
                    coverage_pct=min(coverage, 100.0),
                    reliable=coverage >= MIN_COVERAGE_PCT,
                    evidence_refs=refs[str(pollutant)],
                )
            )
        facts.extend(_aqi_facts(station_s, period, daily, refs))
    return facts


def _aqi_facts(
    station: str, period: str, daily: pd.DataFrame, refs: dict[str, list[str]]
) -> list[Fact]:
    """Latest-day and worst-day AQI facts, or an insufficient-data fact."""
    days = daily[daily["station"] == station]
    results = []
    for day, grp in days.groupby("date"):
        result = overall_aqi(dict(zip(grp["pollutant"], grp["value"].astype(float), strict=True)))
        if result is not None:
            results.append((day, result))
    base = _slug(station)
    total_days = max(days["date"].nunique(), 1)
    coverage = round(100 * len(results) / total_days, 1) if len(days) else 0.0
    if not results:
        return [
            Fact(
                id=f"{base}.aqi.latest",
                statement_data={
                    "aqi": None,
                    "status": "insufficient data: CPCB needs 3 pollutants incl. PM2.5 or PM10 "
                    "with at least 16 hours each on the same day",
                },
                station_id=station,
                period=period,
                coverage_pct=0.0,
                reliable=False,
            )
        ]
    latest_day, latest = results[-1]
    worst_day, worst = max(results, key=lambda item: item[1].aqi)
    out = []
    for suffix, day, res in (("latest", latest_day, latest), ("worst", worst_day, worst)):
        out.append(
            Fact(
                id=f"{base}.aqi.{suffix}",
                statement_data={
                    "aqi": float(res.aqi),
                    "category": res.category,
                    "dominant_pollutant": res.dominant,
                    "date": str(day),
                },
                station_id=station,
                period=period,
                coverage_pct=coverage,
                reliable=coverage >= MIN_COVERAGE_PCT,
                evidence_refs=refs.get(res.dominant, []),
            )
        )
    return out
