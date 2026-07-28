from __future__ import annotations

import secrets

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


# Interactive API docs (Swagger UI / ReDoc) load their JS+CSS from cdn.jsdelivr.net.
# These paths get a nonce-based CSP so the docs render without unsafe-inline.
_DOCS_PATHS = ("/docs", "/redoc")

# API responses are JSON — strict deny-by-default CSP (no inline scripts).
_APP_CSP = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Embedder-Policy"] = "credentialless"
        response.headers["Expect-CT"] = "max-age=86400"

        is_docs = request.url.path in _DOCS_PATHS
        if is_docs:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; "
                f"style-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.jsdelivr.net; "
                "worker-src 'self' blob:; "
                "connect-src 'self'"
            )
        else:
            response.headers["Content-Security-Policy"] = _APP_CSP
        return response
