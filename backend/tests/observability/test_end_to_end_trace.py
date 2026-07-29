"""End-to-end correlation: one HTTP request, three correlated artefacts.

The M11 PLAN.md gate is:

    > A single request is traceable end-to-end in the tracing backend; a sample
    > log export contains no raw secrets or unscrubbed PII.

This test spins up a minimal FastAPI app with the real `AccessLogMiddleware`
and a probe handler that calls `agent_logger.log_action`. One request through
the probe produces all three artefacts — and they share the same
`request_id`:

  1. The response carries `X-Request-ID`.
  2. The structured access-log line (captured via caplog on `kora.access`)
     carries the same `request_id`.
  3. The `agent_logs` row written via `agent_logger` carries the same
     `request_id` (inside `output._request_id`).

If any of these three are missing or the ids disagree, the gate fails.

We use a dedicated probe app (not `app.main`) so the test only depends on the
three observability modules under test — the real app's 25 routers all have
to import cleanly and that's an integration concern owned by the smoke tests.
"""

from __future__ import annotations

import json
import logging
import re
import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.middleware.access_log import AccessLogMiddleware
from app.services import agent_logger


_UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def probe_app(caplog):
    app = FastAPI()
    app.add_middleware(AccessLogMiddleware)

    @app.post("/probe")
    async def probe(request: Request):
        # Resolve the demo user — mock mode always resolves to DEMO_USER_ID.
        from app.seed import DEMO_USER_ID

        log = agent_logger.log_action(
            user_id=DEMO_USER_ID,
            agent_type="bookkeeper",
            action="end_to_end_trace",
            output={"probe": "ok"},
        )
        # Echo a summary so the test client can confirm we ran.
        return {
            "ran": True,
            "log_id": log.id if log else None,
            "request_id": log.output.get("_request_id") if log else None,
        }

    caplog.set_level(logging.INFO, logger="kora.access")
    return app


@pytest.fixture
def client(probe_app):
    with TestClient(probe_app) as c:
        yield c


def _access_lines(caplog) -> list[dict]:
    out = []
    for rec in caplog.records:
        if rec.name != "kora.access":
            continue
        try:
            out.append(json.loads(rec.message))
        except (TypeError, ValueError):
            pass
    return out


def test_single_request_three_correlated_artefacts(client, caplog):
    resp = client.post("/probe")
    assert resp.status_code == 200
    body = resp.json()
    rid_header = resp.headers.get("x-request-id")
    assert rid_header and _UUID_HEX_RE.match(rid_header), rid_header

    # 1. agent_logger ran inside the request and saw the same request_id.
    assert body["request_id"] == rid_header

    # 2. Access log line carries the same id.
    lines = _access_lines(caplog)
    assert lines, "no access log line emitted"
    last = lines[-1]
    assert last["request_id"] == rid_header
    assert last["path"] == "/probe"
    assert last["status"] == 200
    assert last["latency_ms"] >= 0

    # 3. agent_logs row written during the request carries the same id.
    from app.seed import DEMO_USER_ID
    from app import store

    rows = [
        r for r in store.list_agent_logs(DEMO_USER_ID) if r.action == "end_to_end_trace"
    ]
    assert len(rows) == 1
    assert rows[0].output.get("_request_id") == rid_header


def test_inbound_request_id_is_propagated_through_every_artefact(client, caplog):
    sample = uuid.uuid4().hex
    resp = client.post("/probe", headers={"x-request-id": sample})
    assert resp.status_code == 200
    body = resp.json()

    assert resp.headers["x-request-id"] == sample
    assert body["request_id"] == sample

    lines = _access_lines(caplog)
    last = lines[-1]
    assert last["request_id"] == sample


def test_inbound_garbage_request_id_is_replaced(client):
    resp = client.post("/probe", headers={"x-request-id": "<not a uuid>"})
    rid = resp.headers["x-request-id"]
    assert rid != "<not a uuid>"
    assert _UUID_HEX_RE.match(rid)
    assert resp.json()["request_id"] == rid


def test_unhandled_exception_still_emits_a_log_line(caplog):
    """A 5xx response still produces a structured access log line."""
    app = FastAPI()
    app.add_middleware(AccessLogMiddleware)

    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("intentional")

    @app.exception_handler(RuntimeError)
    async def _handler(request, exc):
        from starlette.responses import JSONResponse

        return JSONResponse(status_code=500, content={"error": "boom"})

    caplog.set_level(logging.INFO, logger="kora.access")
    with TestClient(app) as c:
        resp = c.get("/api/boom")
    assert resp.status_code == 500
    assert "x-request-id" in resp.headers
    lines = _access_lines(caplog)
    last = lines[-1]
    assert last["status"] == 500
    assert last["request_id"] == resp.headers["x-request-id"]


def test_dashboard_endpoint_returns_extended_keys():
    """M11.3 — call the dashboard endpoint directly on the agents router."""
    from app.routers.agents import router as agents_router

    app = FastAPI()
    app.include_router(agents_router)

    with TestClient(app) as c:
        # The seeded demo user has zero logs; the endpoint should still return
        # the right shape with empty counters / daily series.
        resp = c.get("/api/agents/log/dashboard?window_days=7")
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "total",
            "today",
            "byType",
            "byTrigger",
            "p50LatencyMs",
            "p95LatencyMs",
            "totalTokens",
            "costByModel",
            "topErrors",
            "daily",
            "window_days",
        ):
            assert key in body, key
        assert body["window_days"] == 7
        assert isinstance(body["daily"], list)
        assert len(body["daily"]) == 7
