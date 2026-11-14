"""no_coords flags for stations without usable coordinates."""

from aqstudio.schemas import FlagKind, QualityFlag, Severity, StationLocation


def coordinate_flags(locations: list[StationLocation]) -> list[QualityFlag]:
    """One info flag per station that has no usable position for the map."""
    return [
        QualityFlag(
            kind=FlagKind.NO_COORDS,
            station_id=loc.station_id,
            severity=Severity.INFO,
            detail=loc.detail or "No usable coordinates.",
        )
        for loc in locations
        if loc.lat is None or loc.lon is None
    ]
