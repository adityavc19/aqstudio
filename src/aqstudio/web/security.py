"""Security headers, same-origin check for state-changing requests, client IP."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from aqstudio.schemas import ErrorBody
from aqstudio.web.errors import error_response

# 'unsafe-inline' for styles and https: images/scripts are allowed for the map frontend
# (Leaflet tiles and its CDN); tighten once the frontend is final.
_CSP = (
    "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https:; "
    "script-src 'self' https://unpkg.com https://cdnjs.cloudflare.com; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

Next = Callable[[Request], Awaitable[Response]]


def client_ip(request: Request) -> str:
    """Client IP for rate limiting.

    A configured trusted header (set by the host's edge, e.g. CF-Connecting-IP on Render) wins;
    otherwise the last X-Forwarded-For entry (appended by the nearest proxy), then the socket.
    """
    header = getattr(request.app.state, "trusted_ip_header", "")
    trusted = request.headers.get(header) if header else None
    if trusted:
        return trusted.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def install_security(app: FastAPI) -> None:
    """Add the origin check and security headers."""

    @app.middleware("http")
    async def origin_check(request: Request, call_next: Next) -> Response:
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        if request.method in _UNSAFE_METHODS and origin and origin.split("://")[-1] != host:
            body = ErrorBody(
                code="forbidden_origin", message="Cross-origin requests are not allowed."
            )
            return error_response(403, body)
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Next) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
