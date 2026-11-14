"""Upload route: store text and propose a mapping."""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from aqstudio.config import PREVIEW_ROWS
from aqstudio.ingest.errors import IngestError
from aqstudio.ingest.parse_long import parse_long_csv
from aqstudio.ingest.propose import propose_mapping
from aqstudio.ingest.sniff import DetectedFormat, detect_format
from aqstudio.schemas import Preview, UploadResponse
from aqstudio.web.body import extract_text
from aqstudio.web.deps import Deps, get_deps
from aqstudio.web.errors import ApiError
from aqstudio.web.security import client_ip

router = APIRouter()


@router.post("/uploads")
async def create_upload(
    request: Request, deps: Annotated[Deps, Depends(get_deps)]
) -> UploadResponse:
    """Accept a file or pasted text, detect its format, and propose a column mapping."""
    decision = deps.upload_limiter.check_and_record(client_ip(request))
    if not decision.allowed:
        raise ApiError(429, "rate_limited", decision.reason)
    deps.db.purge_expired(time.time())
    text = await extract_text(request)
    fmt = detect_format(text)
    if fmt == DetectedFormat.WIDE_GRID:
        raise ApiError(
            422,
            "unsupported_format",
            "This looks like a wide hourly grid, which has no pollutant or station labels. "
            "Wide-grid input is not supported yet; use a long-format CSV.",
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
    warnings = (
        [] if any(m.meaning == "pollutant" for m in mapping) else ["No pollutant columns found."]
    )
    upload_id = deps.uploads.create(fmt.value, text)
    return UploadResponse(
        upload_id=upload_id,
        detected_format=fmt.value,
        preview=Preview(columns=table.columns, rows=table.rows[:PREVIEW_ROWS]),
        mapping=mapping,
        assumptions=assumptions,
        warnings=warnings,
    )
