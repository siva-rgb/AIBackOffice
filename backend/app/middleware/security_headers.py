from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


# Interactive API docs (Swagger UI / ReDoc) load their JS+CSS from cdn.jsdelivr.net.
# These paths get a relaxed CSP so the docs render; every other route keeps the
# strict app policy below.
_DOCS_PATHS = ("/docs", "/redoc")

_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.jsdelivr.net; "
    "worker-src 'self' blob:; "
    "connect-src 'self'"
)

_APP_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self'; "
    "connect-src 'self' https://*.supabase.co https://api.stripe.com https://*.googleapis.com; "
    "frame-src https://js.stripe.com"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        is_docs = request.url.path in _DOCS_PATHS
        response.headers["Content-Security-Policy"] = _DOCS_CSP if is_docs else _APP_CSP
        return response
