"""Rule-based column mapping and assumption proposals (an LLM may refine these later)."""

import re

from aqstudio.config import NON_POLLUTANT_COLUMNS
from aqstudio.ingest.errors import IngestError
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
            description="Timestamps without a UTC offset are in UTC (CPCB exports are UTC). "
            "Override to treat them as IST.",
            proposed="UTC",
            confidence=0.8,
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
    return mapping, assumptions


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
    if not any(m.meaning == "pollutant" and m.pollutant for m in mapping):
        raise IngestError("Mapping needs at least one pollutant column.", "invalid_mapping")
