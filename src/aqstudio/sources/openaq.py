"""Minimal OpenAQ v3 client: nearby locations and a sensor's hourly values."""

from datetime import datetime
from typing import Any

import httpx

from aqstudio.config import LIVE_RADIUS_M, OPENAQ_BASE_URL, SARVAM_TIMEOUT_S


class LiveDataError(RuntimeError):
    """Raised when the public-data service fails."""


class LiveDataBusy(LiveDataError):
    """Raised when the public-data service rate-limits us; worth retrying in a minute."""


class OpenAQClient:
    """Calls OpenAQ with the server-side key; the key never reaches the browser."""

    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        """Keep the key private; the HTTP client is injectable for tests."""
        self._http = http or httpx.Client(timeout=SARVAM_TIMEOUT_S)
        self._headers = {"X-API-Key": api_key}

    def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            response = self._http.get(
                f"{OPENAQ_BASE_URL}{path}", params=params, headers=self._headers
            )
        except httpx.HTTPError as exc:
            raise LiveDataError(f"Public data request failed ({type(exc).__name__}).") from exc
        if response.status_code == 429:
            raise LiveDataBusy("The public data service is busy. Please try again in a minute.")
        if response.status_code != 200:
            raise LiveDataError(f"Public data request failed (HTTP {response.status_code}).")
        results = response.json().get("results", [])
        return results if isinstance(results, list) else []

    def locations_near(self, lat: float, lon: float) -> list[dict[str, Any]]:
        """Monitoring locations within OpenAQ's maximum radius."""
        return self._get(
            "/locations", {"coordinates": f"{lat},{lon}", "radius": LIVE_RADIUS_M, "limit": 50}
        )

    def sensor_hours(self, sensor_id: int, since: datetime) -> list[dict[str, Any]]:
        """Hourly averages for one sensor since a time (UTC)."""
        return self._get(
            f"/sensors/{sensor_id}/hours",
            {"datetime_from": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 100},
        )
