"""Upload route: store text and propose a mapping."""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from aqstudio.clean.normalize import clean_long
from aqstudio.config import PREVIEW_ROWS
from aqstudio.ingest.errors import IngestError
from aqstudio.ingest.parse_long import parse_long_csv
from aqstudio.ingest.parse_wide import table_to_csv, wide_to_long
from aqstudio.ingest.propose import propose_mapping
from aqstudio.ingest.sniff import DetectedFormat, detect_format
from aqstudio.quality.detectors import detect_all
from aqstudio.schemas import (
    Assumption,
    ColumnMapping,
    Preview,
    QualityFlag,
    RawTable,
    Severity,
    UploadResponse,
    UploadStats,
)
from aqstudio.web.body import extract_labels
from aqstudio.web.deps import Deps, get_deps
from aqstudio.web.errors import ApiError
from aqstudio.web.security import client_ip

router = APIRouter()
_EARLY_FLAG_LIMIT = 30
_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARN: 1, Severity.INFO: 2}


def _analyse(
    table: RawTable, mapping: list[ColumnMapping], assumptions: list[Assumption]
) -> tuple[UploadStats, list[QualityFlag]]:
    """Clean with the default assumptions (no AI) so the user sees the data's problems first."""
    day_first = True if any(a.id == "date_order" for a in assumptions) else None
    cleaned = clean_long(table, mapping, False, day_first)
    flags = sorted(detect_all(cleaned.readings), key=lambda f: _SEVERITY_ORDER[f.severity])
    stamps = [r.ts for r in cleaned.readings]
    stats = UploadStats(
        rows=len(table.rows),
        stations=sorted({r.station_id for r in cleaned.readings}),
        period_start=min(stamps).isoformat() if stamps else None,
        period_end=max(stamps).isoformat() if stamps else None,
        pollutants=sorted({r.pollutant for r in cleaned.readings}),
    )
    return stats, flags[:_EARLY_FLAG_LIMIT]


@router.post("/uploads")
async def create_upload(
    request: Request, deps: Annotated[Deps, Depends(get_deps)]
) -> UploadResponse:
    """Accept a file or pasted text, detect its format, and propose a column mapping."""
    decision = deps.upload_limiter.check_and_record(client_ip(request))
    if not decision.allowed:
        raise ApiError(429, "rate_limited", decision.reason)
    deps.db.purge_expired(time.time())
    text, labels = await extract_labels(request)
    fmt = detect_format(text)
    warnings: list[str] = []
    if fmt == DetectedFormat.WIDE_GRID:
        if labels is None:
            raise ApiError(
                422,
                "labels_required",
                "This is a wide hourly grid with no station or pollutant labels. Tell us the "
                "station, pollutant and unit it measures; nothing is guessed.",
                {"needs": ["station", "pollutant", "unit"]},
            )
        try:
            grid, skipped = wide_to_long(text, labels)
        except IngestError as exc:
            raise ApiError(422, exc.code, str(exc)) from exc
        text = table_to_csv(grid)
        warnings.append(
            f"Wide grid converted for {labels.station} ({labels.pollutant}, {labels.unit}). "
            "Grid hours are read as IST clock hours."
        )
        if skipped:
            warnings.append(
                f"{skipped} day row(s) with impossible dates (e.g. 30 February) were skipped."
            )
    if fmt == DetectedFormat.UNKNOWN:
        raise ApiError(
            422,
            "unsupported_format",
            "Could not recognise the format. Expected a long CSV with 'Station ID' and "
            "'Timestamp' columns.",
        )
    try:
        table = parse_long_csv(text)
    except IngestError as exc:
        status = 413 if exc.code == "file_too_large" else 422
        raise ApiError(status, exc.code, str(exc)) from exc
    mapping, assumptions = propose_mapping(table)
    try:
        stats, early_flags = await run_in_threadpool(_analyse, table, mapping, assumptions)
    except IngestError as exc:
        raise ApiError(422, exc.code, str(exc)) from exc
    if not any(m.meaning == "pollutant" for m in mapping):
        warnings.append("No pollutant columns found.")
    upload_id = deps.uploads.create(fmt.value, text)  # wide grids are stored converted
    return UploadResponse(
        upload_id=upload_id,
        detected_format=fmt.value,
        preview=Preview(columns=table.columns, rows=table.rows[:PREVIEW_ROWS]),
        mapping=mapping,
        assumptions=assumptions,
        stats=stats,
        early_flags=early_flags,
        warnings=warnings,
    )
