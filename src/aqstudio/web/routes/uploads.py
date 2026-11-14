"""Upload route: store text and propose a mapping."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ValidationError
from starlette.datastructures import UploadFile

from aqstudio.config import MAX_UPLOAD_BYTES, PREVIEW_ROWS
from aqstudio.ingest.errors import IngestError
from aqstudio.ingest.parse_long import parse_long_csv
from aqstudio.ingest.propose import propose_mapping
from aqstudio.ingest.sniff import DetectedFormat, detect_format
from aqstudio.schemas import Preview, UploadResponse
from aqstudio.web.deps import Deps, get_deps
from aqstudio.web.errors import ApiError

router = APIRouter()
_ALLOWED_SUFFIXES = (".csv", ".txt")


class UploadTextBody(BaseModel):
    """JSON upload body: pasted text."""

    text: str


async def _read_capped(request: Request) -> bytes:
    """Read the request body, refusing anything over the upload limit."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise ApiError(413, "file_too_large", "Upload exceeds the maximum file size.")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode(data: bytes) -> str:
    """Decode uploaded bytes as UTF-8 text."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(400, "invalid_encoding", "The file is not valid UTF-8 text.") from None


async def _extract_text(request: Request) -> str:
    """Get upload text from a multipart file or a JSON body."""
    content_type = request.headers.get("content-type", "")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_UPLOAD_BYTES + 4096:
        raise ApiError(413, "file_too_large", "Upload exceeds the maximum file size.")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        file = form.get("file")
        if not isinstance(file, UploadFile) or not file.filename:
            raise ApiError(422, "invalid_request", "Multipart upload needs a 'file' field.")
        if not file.filename.lower().endswith(_ALLOWED_SUFFIXES):
            raise ApiError(
                415,
                "unsupported_format",
                "Only .csv or .txt files are accepted. PDF and XLSX are not supported yet.",
            )
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "file_too_large", "Upload exceeds the maximum file size.")
        return _decode(data)
    try:
        return UploadTextBody.model_validate(json.loads(await _read_capped(request))).text
    except (ValueError, ValidationError):
        raise ApiError(
            422, "invalid_request", "Send multipart 'file' or JSON {\"text\": ...}."
        ) from None


@router.post("/uploads")
async def create_upload(
    request: Request, deps: Annotated[Deps, Depends(get_deps)]
) -> UploadResponse:
    """Accept a file or pasted text, detect its format, and propose a column mapping."""
    text = await _extract_text(request)
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
