"""Clean a long-format RawTable into tidy IST Readings with a ledger."""

import re

import pandas as pd

from aqstudio.config import LOCAL_TZ, MISSING_TOKENS, NON_POLLUTANT_COLUMNS
from aqstudio.ingest.long_csv import IngestError
from aqstudio.schemas import CleanResult, LedgerEntry, RawTable, Reading

_HEADER_UNIT = re.compile(r"^(?P<name>.+?)\s*\((?P<unit>[^)]*)\)\s*$")


def _split_header(header: str) -> tuple[str, str]:
    """Split 'PM2.5 (ug/m3)' into name and unit; unit is 'unknown' when absent."""
    match = _HEADER_UNIT.match(header)
    if match:
        return match["name"].strip(), match["unit"].strip()
    return header.strip(), "unknown"


def _find(columns: list[str], wanted: str) -> str:
    """Return the column whose lowercase name equals wanted."""
    for column in columns:
        if column.lower() == wanted:
            return column
    raise IngestError(f"Required column '{wanted}' not found.")


def clean_long(table: RawTable) -> CleanResult:
    """Tidy a long table: drop non-timestamp rows, convert UTC to IST, null bad values."""
    id_col = _find(table.columns, "station id")
    ts_col = _find(table.columns, "timestamp")
    value_cols = [c for c in table.columns if c.lower() not in NON_POLLUTANT_COLUMNS]
    width = len(table.columns)
    frame = pd.DataFrame([(r + [""] * width)[:width] for r in table.rows], columns=table.columns)
    frame["_row"] = range(2, len(frame) + 2)  # 1-based, header is row 1

    ledger: list[LedgerEntry] = []
    # Fixed ISO format: letting pandas infer from row 1 breaks when it is a year divider.
    stamps = pd.to_datetime(frame[ts_col], utc=True, errors="coerce", format="ISO8601")
    stamps = stamps.where(~frame[ts_col].str.strip().str.fullmatch(r"\d{4}"))
    bad = frame[stamps.isna()]
    ledger.extend(
        LedgerEntry(
            row_ref=f"row{row}",
            rule="drop_non_timestamp_row",
            before=str(raw),
            after=None,
            reason="Timestamp is not parseable; likely a divider or stray row.",
        )
        for row, raw in zip(bad["_row"], bad[ts_col], strict=True)
    )
    ledger.append(
        LedgerEntry(
            row_ref="all",
            rule="utc_to_ist",
            before="UTC",
            after=LOCAL_TZ,
            reason="Hour-of-day and daily statistics must use local time.",
        )
    )

    keep = stamps.notna()
    frame = frame[keep].assign(_ts=stamps[keep].dt.tz_convert(LOCAL_TZ))
    long = frame.melt(
        id_vars=[id_col, "_ts", "_row"], value_vars=value_cols, var_name="header", value_name="raw"
    )
    raw = long["raw"].astype(str).str.strip()
    is_missing = raw.str.lower().isin(MISSING_TOKENS)
    numeric = pd.to_numeric(raw.where(~is_missing), errors="coerce")
    junk = long[numeric.isna() & ~is_missing]
    ledger.extend(
        LedgerEntry(
            row_ref=f"row{row}:{header}",
            rule="non_numeric_to_missing",
            before=str(value),
            after=None,
            reason="Value is not a number; stored as missing, not zero.",
        )
        for row, header, value in zip(junk["_row"], junk["header"], junk["raw"], strict=True)
    )

    units = {h: _split_header(h) for h in value_cols}
    long = long.assign(_value=numeric).sort_values(["header", id_col, "_ts"])
    readings = [
        Reading(
            station_id=str(station),
            timestamp=ts.to_pydatetime(),
            pollutant=units[header][0],
            value=None if pd.isna(value) else float(value),
            unit=units[header][1],
            source_row_ref=f"row{row}:{header}",
        )
        for station, ts, row, header, value in zip(
            long[id_col], long["_ts"], long["_row"], long["header"], long["_value"], strict=True
        )
    ]
    return CleanResult(readings=readings, ledger=ledger)
