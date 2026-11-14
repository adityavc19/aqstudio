"""Uniform JSON error shape: {"error": {"code", "message", "detail"}}."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from aqstudio.schemas import ErrorBody

_log = logging.getLogger("aqstudio")
_STATUS_CODES = {404: "not_found", 405: "method_not_allowed", 413: "file_too_large"}


class ApiError(Exception):
    """An error with an HTTP status and a machine-readable code."""

    def __init__(
        self, status: int, code: str, message: str, detail: dict[str, Any] | None = None
    ) -> None:
        """Store the response parts."""
        super().__init__(message)
        self.status = status
        self.body = ErrorBody(code=code, message=message, detail=detail)


def error_response(status: int, body: ErrorBody) -> JSONResponse:
    """Build the standard error response."""
    return JSONResponse({"error": body.model_dump()}, status_code=status)


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every failure uses the standard shape and leaks no internals."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.body)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e["loc"]) for e in exc.errors()]
        body = ErrorBody(
            code="invalid_request",
            message="The request is malformed or missing fields.",
            detail={"fields": fields},
        )
        return error_response(422, body)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        return error_response(exc.status_code, ErrorBody(code=code, message=str(exc.detail)))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        _log.exception("Unhandled error", exc_info=exc)
        body = ErrorBody(code="internal_error", message="Something went wrong on the server.")
        return error_response(500, body)
