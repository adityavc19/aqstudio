"""Live area snapshot: CPCB AQI over a rolling 24-hour window for the nearest live monitors."""

from datetime import datetime, timedelta
from typing import Any, Protocol

from aqstudio.config import (
    EIGHT_HOUR_POLLUTANTS,
    EXPECTED_UNITS,
    HEALTH_IMPACTS,
    LIVE_MAX_AGE_HOURS,
    LIVE_STATIONS,
    LIVE_WINDOW_HOURS,
    MIN_8H_HOURS,
    MIN_DAY_HOURS,
    OPENAQ_PARAMETERS,
)
from aqstudio.facts.aqi import overall_aqi
from aqstudio.quality.units import conversion_for, normalize_unit
from aqstudio.schemas import LiveArea, LivePollutant, LiveStation

SOURCE = (
    "Readings: OpenAQ (state and central board monitors). AQI computed by this tool from the "
    "last 24 hours using CPCB rules; not an official reading."
)
INSUFFICIENT = "insufficient_data"


class PublicData(Protocol):
    """What the snapshot needs from a public-data source."""

    def locations_near(self, lat: float, lon: float) -> list[dict[str, Any]]:
        """Nearby locations."""
        ...

    def sensor_hours(self, sensor_id: int, since: datetime) -> list[dict[str, Any]]:
        """Hourly values for a sensor."""
        ...


def _utc(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def _window_value(pollutant: str, values: list[float]) -> float | None:
    """CPCB window metric: 24h mean, or the highest 8-hour mean for CO and O3."""
    if len(values) < MIN_DAY_HOURS:
        return None
    if pollutant in EIGHT_HOUR_POLLUTANTS:
        means = [
            sum(chunk) / len(chunk)
            for i in range(len(values))
            if len(chunk := values[i : i + 8]) >= MIN_8H_HOURS
        ]
        return max(means) if means else None
    return sum(values) / len(values)


def _pollutant(
    client: PublicData, sensors: list[dict[str, Any]], since: datetime
) -> LivePollutant | str | None:
    """The sensor with the most recent hours, in CPCB units; a label if its unit cannot be used."""
    best: tuple[str, str, list[float]] | None = None
    for sensor in sensors:
        name = OPENAQ_PARAMETERS[sensor["parameter"]["name"]]
        unit = normalize_unit(sensor["parameter"].get("units", ""))
        hours = client.sensor_hours(int(sensor["id"]), since)
        values = [float(h["value"]) for h in hours if isinstance(h.get("value"), int | float)]
        if best is None or len(values) > len(best[2]):
            best = (name, unit, values)
    if best is None:
        return None
    name, unit, values = best
    expected = EXPECTED_UNITS.get(name, unit)
    if unit != expected:
        conversion = conversion_for(name, unit)
        if conversion is None or not conversion.exact:
            return f"{name} ({unit})"  # never mix units or convert approximately without a person
        values = [v * conversion.factor for v in values]
    window = _window_value(name, values)
    return LivePollutant(
        pollutant=name,
        value=None if window is None else round(window, 2),
        unit=expected,
        hours=len(values),
    )


def _station(client: PublicData, location: dict[str, Any], now: datetime) -> LiveStation:
    """Compute one station's rolling-window AQI from its sensors."""
    since = now - timedelta(hours=LIVE_WINDOW_HOURS)
    by_param: dict[str, list[dict[str, Any]]] = {}
    for sensor in location.get("sensors", []):
        if sensor["parameter"]["name"] in OPENAQ_PARAMETERS:
            by_param.setdefault(sensor["parameter"]["name"], []).append(sensor)
    results = [_pollutant(client, sensors, since) for sensors in by_param.values()]
    pollutants = [r for r in results if isinstance(r, LivePollutant)]
    skipped = [r for r in results if isinstance(r, str)]
    usable = {p.pollutant: p.value for p in pollutants if p.value is not None}
    result = overall_aqi({k: v for k, v in usable.items() if v is not None})
    last = _utc((location.get("datetimeLast") or {}).get("utc")) or now
    reason = None
    if result is None:
        short = [f"{p.pollutant} ({p.hours} h)" for p in pollutants if p.value is None]
        reason = (
            "CPCB needs 3 pollutants including PM2.5 or PM10, each with 16+ hours in the last day."
        )
        if short:
            reason += " Too few hours for: " + ", ".join(short) + "."
    return LiveStation(
        name=str(location.get("name", "Unnamed station")),
        distance_km=round(float(location.get("distance", 0)) / 1000, 1),
        last_reading_age_min=int((now - last).total_seconds() // 60),
        aqi=result.aqi if result else None,
        category=result.category if result else INSUFFICIENT,
        dominant=result.dominant if result else None,
        reason=reason,
        pollutants=pollutants,
        skipped=skipped,
    )


def live_area(client: PublicData, lat: float, lon: float, now: datetime) -> LiveArea:
    """Nearest live regulatory monitors with their computed CPCB AQI."""
    fresh = []
    for location in client.locations_near(lat, lon):
        last = _utc((location.get("datetimeLast") or {}).get("utc"))
        is_monitor = location.get("isMonitor", True)
        if is_monitor and last and (now - last).total_seconds() <= LIVE_MAX_AGE_HOURS * 3600:
            fresh.append(location)
    nearest = sorted(fresh, key=lambda loc: float(loc.get("distance", 0)))[:LIVE_STATIONS]
    stations = [_station(client, loc, now) for loc in nearest]
    rated = [s for s in stations if s.aqi is not None]
    worst = max(rated, key=lambda s: s.aqi or 0).category if rated else INSUFFICIENT
    return LiveArea(
        lat=lat,
        lon=lon,
        generated_at=now,
        stations=stations,
        worst_category=worst,
        health_statement=HEALTH_IMPACTS.get(worst),
        source=SOURCE,
    )
