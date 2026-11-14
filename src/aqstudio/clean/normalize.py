"""Clean a long-format RawTable into tidy IST Readings with a ledger."""

import pandas as pd

from aqstudio.config import (
    IST_OFFSET_MINUTES,
    LOCAL_TZ,
    MISSING_TOKENS,
    POLLUTANT_ALIASES,
)
from aqstudio.schemas import CleanResult, ColumnMapping, LedgerEntry, RawTable, Reading

_TZ_SUFFIX = r"(?:Z|[+-]\d{2}:?\d{2})$"


def canonical_pollutant(name: str) -> str:
    """Normalise pollutant naming (e.g. Ozone -> O3, pm2.5 -> PM2.5)."""
    key = name.strip().upper()
    return POLLUTANT_ALIASES.get(key, key)


def _column(mapping: list[ColumnMapping], meaning: str) -> str:
    """Return the single column mapped to `meaning`."""
    return next(m.column for m in mapping if m.meaning == meaning)


def clean_long(
    table: RawTable, mapping: list[ColumnMapping], naive_is_ist: bool = False
) -> CleanResult:
    """Tidy a long table: drop non-timestamp rows, convert to IST, null bad values."""
    id_col = _column(mapping, "station_id")
    ts_col = _column(mapping, "timestamp")
    pollutants = {m.column: m for m in mapping if m.meaning == "pollutant" and m.pollutant}
    width = len(table.columns)
    frame = pd.DataFrame([(r + [""] * width)[:width] for r in table.rows], columns=table.columns)
    frame["_row"] = range(2, len(frame) + 2)  # 1-based, header is row 1

    ledger: list[LedgerEntry] = []
    raw_ts = frame[ts_col].str.strip()
    # Fixed ISO format: letting pandas infer from row 1 breaks when it is a year divider.
    stamps = pd.to_datetime(raw_ts, utc=True, errors="coerce", format="ISO8601")
    stamps = stamps.where(~raw_ts.str.fullmatch(r"\d{4}"))
    if naive_is_ist:
        naive = ~raw_ts.str.contains(_TZ_SUFFIX, regex=True)
        stamps = stamps.where(~naive, stamps - pd.Timedelta(minutes=IST_OFFSET_MINUTES))
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
            rule="timezone_to_ist",
            before="IST (naive timestamps)" if naive_is_ist else "UTC",
            after=LOCAL_TZ,
            reason="Hour-of-day and daily statistics must use local time.",
        )
    )
    ledger.extend(
        LedgerEntry(
            row_ref=f"col:{m.column}",
            rule="assume_standard_unit",
            before=None,
            after="CPCB standard unit",
            reason="No unit in the header; CPCB standard units assumed.",
        )
        for m in pollutants.values()
        if m.unit is None
    )

    keep = stamps.notna()
    frame = frame[keep].assign(_ts=stamps[keep].dt.tz_convert(LOCAL_TZ))
    long = frame.melt(
        id_vars=[id_col, "_ts", "_row"],
        value_vars=list(pollutants),
        var_name="header",
        value_name="raw",
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

    names = {h: canonical_pollutant(m.pollutant or h) for h, m in pollutants.items()}
    units = {h: m.unit or "unknown" for h, m in pollutants.items()}
    long = long.assign(_value=numeric).sort_values(["header", id_col, "_ts"])
    readings = [
        Reading(
            station_id=str(station),
            ts=ts.to_pydatetime(),
            pollutant=names[header],
            value=None if pd.isna(value) else float(value),
            unit=units[header],
            row_ref=f"row{row}:{header}",
        )
        for station, ts, row, header, value in zip(
            long[id_col], long["_ts"], long["_row"], long["header"], long["_value"], strict=True
        )
    ]
    return CleanResult(readings=readings, ledger=ledger)
