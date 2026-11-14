"""Rule-based column mapping and assumption proposals (an LLM may refine these later)."""

import re

import pandas as pd

from aqstudio.clean.normalize import canonical_pollutant
from aqstudio.clean.stations import extract_stations
from aqstudio.config import (
    EXPECTED_UNITS,
    LAT_COLUMNS,
    LON_COLUMNS,
    MAX_POLLUTANT_CHARS,
    NON_POLLUTANT_COLUMNS,
)
from aqstudio.ingest.errors import IngestError
from aqstudio.quality.units import conversion_for, normalize_unit
from aqstudio.schemas import Assumption, ColumnMapping, RawTable

_HEADER_UNIT = re.compile(r"^(?P<name>.+?)\s*\((?P<unit>[^)]*)\)\s*$")


def split_header(header: str) -> tuple[str, str | None]:
    """Split 'PM2.5 (ug/m3)' into name and unit; unit is None when absent."""
    match = _HEADER_UNIT.match(header)
    if match:
        return match["name"].strip(), match["unit"].strip()
    return header.strip(), None


def propose_mapping(table: RawTable) -> tuple[list[ColumnMapping], list[Assumption]]:
    """Propose a meaning for each column plus the assumptions the pipeline would make."""
    mapping: list[ColumnMapping] = []
    unitless: list[str] = []
    for column in table.columns:
        key = column.lower()
        if key == "station id":
            mapping.append(ColumnMapping(column=column, meaning="station_id"))
        elif key == "timestamp":
            mapping.append(ColumnMapping(column=column, meaning="timestamp"))
        elif key == "station name":
            mapping.append(ColumnMapping(column=column, meaning="station_name"))
        elif key in LAT_COLUMNS:
            mapping.append(ColumnMapping(column=column, meaning="latitude"))
        elif key in LON_COLUMNS:
            mapping.append(ColumnMapping(column=column, meaning="longitude"))
        elif key in NON_POLLUTANT_COLUMNS:
            mapping.append(ColumnMapping(column=column, meaning="ignore"))
        else:
            name, unit = split_header(column)
            if unit is None:
                unitless.append(column)
            mapping.append(
                ColumnMapping(
                    column=column,
                    meaning="pollutant",
                    pollutant=name,
                    unit=unit,
                    confidence=1.0 if unit else 0.6,
                )
            )
    assumptions = [
        Assumption(
            id="timezone",
            kind="timezone",
            description="Timestamps without a UTC offset are read as UTC (CPCB exports are UTC).",
            proposed="UTC",
            confidence=0.8,
            confirm_label="Yes, UTC",
            alternative_label="No, they are IST",
        )
    ]
    if unitless:
        assumptions.append(
            Assumption(
                id="units",
                kind="units",
                description="These columns have no unit in the header and are assumed to use "
                f"CPCB standard units: {', '.join(unitless)}.",
                proposed=unitless,
                confidence=0.5,
            )
        )
    assumptions.extend(_conversion_proposals(mapping))
    ts_column = next(m.column for m in mapping if m.meaning == "timestamp")
    sample = pd.Series([r[table.columns.index(ts_column)] for r in table.rows[:50] if r], dtype=str)
    sample = sample[~sample.str.fullmatch(r"\s*\d{4}\s*") & (sample.str.strip() != "")]
    iso = pd.to_datetime(sample, utc=True, errors="coerce", format="ISO8601")
    if iso.isna().any():
        assumptions.append(
            Assumption(
                id="date_order",
                kind="date_order",
                description="Timestamps are not ISO formatted. They are read day-first "
                "(DD-MM-YYYY, the Indian convention).",
                proposed="day_first",
                confidence=0.6,
                confirm_label="Yes, day first",
                alternative_label="No, month first",
            )
        )
    swapped = [
        loc.station_id for loc in extract_stations(table, mapping) if loc.problem == "swapped"
    ]
    if swapped:
        assumptions.append(
            Assumption(
                id="coordinates_swapped",
                kind="coordinates",
                description="Coordinates look swapped (latitude and longitude) for: "
                f"{', '.join(swapped)}. Confirm to swap them; otherwise these stations get no "
                "map position.",
                proposed={"station_ids": swapped},
                confidence=0.7,
                default_applied=False,
                confirm_label="Swap them",
                alternative_label="Leave them off the map",
            )
        )
    return mapping, assumptions


def _conversion_proposals(mapping: list[ColumnMapping]) -> list[Assumption]:
    """One approvable conversion per column whose unit differs from CPCB's but has a safe fix."""
    proposals: list[Assumption] = []
    for m in mapping:
        if m.meaning != "pollutant" or not m.pollutant or not m.unit:
            continue
        pollutant, unit = canonical_pollutant(m.pollutant), normalize_unit(m.unit)
        conversion = conversion_for(pollutant, unit)
        if conversion is None:
            continue
        how = "exact" if conversion.exact else "approximate, at 25 C and 1 atm"
        proposals.append(
            Assumption(
                id=f"convert_unit:{m.column}",
                kind="unit_conversion",
                description=f"{pollutant} is labelled '{unit}' but CPCB uses "
                f"'{EXPECTED_UNITS[pollutant]}'. Multiply its values by {conversion.factor:g} "
                f"({how})? Until you approve, {pollutant} is left out of the statistics and AQI.",
                proposed={
                    "column": m.column,
                    "pollutant": pollutant,
                    "from_unit": conversion.from_unit,
                    "to_unit": conversion.to_unit,
                    "factor": conversion.factor,
                    "exact": conversion.exact,
                },
                confidence=0.9 if conversion.exact else 0.6,
                default_applied=False,
                confirm_label="Approve conversion",
                alternative_label="Keep it excluded",
            )
        )
    return proposals


def validate_mapping(table: RawTable, mapping: list[ColumnMapping]) -> None:
    """Check a user-supplied mapping against the table; raise IngestError if unusable."""
    known = set(table.columns)
    unknown = [m.column for m in mapping if m.column not in known]
    if unknown:
        raise IngestError(
            f"Mapping refers to unknown columns: {', '.join(unknown)}.", "invalid_mapping"
        )
    for meaning in ("station_id", "timestamp"):
        if sum(m.meaning == meaning for m in mapping) != 1:
            raise IngestError(f"Mapping needs exactly one '{meaning}' column.", "invalid_mapping")
    too_long = [m.pollutant for m in mapping if len(m.pollutant or "") > MAX_POLLUTANT_CHARS]
    if too_long:
        raise IngestError("Pollutant names must be short.", "invalid_mapping")
    lat_count = sum(m.meaning == "latitude" for m in mapping)
    lon_count = sum(m.meaning == "longitude" for m in mapping)
    if lat_count != lon_count or lat_count > 1:
        raise IngestError(
            "Mapping needs both or neither of one 'latitude' and one 'longitude' column.",
            "invalid_mapping",
        )
    if not any(m.meaning == "pollutant" and m.pollutant for m in mapping):
        raise IngestError("Mapping needs at least one pollutant column.", "invalid_mapping")
