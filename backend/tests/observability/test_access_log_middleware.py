"""Test the AccessLogMiddleware (M11.1).

Properties verified:
  1. Every request emits exactly one structured JSON line on `kora.access`.
  2. The response carries `X-Request-ID` and matches the log line.
  3. An inbound `X-Request-ID` that is a uuid-hex is reused; a garbage one
     is replaced with a fresh uuid-hex.
  4. An unhandled exception still emits a log line (status=500) and the
     response carries `X-Request-ID`.
  5. The `authorization` header value never reaches the log line.
  6. A broken logger (closed stream / raise) does NOT break the request.
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.access_log import AccessLogMiddleware
from app.utils.request_context import current_request_id, set_user_id


@pytest.fixture
def client(caplog):
    app = FastAPI()
    app.add_middleware(AccessLogMiddleware)

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    @app.get("/api/echo-user")
    async def echo_user():
        # Simulate an auth dependency stamping the user id.
        set_user_id("user-test-1")
        return {"ok": True}

    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("intentional")

    @app.exception_handler(RuntimeError)
    async def _runtime_error_handler(request, exc):
        from starlette.responses import JSONResponse

        return JSONResponse(status_code=500, content={"error": "boom"})

    caplog.set_level(logging.INFO, logger="kora.access")
    with TestClient(app) as c:
        yield c


def _lines(caplog) -> list[dict]:
    return [
        json.loads(rec.message) for rec in caplog.records if rec.name == "kora.access"
    ]


def test_happy_path_emits_one_line_with_correlation_id(client, caplog):
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    rid = resp.headers["x-request-id"]
    assert len(rid) == 32  # uuid4 hex
    lines = _lines(caplog)
    assert len(lines) == 1
    line = lines[0]
    assert line["request_id"] == rid
    assert line["method"] == "GET"
    assert line["path"] == "/api/ping"
    assert line["route_template"] == "/api/ping"
    assert line["status"] == 200
    assert line["latency_ms"] >= 0
    assert line["user_id"] is None


def test_user_id_is_stamped_when_auth_dep_sets_it(client, caplog):
    resp = client.get("/api/echo-user")
    assert resp.status_code == 200
    line = _lines(caplog)[-1]
    assert line["user_id"] == "user-test-1"


def test_inbound_request_id_is_reused(client, caplog):
    sample = uuid.uuid4().hex
    resp = client.get("/api/ping", headers={"x-request-id": sample})
    assert resp.headers["x-request-id"] == sample
    line = _lines(caplog)[-1]
    assert line["request_id"] == sample


def test_inbound_garbage_request_id_is_replaced(client, caplog):
    resp = client.get("/api/ping", headers={"x-request-id": "<not a uuid>"})
    rid = resp.headers["x-request-id"]
    assert rid != "<not a uuid>"
    assert len(rid) == 32
    line = _lines(caplog)[-1]
    assert line["request_id"] == rid


def test_authorization_header_value_is_redacted(client, caplog):
    resp = client.get(
        "/api/ping",
        headers={"authorization": "Bearer eyJabc.def.ghi"},
    )
    assert resp.status_code == 200
    line = _lines(caplog)[-1]
    # The header dict MUST NOT contain the bearer token.
    headers_dump = json.dumps(line["headers"])
    assert "eyJabc" not in headers_dump
    assert "Bearer" not in headers_dump


def test_unhandled_exception_still_emits_a_line(client, caplog):
    resp = client.get("/api/boom")
    assert resp.status_code == 500
    assert "x-request-id" in resp.headers
    line = _lines(caplog)[-1]
    assert line["status"] == 500
    assert line["request_id"] == resp.headers["x-request-id"]


def test_context_is_closed_after_request(client):
    # Run a request, then check the ContextVar slot is empty.
    client.get("/api/ping")
    assert current_request_id() is None


def test_broken_logger_does_not_break_request(client, monkeypatch, caplog):
    """If the stdlib logger itself raises on emit, the request must still 200."""
    from app.middleware import access_log

    def boom(*_args, **_kwargs):
        raise OSError("stream closed")

    monkeypatch.setattr(access_log._logger, "info", boom)
    # The middleware swallows its own failures, but caplog will still capture
    # the *primary* logger — the broken one will hit `print()` fallback.
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers


def test_two_requests_get_distinct_ids(client, caplog):
    r1 = client.get("/api/ping")
    r2 = client.get("/api/ping")
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]
    lines = _lines(caplog)
    assert len(lines) == 2
    assert lines[0]["request_id"] != lines[1]["request_id"]
