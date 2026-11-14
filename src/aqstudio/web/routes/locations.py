"""Attach user-supplied station locations to a stored brief (map data only)."""

import csv
import io
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from aqstudio.config import MAX_LOCATION_ROWS
from aqstudio.geo import check_coordinates
from aqstudio.schemas import (
    CoordinatesSource,
    FlagKind,
    LocationMatch,
    LocationRejection,
    LocationsResponse,
    StationInfo,
)
from aqstudio.web.body import extract_text
from aqstudio.web.deps import Deps, get_deps, session_id
from aqstudio.web.errors import ApiError

router = APIRouter()
_ALIASES = {
    "station_id": ("station_id", "station", "id"),
    "lat": ("lat", "latitude"),
    "lon": ("lon", "lng", "longitude"),
}


def _norm(text: str) -> str:
    """Normalise a station id or name for matching."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _parse_rows(text: str) -> list[dict[str, str]]:
    """Read station_id/lat/lon rows from CSV text, tolerating common header spellings."""
    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
    columns: dict[str, str] = {}
    for field, names in _ALIASES.items():
        found = next((headers[n] for n in names if n in headers), None)
        if found is None:
            raise ApiError(
                422, "invalid_locations", "Locations need columns station_id, lat and lon."
            )
        columns[field] = found
    rows = [{k: (row.get(col) or "").strip() for k, col in columns.items()} for row in reader]
    if len(rows) > MAX_LOCATION_ROWS:
        raise ApiError(422, "invalid_locations", "Too many location rows.")
    return rows


@router.post("/briefs/{brief_id}/locations")
async def set_locations(
    brief_id: str, request: Request, deps: Annotated[Deps, Depends(get_deps)]
) -> LocationsResponse:
    """Update station coordinates from pasted text or a CSV. Does not re-run the LLM or analysis."""
    stored = deps.briefs.get(brief_id)
    if stored is None:
        raise ApiError(404, "not_found", "Brief not found.")
    if stored.brief is None:
        raise ApiError(409, "not_ready", "The brief is not ready yet.")
    if session_id(request) != stored.session_id:
        raise ApiError(
            403, "forbidden", "Only the browser session that created a brief can edit it."
        )
    rows = _parse_rows(await extract_text(request))
    brief = stored.brief
    by_id = {_norm(s.station_id): s for s in brief.stations}
    names: dict[str, list[StationInfo]] = {}
    for info in brief.stations:
        names.setdefault(_norm(info.name), []).append(info)
    updates: dict[str, tuple[float, float]] = {}
    matched: list[LocationMatch] = []
    unmatched: list[LocationRejection] = []
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        key = row["station_id"]
        station = by_id.get(_norm(key))
        if station is None:
            candidates = names.get(_norm(key), [])
            if len(candidates) > 1:
                unmatched.append(
                    LocationRejection(
                        row=number, file_station=key, reason="Name matches several stations."
                    )
                )
                continue
            station = candidates[0] if candidates else None
        if station is None:
            unmatched.append(
                LocationRejection(
                    row=number, file_station=key, reason="No station with this id or name."
                )
            )
            continue
        check = check_coordinates(row["lat"], row["lon"])
        if check.problem is not None or check.lat is None or check.lon is None:
            unmatched.append(LocationRejection(row=number, file_station=key, reason=check.detail))
            continue
        updates[station.station_id] = (check.lat, check.lon)
        matched.append(LocationMatch(row=number, file_station=key, station_id=station.station_id))
    if updates:
        stations = [
            s.model_copy(update={"lat": updates[s.station_id][0], "lon": updates[s.station_id][1]})
            if s.station_id in updates
            else s
            for s in brief.stations
        ]
        flags = [
            f for f in brief.flags if not (f.kind == FlagKind.NO_COORDS and f.station_id in updates)
        ]
        brief = brief.model_copy(
            update={
                "stations": stations,
                "flags": flags,
                "coordinates_source": CoordinatesSource.STATIONS_FILE,
            }
        )
        deps.briefs.save_brief(brief)
    return LocationsResponse(
        stations=brief.stations,
        coordinates_source=brief.coordinates_source,
        matched=matched,
        unmatched=unmatched,
    )
