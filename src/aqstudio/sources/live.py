"""Live area snapshot: CPCB AQI over a rolling 24-hour window for the nearest live monitors."""

import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from aqstudio.config import (
    EIGHT_HOUR_POLLUTANTS,
    EXPECTED_UNITS,
    HEALTH_IMPACTS,
    LIVE_CACHE_SECONDS,
    LIVE_MAX_AGE_HOURS,
    LIVE_STATIONS,
    LIVE_WINDOW_HOURS,
    MIN_8H_HOURS,
    MIN_DAY_HOURS,
    OPENAQ_PARAMETERS,
)
from aqstudio.facts.aqi import overall_aqi
from aqstudio.llm.cache import cache_key
from aqstudio.quality.units import conversion_for, normalize_unit
from aqstudio.schemas import LiveArea, LivePollutant, LiveStation

if TYPE_CHECKING:
    from aqstudio.store.db import Database

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
    """The sensor with the most recent hours, in CPCB units; a label if its unit cannot be used.

    Upstream calls are rationed: unusable units are rejected before fetching, and duplicate
    sensors are only tried until one has enough hours.
    """
    name = OPENAQ_PARAMETERS[sensors[0]["parameter"]["name"]]
    unit = normalize_unit(sensors[0]["parameter"].get("units", ""))
    expected = EXPECTED_UNITS.get(name, unit)
    factor = 1.0
    if unit != expected:
        conversion = conversion_for(name, unit)
        if conversion is None or not conversion.exact:
            return f"{name} ({unit})"  # never mix units or convert approximately without a person
        factor = conversion.factor
    best: list[float] | None = None
    for sensor in sensors:
        hours = client.sensor_hours(int(sensor["id"]), since)
        values = [float(h["value"]) for h in hours if isinstance(h.get("value"), int | float)]
        if best is None or len(values) > len(best):
            best = values
        if len(best) >= MIN_DAY_HOURS:
            break
    if best is None:
        return None
    values = [v * factor for v in best]
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
        health_statement=HEALTH_IMPACTS.get(result.category) if result else None,
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


class CachedPublicData:
    """Caches upstream answers for 30 minutes so nearby lookups share sensor data."""

    def __init__(self, inner: PublicData, db: "Database") -> None:
        """Wrap a public-data source with the app database as the cache."""
        self._inner = inner
        self._db = db

    def _window(self) -> int:
        return int(time.time() // LIVE_CACHE_SECONDS)

    def locations_near(self, lat: float, lon: float) -> list[dict[str, Any]]:
        """Nearby locations, cached per ~1 km cell and half hour."""
        key = cache_key(kind="oaq-loc", lat=round(lat, 2), lon=round(lon, 2), w=self._window())
        return self._cached(key, lambda: self._inner.locations_near(lat, lon))

    def sensor_hours(self, sensor_id: int, since: datetime) -> list[dict[str, Any]]:
        """A sensor's recent hours, cached per half hour."""
        key = cache_key(kind="oaq-hours", sensor=sensor_id, w=self._window())
        return self._cached(key, lambda: self._inner.sensor_hours(sensor_id, since))

    def _cached(self, key: str, fetch: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
        hit = self._db.cache_get(key)
        if hit is not None:
            data: list[dict[str, Any]] = json.loads(hit)
            return data
        result = fetch()
        self._db.cache_put(key, json.dumps(result))
        return result
