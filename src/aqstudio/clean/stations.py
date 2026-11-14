"""Extract station names and coordinates from the upload's own columns."""

import pandas as pd

from aqstudio.geo import check_coordinates
from aqstudio.schemas import ColumnMapping, RawTable, StationLocation


def extract_stations(
    table: RawTable, mapping: list[ColumnMapping], swap_ids: frozenset[str] = frozenset()
) -> list[StationLocation]:
    """One entry per station; swapped coordinates are corrected only for ids the user confirmed."""
    cols = {m.meaning: m.column for m in mapping}
    width = len(table.columns)
    frame = pd.DataFrame([(r + [""] * width)[:width] for r in table.rows], columns=table.columns)
    has_coords = "latitude" in cols and "longitude" in cols
    stations: list[StationLocation] = []
    for station, grp in frame.groupby(cols["station_id"], sort=False):
        station_id = str(station)
        if not station_id.strip():
            continue
        name = station_id
        if "station_name" in cols:
            named = grp[cols["station_name"]].str.strip()
            name = next((n for n in named if n), station_id)
        if not has_coords:
            stations.append(
                StationLocation(
                    station_id=station_id,
                    name=name,
                    problem="missing",
                    detail="No coordinate columns in the upload.",
                )
            )
            continue
        lats, lons = grp[cols["latitude"]].str.strip(), grp[cols["longitude"]].str.strip()
        index = next((i for i, (a, b) in enumerate(zip(lats, lons, strict=True)) if a or b), 0)
        check = check_coordinates(str(lats.iloc[index]), str(lons.iloc[index]))
        lat, lon, problem = check.lat, check.lon, check.problem
        if problem == "swapped" and station_id in swap_ids and lat is not None and lon is not None:
            lat, lon, problem = lon, lat, None
        elif problem is not None:
            lat, lon = None, None
        stations.append(
            StationLocation(
                station_id=station_id,
                name=name,
                lat=lat,
                lon=lon,
                problem=problem,
                detail=check.detail if problem else "",
            )
        )
    return stations
