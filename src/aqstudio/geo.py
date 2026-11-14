"""Coordinate validation. Coordinates are never geocoded or invented, only checked."""

import math
from dataclasses import dataclass

from aqstudio.config import INDIA_BBOX


@dataclass(frozen=True)
class CoordCheck:
    """Outcome of checking a lat/lon pair; problem is None when usable."""

    lat: float | None
    lon: float | None
    problem: str | None
    detail: str = ""


def _in_india(lat: float, lon: float) -> bool:
    """True when the point falls inside the rough India bounding box."""
    lat_min, lon_min, lat_max, lon_max = INDIA_BBOX
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def check_coordinates(lat_raw: str, lon_raw: str) -> CoordCheck:
    """Validate raw latitude/longitude text; flag swapped values instead of fixing them."""
    lat_s, lon_s = lat_raw.strip(), lon_raw.strip()
    if not lat_s and not lon_s:
        return CoordCheck(None, None, "missing", "No coordinates in the data.")
    if not lat_s or not lon_s:
        return CoordCheck(None, None, "invalid", "Only one of latitude and longitude is present.")
    try:
        lat, lon = float(lat_s), float(lon_s)
    except ValueError:
        return CoordCheck(None, None, "invalid", "Coordinates are not numeric.")
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return CoordCheck(None, None, "invalid", "Coordinates are not finite numbers.")
    if lat == 0 and lon == 0:
        return CoordCheck(None, None, "invalid", "(0, 0) is a placeholder, not a location.")
    if not _in_india(lat, lon) and _in_india(lon, lat):
        return CoordCheck(lat, lon, "swapped", "Latitude and longitude look swapped.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return CoordCheck(None, None, "invalid", "Coordinates are out of range.")
    return CoordCheck(lat, lon, None)
