"""Shared extraction of pasted text or an uploaded file from a request."""

import json

from fastapi import Request
from pydantic import BaseModel, ValidationError
from starlette.datastructures import UploadFile

from aqstudio.config import MAX_UPLOAD_BYTES
from aqstudio.web.errors import ApiError

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
