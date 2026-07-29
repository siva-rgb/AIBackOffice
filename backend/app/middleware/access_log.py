"""Access-log middleware (M11.1).

Pure ASGI middleware — *not* Starlette's `BaseHTTPMiddleware`, which has a
well-documented bug where `await call_next(...)` runs the downstream app on a
spawned anyio task and **loses the outer task's `ContextVar` writes**. Service
code (e.g. `agent_logger`) runs in that spawned task, so a contextvar set
on the outer task wouldn't be visible. Pure ASGI keeps everything on one
task, so the request_id / user_id contextvars set here are visible to
downstream services, and any `set_user_id(...)` they do is visible to our
`finally`-equivalent logging line below.

One structured JSON line per HTTP request, emitted on the standard `logging`
channel under `kora.access`. The line is intentionally **machine-first** — it
includes every key needed to join it with `agent_logs` rows and Sentry events
without post-processing:

    {
      "ts":           "2026-07-29T10:00:00.000Z",
      "request_id":   "abc123...",
      "method":       "GET",
      "path":         "/api/agents/log",
      "route_template": "/api/agents/log",     # post-routing, not raw path
      "status":       200,
      "latency_ms":   42,
      "user_id":      "uuid..." | null,
      "client_ip":    "1.2.3.4",
      "user_agent":   "kora-frontend/...",
      "headers":      { "x-forwarded-for": "...", ... }   # scrubbed
    }

PII / secrets in `headers`, `query`, and any custom field go through
`app.utils.pii_scrubber.scrub` before the line is emitted.

Failure mode: a broken log must NOT break the request. The middleware catches
its own exceptions and writes a `print()`-level fallback (the standard logger
itself can be the failure source, e.g. a closed stream).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from ..utils.pii_scrubber import scrub
from ..utils.request_context import (
    begin_request_context,
    current_user_id,
    end_request_context,
)


_ACCESS_LOGGER_NAME = "kora.access"
_logger = logging.getLogger(_ACCESS_LOGGER_NAME)


def _safe_emit(line: dict[str, Any]) -> None:
    """Best-effort emit. Never raise."""
    try:
        _logger.info(json.dumps(line, default=str, separators=(",", ":")))
    except Exception:
        try:
            print(f"[access-log] failed to emit: {line}")
        except Exception:
            pass


def _client_ip(scope: dict) -> str | None:
    headers = {
        k[5:].lower().decode(): v.decode()
        for k, v in scope.get("headers") or []
        if k.startswith(b"x-forwarded-for")
    }
    fwd = headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    client = scope.get("client")
    if client:
        return client[0]
    return None


def _ua(scope: dict) -> str | None:
    for k, v in scope.get("headers") or []:
        if k.lower() == b"user-agent":
            return v.decode(errors="replace")
    return None


def _headers_dict(scope: dict) -> dict[str, str]:
    """Decode ASGI headers, dropping the sensitive ones at the source."""
    out: dict[str, str] = {}
    sensitive = {b"authorization", b"cookie", b"set-cookie"}
    for k, v in scope.get("headers") or []:
        if k in sensitive:
            continue
        out[k.decode(errors="replace").lower()] = v.decode(errors="replace")
    return out


def _query_dict(scope: dict) -> dict[str, str]:
    raw = scope.get("query_string") or b""
    if not raw:
        return {}
    decoded = raw.decode(errors="replace")
    out: dict[str, str] = {}
    for pair in decoded.split("&"):
        if not pair:
            continue
        if "=" in pair:
            k, v = pair.split("=", 1)
        else:
            k, v = pair, ""
        out[k] = v
    return out


def _route_template_from_scope(scope: dict) -> str | None:
    """Starlette stores the matched route on `scope["route"]` after routing."""
    route = scope.get("route")
    return getattr(route, "path", None) if route else None


class AccessLogMiddleware:
    """Pure ASGI middleware.

    Implements the ASGI3 interface directly so we don't inherit Starlette's
    BaseHTTPMiddleware contextvar bug. Lifecycle:

      1. Open request scope (mint request_id, set up contextvars).
      2. Send the wrapped ASGI send() an extra `http.response.start` header
         (`X-Request-ID`) on the way down. We do this by wrapping the caller's
         `send` callable.
      3. After the response is sent, emit one structured access-log line.
      4. Close the scope.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # Pass through lifespan / websocket unchanged.
            return await self.app(scope, receive, send)

        inbound = None
        for k, v in scope.get("headers") or []:
            if k.lower() == b"x-request-id":
                inbound = v.decode(errors="replace")
                break

        request_id = begin_request_context(inbound_request_id=inbound)
        start = time.perf_counter()
        status_holder: dict[str, int] = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message.get("status", 500)
                # Stamp the request_id back on the response.
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            path = scope.get("path") or ""
            route_template = _route_template_from_scope(scope) or path
            line = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
                "method": scope.get("method"),
                "path": path,
                "route_template": route_template,
                "query": scrub(_query_dict(scope)),
                "status": status_holder["status"],
                "latency_ms": elapsed_ms,
                "user_id": current_user_id(),
                "client_ip": _client_ip(scope),
                "user_agent": _ua(scope),
                "headers": scrub(_headers_dict(scope)),
            }
            _safe_emit(line)
            end_request_context()
