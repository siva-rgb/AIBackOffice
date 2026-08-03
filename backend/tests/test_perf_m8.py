"""M8 — Performance first pass tests."""
from __future__ import annotations

import inspect
import pathlib
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app import store
from app.clients import pool
from app.dependencies import get_current_user
from app.main import app
from app.models import Invoice, User
from app.services import llm, supervisor
from app.services.import_jobs import create_job, get_job, run_import_job
from app.utils.csv_parser import ParsedRow
from app.utils.request_cache import begin_request_cache, end_request_cache, request_cached

client = TestClient(app)


def test_dashboard_indexes_migration_exists():
    path = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "2026-07-28_perf_dashboard_indexes.sql"
    text = path.read_text(encoding="utf-8")
    assert "idx_transactions_user_date" in text
    assert "idx_invoices_user_created" in text
    assert "idx_agent_logs_user_created" in text


_FAKE_SUPABASE_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSJ9.test-signature"


def test_supabase_client_is_singleton(monkeypatch):
    monkeypatch.setattr("app.clients.pool.settings.SUPABASE_URL", "http://localhost:54321")
    monkeypatch.setattr("app.clients.pool.settings.SUPABASE_SERVICE_ROLE_KEY", _FAKE_SUPABASE_JWT)
    pool.close_pools()
    a = pool.get_supabase()
    b = pool.get_supabase()
    assert a is b
    pool.close_pools()


def test_request_cache_dedupes_gather_state():
    calls = {"n": 0}

    @request_cached
    def _expensive(uid: str) -> str:
        calls["n"] += 1
        return uid

    begin_request_cache()
    try:
        assert _expensive("u1") == "u1"
        assert _expensive("u1") == "u1"
        assert calls["n"] == 1
    finally:
        end_request_cache()


def test_csv_upload_returns_processing_job(user_id, monkeypatch):
    user = User(id=user_id, email="u@example.com", plan="free", created_at=datetime.now(timezone.utc).isoformat())
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr("app.routers.bookkeeping.check_rate_limit", lambda *a, **k: MagicMock(allowed=True))

    csv = "Date,Description,Amount\n2026-01-01,Test,-10.00\n"
    r = client.post("/api/bookkeeping/upload", files={"file": ("bank.csv", csv, "text/csv")})
    app.dependency_overrides.pop(get_current_user, None)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "processing"
    assert body["jobId"]


def test_import_job_completes(user_id):
    job_id = create_job(user_id)
    rows = [ParsedRow(date="2026-01-01", description="Coffee", amount=-4.5, type="expense")]
    run_import_job(job_id, user_id, "USD", rows)
    job = get_job(job_id, user_id)
    assert job["status"] == "done"
    assert job["inserted"] >= 1


def test_import_job_state_is_store_backed(user_id):
    """R1 durability fix: job state lives in the store (shared/durable in prod),
    not a per-process module dict — so it survives across workers/restarts."""
    from app.services import import_jobs
    from app import store

    # The old in-process job dict must be gone (anti-regression).
    assert not hasattr(import_jobs, "_jobs")

    job_id = create_job(user_id)
    # Retrievable straight from the store layer, keyed by (user, job).
    row = store.get_import_job(user_id, job_id)
    assert row is not None
    assert row["status"] == "pending"


def test_import_job_is_tenant_scoped(user_id):
    other = str(uuid.uuid4())
    job_id = create_job(user_id)
    # Another tenant cannot read this job.
    assert get_job(job_id, other) is None
    from app import store

    assert store.get_import_job(other, job_id) is None


def test_invoice_pdf_endpoint_queues_background(user_id, monkeypatch):
    user = User(id=user_id, email="u@example.com", plan="free", created_at=datetime.now(timezone.utc).isoformat())
    app.dependency_overrides[get_current_user] = lambda: user

    queued: list[tuple[str, str]] = []

    def _capture(_bg, _fn, *args):
        queued.append((args[0], args[1]))

    monkeypatch.setattr("fastapi.BackgroundTasks.add_task", _capture)

    inv_id = store.uid("inv")
    store.insert_invoice(
        Invoice(
            id=inv_id,
            user_id=user_id,
            invoice_number="INV-T",
            client_name="Acme",
            client_email="a@acme.com",
            status="draft",
            total=10.0,
            due_date="2026-08-01",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )

    r = client.post(f"/api/invoices/{inv_id}/pdf")
    app.dependency_overrides.pop(get_current_user, None)
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    assert queued and queued[0][1] == inv_id


def test_async_llm_client_exists():
    assert inspect.iscoroutinefunction(llm.achat)
    assert inspect.iscoroutinefunction(llm.achat_messages)


def test_manager_chat_uses_async_agentic(monkeypatch):
    called = {"async": False}

    async def _fake_async(uid, msg, history):
        called["async"] = True
        return {"reply": "ok", "suggestedActions": [], "queued": 0, "toolsUsed": []}

    monkeypatch.setattr(supervisor, "chat_agentic_async", _fake_async)
    from app.seed import DEMO_USER_ID

    user = store.get_user(DEMO_USER_ID)
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr("app.routers.manager.check_rate_limit", lambda *a, **k: MagicMock(allowed=True))

    r = client.post("/api/manager/chat", json={"message": "hello", "history": []})
    app.dependency_overrides.pop(get_current_user, None)
    assert r.status_code == 200
    assert called["async"] is True


def test_async_chat_offloads_blocking_store_io(user_id, monkeypatch):
    """R2: the async chat path must run blocking store I/O off the event-loop
    thread (via asyncio.to_thread), not inline on the loop."""
    import asyncio
    import threading
    import types

    main_thread = threading.current_thread()
    seen: dict = {}
    real_get_user = store.get_user

    def spy_get_user(uid):
        seen["get_user_thread"] = threading.current_thread()
        return real_get_user(uid)

    monkeypatch.setattr(supervisor.store, "get_user", spy_get_user)
    monkeypatch.setattr(supervisor, "_agentic_available", lambda: True)

    async def fake_achat_messages(messages, **kwargs):
        return types.SimpleNamespace(
            tool_calls=None,
            content="hi there",
            input_tokens=1,
            output_tokens=1,
            model="mock",
        )

    monkeypatch.setattr(supervisor.llm, "achat_messages", fake_achat_messages)

    out = asyncio.run(supervisor.chat_agentic_async(user_id, "hello", []))

    assert out["reply"] == "hi there"
    assert seen.get("get_user_thread") is not None
    assert seen["get_user_thread"] is not main_thread  # offloaded, not on the loop


def test_overview_latency_smoke():
    import time

    t0 = time.perf_counter()
    r = client.get("/api/overview")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200
    assert elapsed_ms < 5000
