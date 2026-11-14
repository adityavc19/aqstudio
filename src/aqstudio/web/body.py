"""Shared extraction of pasted text or an uploaded file from a request."""

import json

from fastapi import Request
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import UploadFile

from aqstudio.config import MAX_ID_CHARS, MAX_POLLUTANT_CHARS, MAX_UPLOAD_BYTES
from aqstudio.ingest.errors import IngestError
from aqstudio.ingest.parse_wide import WideLabels
from aqstudio.ingest.parse_xlsx import xlsx_to_csv
from aqstudio.web.errors import ApiError

_ALLOWED_SUFFIXES = (".csv", ".txt", ".xlsx")


class UploadTextBody(BaseModel):
    """JSON upload body: pasted text, plus labels for a wide grid."""

    text: str
    station: str | None = Field(default=None, max_length=MAX_ID_CHARS)
    pollutant: str | None = Field(default=None, max_length=MAX_POLLUTANT_CHARS)
    unit: str | None = Field(default=None, max_length=16)


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


async def extract_text(request: Request) -> str:
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
                "Only .csv, .txt or .xlsx files are accepted. PDF is not supported yet.",
            )
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "file_too_large", "Upload exceeds the maximum file size.")
        if file.filename.lower().endswith(".xlsx"):
            try:
                return xlsx_to_csv(data)
            except IngestError as exc:
                status = 413 if exc.code == "file_too_large" else 422
                raise ApiError(status, exc.code, str(exc)) from exc
        return _decode(data)
    try:
        return UploadTextBody.model_validate(json.loads(await _read_capped(request))).text
    except (ValueError, ValidationError):
        raise ApiError(
            422, "invalid_request", "Send multipart 'file' or JSON {\"text\": ...}."
        ) from None


def _labels(station: object, pollutant: object, unit: object) -> WideLabels | None:
    """Wide-grid labels when all three are given as non-empty text."""
    parts = [str(v).strip() if isinstance(v, str) else "" for v in (station, pollutant, unit)]
    if not all(parts):
        return None
    if len(parts[0]) > MAX_ID_CHARS or len(parts[1]) > MAX_POLLUTANT_CHARS or len(parts[2]) > 16:
        raise ApiError(422, "invalid_request", "Station, pollutant or unit label is too long.")
    return WideLabels(*parts)


async def extract_labels(request: Request) -> tuple[str, WideLabels | None]:
    """Upload text plus optional wide-grid labels, from multipart fields or the JSON body."""
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        labels = _labels(form.get("station"), form.get("pollutant"), form.get("unit"))
        return await extract_text(request), labels
    body = await _read_capped(request)
    try:
        parsed = UploadTextBody.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        raise ApiError(
            422, "invalid_request", "Send multipart 'file' or JSON {\"text\": ...}."
        ) from None
    return parsed.text, _labels(parsed.station, parsed.pollutant, parsed.unit)
