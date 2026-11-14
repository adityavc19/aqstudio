"""Deterministic facts: coverage-aware means, CPCB AQI, PM ratio hints and hotspots."""

from dataclasses import dataclass, field

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
from aqstudio.facts.cadence import is_daily
from aqstudio.facts.patterns import citywide_facts, diurnal_facts, hourly_grid, trend_facts
from aqstudio.quality.reliability import grade_for
from aqstudio.schemas import (
    Fact,
    FlagKind,
    QualityFlag,
    Reading,
    ReliabilityGrade,
    StationHours,
)

_FAULT_KINDS = {FlagKind.CEILING, FlagKind.STUCK}
_USABLE = {ReliabilityGrade.GOOD, ReliabilityGrade.FAIR}
_GRADE_ORDER = [
    ReliabilityGrade.UNRELIABLE,
    ReliabilityGrade.POOR,
    ReliabilityGrade.FAIR,
    ReliabilityGrade.GOOD,
]


@dataclass(frozen=True)
class FactsResult:
    """Facts (ids unassigned), whether data is daily, and the hourly grid for the UI."""

    facts: list[Fact]
    daily_cadence: bool
    hourly: list[StationHours] = field(default_factory=list)


def assign_fact_ids(facts: list[Fact]) -> list[Fact]:
    """Give facts sequential ids (F1, F2, ...) in list order."""
    return [f.model_copy(update={"id": f"F{i}"}) for i, f in enumerate(facts, start=1)]


def _all_rows(readings: list[Reading]) -> pd.DataFrame:
    """Every reading, including missing values, as a frame."""
    return pd.DataFrame(
        [(r.station_id, r.pollutant, r.ts, r.value, r.unit, r.row_ref) for r in readings],
        columns=["station", "pollutant", "ts", "value", "unit", "ref"],
    )


def _valid_rows(frame: pd.DataFrame, flags: list[QualityFlag]) -> pd.DataFrame:
    """Valid readings with sensor-fault runs and unit-mismatched series removed."""
    for flag in flags:
        if flag.pollutant is None:
            continue
        same_series = (frame["station"] == flag.station_id) & (frame["pollutant"] == flag.pollutant)
        if flag.kind == FlagKind.UNIT_MISMATCH:
            frame = frame[~same_series]
        elif flag.kind in _FAULT_KINDS and flag.start and flag.end:
            frame = frame[~(same_series & frame["ts"].between(flag.start, flag.end))]
    return frame.dropna(subset=["value"])


def _slots(frame: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Mean per station, pollutant and time slot (hour or day), keeping the first source ref."""
    frame = frame.assign(slot=frame["ts"].dt.floor(freq))
    return (
        frame.groupby(["station", "pollutant", "slot"])
        .agg(value=("value", "mean"), unit=("unit", "first"), ref=("ref", "first"))
        .reset_index()
    )


def _daily_values(slots: pd.DataFrame, daily_cadence: bool) -> pd.DataFrame:
    """Daily metric per pollutant: 24h mean, or max rolling 8h mean for CO and O3."""
    rows: list[dict[str, object]] = []
    for (station, pollutant), grp in slots.groupby(["station", "pollutant"]):
        series = grp.set_index("slot")["value"]
        days = pd.DatetimeIndex(series.index).date
        if daily_cadence:
            daily, counts = series.groupby(days).mean(), series.groupby(days).count()
            enough = dict.fromkeys(counts.index, True)
        else:
            counts = series.groupby(days).count()
            if pollutant in EIGHT_HOUR_POLLUTANTS:
                full = series.reindex(
                    pd.date_range(series.index.min(), series.index.max(), freq="h")
                )
                rolled = full.rolling(8, min_periods=MIN_8H_HOURS).mean()
                daily = rolled.groupby(pd.DatetimeIndex(rolled.index).date).max()
            else:
                daily = series.groupby(days).mean()
            enough = {d: c >= MIN_DAY_HOURS for d, c in counts.items()}
        rows.extend(
            {"station": station, "pollutant": pollutant, "date": day, "value": value}
            for day, value in daily.items()
            if enough.get(day, False) and pd.notna(value)
        )
    return pd.DataFrame(rows, columns=["station", "pollutant", "date", "value"])


def _expected_aqi_days(start: pd.Timestamp, end: pd.Timestamp, daily_cadence: bool) -> int:
    """Days in the upload's span on which a CPCB AQI could be computed if data were complete."""
    first, last = start.floor("D"), end.floor("D")
    if daily_cadence:
        return (last - first).days + 1
    stop = end.floor("h") + pd.Timedelta(hours=1)
    count = 0
    for day in pd.date_range(first, last, freq="D"):
        overlap = min(stop, day + pd.Timedelta(days=1)) - max(start.floor("h"), day)
        count += overlap >= pd.Timedelta(hours=MIN_DAY_HOURS)
    return max(count, 1)


def _flag_ids(flags: list[QualityFlag], station: str, pollutant: str | None) -> list[str]:
    """Ids of flags that touch a station (and pollutant when given), excluding map-only flags."""
    return [
        f.id
        for f in flags
        if f.station_id == station
        and f.kind != FlagKind.NO_COORDS
        and (pollutant is None or f.pollutant in (None, pollutant))
    ]


def build_facts(readings: list[Reading], flags: list[QualityFlag]) -> FactsResult:
    """Coverage-aware facts, patterns and the hourly grid."""
    if not readings:
        return FactsResult([], False)
    everything = _all_rows(readings)
    start, end = everything["ts"].min(), everything["ts"].max()
    valid = _valid_rows(everything, flags)
    if valid.empty:
        return FactsResult([], False)
    daily_cadence = is_daily(valid)
    freq, noun = ("D", "days") if daily_cadence else ("h", "hours")
    expected = (
        (end.floor("D") - start.floor("D")).days + 1
        if daily_cadence
        else int((end.floor("h") - start.floor("h")).total_seconds() // 3600) + 1
    )
    slots = _slots(valid, freq)
    daily = _daily_values(slots, daily_cadence)
    expected_days = _expected_aqi_days(start, end, daily_cadence)
    period = f"{start.date()}..{end.date()}"
    facts: list[Fact] = []
    means: dict[str, dict[str, Fact]] = {}
    for station, st_slots in slots.groupby("station"):
        station_s = str(station)
        refs: dict[str, list[str]] = {}
        for pollutant, grp in st_slots.groupby("pollutant"):
            pol = str(pollutant)
            coverage = min(round(100 * len(grp) / expected, 1), 100.0)
            refs[pol] = [str(grp["ref"].iloc[0]), str(grp["ref"].iloc[-1])]
            fact = Fact(
                kind="pollutant_mean",
                station_id=station_s,
                period=period,
                values={
                    "pollutant": pol,
                    "mean": round(float(grp["value"].mean()), 2),
                    "unit": str(grp["unit"].iloc[0]),
                    f"valid_{noun}": float(len(grp)),
                    f"expected_{noun}": float(expected),
                },
                coverage_pct=coverage,
                reliability_grade=grade_for(coverage),
                evidence=[*refs[pol], *_flag_ids(flags, station_s, pol)],
            )
            facts.append(fact)
            means.setdefault(station_s, {})[pol] = fact
        facts.extend(_aqi_facts(station_s, period, daily, refs, flags, expected_days))
        facts.extend(_ratio_fact(station_s, period, means.get(station_s, {})))
    facts.extend(_hotspot_fact(means))
    if daily_cadence:
        return FactsResult(facts, True)
    mean_coverage = {
        (f.station_id or "", str(f.values["pollutant"])): f.coverage_pct
        for f in facts
        if f.kind == "pollutant_mean"
    }
    trends = trend_facts(daily, period, expected_days)
    facts.extend(diurnal_facts(slots, period, mean_coverage))
    facts.extend(trends)
    facts.extend(citywide_facts(trends))
    return FactsResult(facts, False, hourly_grid(slots, end))


def _aqi_facts(
    station: str,
    period: str,
    daily: pd.DataFrame,
    refs: dict[str, list[str]],
    flags: list[QualityFlag],
    expected_days: int,
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
    coverage = min(round(100 * len(results) / expected_days, 1), 100.0)
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
    """Rank stations by PM2.5 mean; coverage is measured on the same window, so this is fair."""
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
                top_fact.reliability_grade, second_fact.reliability_grade, key=_GRADE_ORDER.index
            ),
            evidence=[*top_fact.evidence[:2], *second_fact.evidence[:2]],
        )
    ]
