"""Live 'Air near you' from public monitors: cached, rate limited, never invented."""

import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from aqstudio.config import LIVE_CACHE_SECONDS
from aqstudio.llm.cache import cache_key
from aqstudio.schemas import LiveArea
from aqstudio.sources.live import live_area
from aqstudio.sources.openaq import LiveDataError
from aqstudio.web.deps import Deps, get_deps
from aqstudio.web.errors import ApiError
from aqstudio.web.security import client_ip

router = APIRouter()


@router.get("/areas/live")
def area_live(
    request: Request,
    deps: Annotated[Deps, Depends(get_deps)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> LiveArea:
    """Nearest live monitors with CPCB AQI over the last 24 hours (cached for 30 minutes)."""
    if deps.public_data is None:
        raise ApiError(
            503, "live_data_unavailable", "Live public data is not configured on this server."
        )
    # Round to about 1 km so nearby requests share a cache entry and upstream calls stay low.
    lat, lon = round(lat, 2), round(lon, 2)
    window = int(time.time() // LIVE_CACHE_SECONDS)
    key = cache_key(kind="live", lat=lat, lon=lon, window=window)
    hit = deps.db.cache_get(key)
    if hit is not None:
        return LiveArea.model_validate_json(hit)
    if deps.live_limiter is not None:
        decision = deps.live_limiter.check_and_record(client_ip(request))
        if not decision.allowed:
            raise ApiError(429, "rate_limited", decision.reason)
    try:
        area = live_area(deps.public_data, lat, lon, datetime.now(UTC))
    except LiveDataError as exc:
        raise ApiError(502, "live_data_unavailable", str(exc)) from exc
    if not area.stations:
        raise ApiError(
            404,
            "no_data",
            "No public monitor near this location reported in the last 3 hours. "
            "Nothing is estimated in its place.",
        )
    deps.db.cache_put(key, area.model_dump_json())
    return area
