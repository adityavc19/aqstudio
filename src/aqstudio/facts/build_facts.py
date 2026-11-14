"""Deterministic facts: coverage-aware means, CPCB AQI, PM ratio hints and hotspots."""

import pandas as pd

from aqstudio.config import (
    EIGHT_HOUR_POLLUTANTS,
    HOTSPOT_MIN_STATIONS,
    MIN_8H_HOURS,
    MIN_DAY_HOURS,
    PM_RATIO_COMBUSTION,
    PM_RATIO_DUST,
)
from aqstudio.facts.aqi import overall_aqi
from aqstudio.quality.reliability import grade_for
from aqstudio.schemas import Fact, FlagKind, QualityFlag, Reading, ReliabilityGrade

_FAULT_KINDS = {FlagKind.CEILING, FlagKind.STUCK}
_USABLE = {ReliabilityGrade.GOOD, ReliabilityGrade.FAIR}


def _clean_frame(readings: list[Reading], flags: list[QualityFlag]) -> pd.DataFrame:
    """Valid readings as a frame, with sensor-fault runs and unit-mismatched series removed."""
    frame = pd.DataFrame(
        [(r.station_id, r.pollutant, r.ts, r.value, r.unit, r.row_ref) for r in readings],
        columns=["station", "pollutant", "ts", "value", "unit", "ref"],
    )
    for flag in flags:
        if flag.pollutant is None:
            continue
        same_series = (frame["station"] == flag.station_id) & (frame["pollutant"] == flag.pollutant)
        if flag.kind == FlagKind.UNIT_MISMATCH:
            frame = frame[~same_series]
        elif flag.kind in _FAULT_KINDS and flag.start and flag.end:
            frame = frame[~(same_series & frame["ts"].between(flag.start, flag.end))]
    return frame.dropna(subset=["value"])


def _hourly(frame: pd.DataFrame) -> pd.DataFrame:
    """Hourly means per station and pollutant, keeping source refs."""
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


def _flag_ids(flags: list[QualityFlag], station: str, pollutant: str | None) -> list[str]:
    """Ids of flags that touch a station (and pollutant when given)."""
    return [
        f.id
        for f in flags
        if f.station_id == station and (pollutant is None or f.pollutant in (None, pollutant))
    ]


def build_facts(readings: list[Reading], flags: list[QualityFlag]) -> list[Fact]:
    """Compute coverage-aware facts for every station, with ids F1, F2, ..."""
    if not readings:
        return []
    frame = _clean_frame(readings, flags)
    if frame.empty:
        return []
    hourly = _hourly(frame)
    daily = _daily_values(hourly)
    facts: list[Fact] = []
    means: dict[str, dict[str, Fact]] = {}
    for station, st_hours in hourly.groupby("station"):
        station_s = str(station)
        span = max(
            int((st_hours["hour"].max() - st_hours["hour"].min()).total_seconds() // 3600) + 1, 1
        )
        period = f"{st_hours['hour'].min().date()}..{st_hours['hour'].max().date()}"
        refs: dict[str, list[str]] = {}
        for pollutant, grp in st_hours.groupby("pollutant"):
            pol = str(pollutant)
            coverage = min(round(100 * len(grp) / span, 1), 100.0)
            refs[pol] = [str(grp["ref"].iloc[0]), str(grp["ref"].iloc[-1])]
            fact = Fact(
                kind="pollutant_mean",
                station_id=station_s,
                period=period,
                values={
                    "pollutant": pol,
                    "mean": round(float(grp["value"].mean()), 2),
                    "unit": str(grp["unit"].iloc[0]),
                    "valid_hours": float(len(grp)),
                },
                coverage_pct=coverage,
                reliability_grade=grade_for(coverage),
                evidence=[*refs[pol], *_flag_ids(flags, station_s, pol)],
            )
            facts.append(fact)
            means.setdefault(station_s, {})[pol] = fact
        facts.extend(_aqi_facts(station_s, period, daily, refs, flags))
        facts.extend(_ratio_fact(station_s, period, means.get(station_s, {})))
    facts.extend(_hotspot_fact(means))
    return [f.model_copy(update={"id": f"F{i}"}) for i, f in enumerate(facts, start=1)]


def _aqi_facts(
    station: str,
    period: str,
    daily: pd.DataFrame,
    refs: dict[str, list[str]],
    flags: list[QualityFlag],
) -> list[Fact]:
    """Latest-day and worst-day AQI facts, or an insufficient-data fact."""
    days = daily[daily["station"] == station]
    results = []
    for day, grp in days.groupby("date"):
        result = overall_aqi(dict(zip(grp["pollutant"], grp["value"].astype(float), strict=True)))
        if result is not None:
            results.append((day, result))
    if not results:
        return [
            Fact(
                kind="aqi_insufficient",
                station_id=station,
                period=period,
                values={
                    "aqi": None,
                    "status": "insufficient data: CPCB needs 3 pollutants incl. PM2.5 or PM10 "
                    "with at least 16 hours each on the same day",
                },
                coverage_pct=0.0,
                reliability_grade=ReliabilityGrade.UNRELIABLE,
                evidence=_flag_ids(flags, station, None),
            )
        ]
    coverage = round(100 * len(results) / max(days["date"].nunique(), 1), 1)
    latest_day, latest = results[-1]
    worst_day, worst = max(results, key=lambda item: item[1].aqi)
    return [
        Fact(
            kind=kind,
            station_id=station,
            period=period,
            values={
                "aqi": float(res.aqi),
                "category": res.category,
                "dominant_pollutant": res.dominant,
                "date": str(day),
            },
            coverage_pct=coverage,
            reliability_grade=grade_for(coverage),
            evidence=refs.get(res.dominant, []),
        )
        for kind, day, res in (("aqi_latest", latest_day, latest), ("aqi_worst", worst_day, worst))
    ]


def _ratio_fact(station: str, period: str, means: dict[str, Fact]) -> list[Fact]:
    """PM2.5/PM10 ratio as a coarse combustion-vs-dust hint, never a conclusion."""
    pm25, pm10 = means.get("PM2.5"), means.get("PM10")
    if pm25 is None or pm10 is None:
        return []
    a, b = pm25.values["mean"], pm10.values["mean"]
    if not isinstance(a, float) or not isinstance(b, float) or b <= 0:
        return []
    ratio = round(a / b, 2)
    hint = (
        "combustion-leaning (hint only)"
        if ratio >= PM_RATIO_COMBUSTION
        else "coarse-dust-leaning (hint only)"
        if ratio <= PM_RATIO_DUST
        else "mixed (hint only)"
    )
    coverage = min(pm25.coverage_pct, pm10.coverage_pct)
    return [
        Fact(
            kind="pm_ratio",
            station_id=station,
            period=period,
            values={"ratio": ratio, "hint": hint},
            coverage_pct=coverage,
            reliability_grade=grade_for(coverage),
            evidence=[*pm25.evidence[:2], *pm10.evidence[:2]],
        )
    ]


def _hotspot_fact(means: dict[str, dict[str, Fact]]) -> list[Fact]:
    """Rank stations by PM2.5 mean, using only stations with usable coverage."""
    usable = [
        (st, m["PM2.5"])
        for st, m in means.items()
        if "PM2.5" in m and m["PM2.5"].reliability_grade in _USABLE
    ]
    if len(usable) < HOTSPOT_MIN_STATIONS:
        return []
    ranked = sorted(usable, key=lambda item: float(item[1].values["mean"] or 0), reverse=True)
    (top, top_fact), (second, second_fact) = ranked[0], ranked[1]
    return [
        Fact(
            kind="hotspot",
            values={
                "pollutant": "PM2.5",
                "top_station": top,
                "top_mean": top_fact.values["mean"],
                "runner_up_station": second,
                "runner_up_mean": second_fact.values["mean"],
                "stations_compared": float(len(ranked)),
            },
            coverage_pct=min(top_fact.coverage_pct, second_fact.coverage_pct),
            reliability_grade=min(
                top_fact.reliability_grade, second_fact.reliability_grade, key=_grade_rank
            ),
            evidence=[*top_fact.evidence[:2], *second_fact.evidence[:2]],
        )
    ]


def _grade_rank(grade: ReliabilityGrade) -> int:
    """Order grades from worst (0) to best (3)."""
    return [
        ReliabilityGrade.UNRELIABLE,
        ReliabilityGrade.POOR,
        ReliabilityGrade.FAIR,
        ReliabilityGrade.GOOD,
    ].index(grade)
