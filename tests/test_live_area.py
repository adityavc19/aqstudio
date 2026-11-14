from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from aqstudio.config import Settings
from aqstudio.sources.live import live_area
from aqstudio.sources.openaq import LiveDataError
from aqstudio.web.app import create_app
from tests.conftest import FakeLLM

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


def _sensor(sid: int, name: str, units: str = "µg/m³") -> dict[str, Any]:
    return {"id": sid, "parameter": {"name": name, "units": units}}


def _loc(
    name: str, km: float, age_h: float, sensors: list[dict[str, Any]], monitor: bool = True
) -> dict[str, Any]:
    last = (NOW - timedelta(hours=age_h)).isoformat().replace("+00:00", "Z")
    return {
        "name": name,
        "distance": km * 1000,
        "isMonitor": monitor,
        "datetimeLast": {"utc": last},
        "sensors": sensors,
    }


class FakeOpenAQ:
    """Synthetic public data: one live monitor, one stale, one low-cost sensor, one patchy."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def locations_near(self, lat: float, lon: float) -> list[dict[str, Any]]:
        self.calls += 1
        if self.fail:
            raise LiveDataError("Public data request failed (HTTP 500).")
        return [
            _loc(
                "Live Monitor",
                2.0,
                1,
                [
                    _sensor(1, "pm25"),
                    _sensor(2, "pm10"),
                    _sensor(3, "no2"),
                    _sensor(4, "co"),
                    _sensor(9, "pm25"),
                ],
            ),
            _loc("Stale Monitor", 1.0, 72, [_sensor(5, "pm25")]),
            _loc("Low-cost Sensor", 0.5, 1, [_sensor(6, "pm25")], monitor=False),
            _loc(
                "Patchy Monitor",
                3.0,
                1,
                [_sensor(7, "pm25"), _sensor(8, "no2"), _sensor(10, "so2", "ppb")],
            ),
        ]

    def sensor_hours(self, sensor_id: int, since: datetime) -> list[dict[str, Any]]:
        self.calls += 1
        values = {1: 45.0, 2: 90.0, 3: 30.0, 4: 1500.0, 7: 200.0, 8: 20.0, 10: 5.0}
        if sensor_id == 9:
            return []  # a dead duplicate sensor next to the live one
        count = 10 if sensor_id in (7, 8) else 24
        return [{"value": values[sensor_id]} for _ in range(count)]


def test_live_area_uses_only_fresh_monitors_and_computes_rolling_aqi() -> None:
    area = live_area(FakeOpenAQ(), 12.97, 77.59, NOW)
    assert [s.name for s in area.stations] == ["Live Monitor", "Patchy Monitor"]
    live, patchy = area.stations
    assert live.aqi == 90 and live.category == "Satisfactory" and live.dominant == "PM10"
    co = next(p for p in live.pollutants if p.pollutant == "CO")
    assert co.unit == "mg/m3" and co.value == 1.5  # exact ug->mg conversion
    assert patchy.aqi is None and "Too few hours" in (patchy.reason or "")
    assert patchy.skipped == ["SO2 (ppb)"]  # approximate gas conversions are never automatic
    assert area.worst_category == "Satisfactory" and "sensitive people" in (
        area.health_statement or ""
    )


def test_endpoint_caches_limits_and_fails_honestly(settings: Settings) -> None:
    source = FakeOpenAQ()
    client = TestClient(create_app(settings, FakeLLM(), public_data=source))
    first = client.get("/api/areas/live", params={"lat": 12.9716, "lon": 77.5946})
    assert first.status_code == 200 and first.json()["stations"][0]["name"] == "Live Monitor"
    calls = source.calls
    assert client.get("/api/areas/live", params={"lat": 12.972, "lon": 77.595}).status_code == 200
    assert source.calls == calls  # same ~1 km cell served from cache
    assert client.get("/api/areas/live", params={"lat": 120, "lon": 77}).status_code == 422
    down = TestClient(create_app(settings, FakeLLM(), public_data=FakeOpenAQ(fail=True)))
    assert (
        down.get("/api/areas/live", params={"lat": 28.6, "lon": 77.2}).json()["error"]["code"]
        == "live_data_unavailable"
    )
    none = TestClient(create_app(settings, FakeLLM()))
    assert none.get("/api/areas/live", params={"lat": 28.6, "lon": 77.2}).status_code == 503


def test_unusable_units_cost_no_upstream_call_and_duplicates_stop_early() -> None:
    source = FakeOpenAQ()
    live_area(source, 12.97, 77.59, NOW)
    # 1 location call; Live Monitor: pm25 (first sensor already 24 h, dead duplicate 9 skipped),
    # pm10, no2, co; Patchy: pm25, no2; SO2 in ppb is rejected before fetching.
    assert source.calls == 1 + 4 + 2


def test_upstream_rate_limit_is_reported_as_busy(settings: Settings) -> None:
    from aqstudio.sources.openaq import LiveDataBusy

    class Busy(FakeOpenAQ):
        def locations_near(self, lat: float, lon: float) -> list[dict[str, Any]]:
            raise LiveDataBusy("The public data service is busy. Please try again in a minute.")

    client = TestClient(create_app(settings, FakeLLM(), public_data=Busy()))
    resp = client.get("/api/areas/live", params={"lat": 23.26, "lon": 77.41})
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "live_data_busy"


def test_cached_public_data_shares_sensor_hours(settings: Settings) -> None:
    from aqstudio.sources.live import CachedPublicData
    from aqstudio.store.db import Database

    source = FakeOpenAQ()
    cached = CachedPublicData(source, Database(settings.database_path))
    live_area(cached, 12.97, 77.59, NOW)
    first = source.calls
    live_area(cached, 12.97, 77.59, NOW)
    assert source.calls == first
