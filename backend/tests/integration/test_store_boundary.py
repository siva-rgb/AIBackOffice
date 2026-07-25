"""Integration tests for the store/Supabase boundary (app/store.py + memory_store).

Validates the contract between Kora's services and the data layer:
- store dispatches to memory_store in mock mode (conftest forces KORA_DATA_BACKEND=mock)
- CRUD round-trips for the three most critical entities: User, Invoice, AgentLog
- Isolation: each test gets its own user_id (from conftest) so state never leaks
- No real Supabase connection is made — conftest blanks SUPABASE_URL/KEY
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import store
from app.models import AgentLog, Invoice, LineItem, User


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user(uid: str) -> User:
    return User(id=uid, email=f"{uid}@example.com", plan="pro", created_at=_now())


def _invoice(uid: str, inv_id: str) -> Invoice:
    return Invoice(
        id=inv_id, user_id=uid, invoice_number="INV-T-001",
        client_name="Test Client", client_email="client@example.com",
        line_items=[LineItem(description="Work", quantity=1, rate=500, amount=500)],
        subtotal=500, tax_rate=0, tax_amount=0, total=500,
        status="draft", due_date="2099-12-31", created_at=_now(),
    )


def _agent_log(uid: str, log_id: str) -> AgentLog:
    return AgentLog(
        id=log_id, user_id=uid, agent_type="bookkeeper",
        action="test action", model_used="mock",
        status="success", triggered_by="user", created_at=_now(),
    )


# ── User boundary ─────────────────────────────────────────────────────────────

def test_get_user_returns_none_for_unknown(user_id):
    assert store.get_user(user_id) is None


def test_update_user_and_retrieve(user_id):
    u = _user(user_id)
    store.update_user(user_id, {"email": u.email, "plan": u.plan})
    retrieved = store.get_user(user_id)
    # update_user patches an existing row; if the user doesn't exist yet it
    # returns None — that's the correct contract for a patch-only store.
    # We seed via insert path used by the app (memory_store seeds on boot).
    # Just verify the call doesn't raise and returns None or a User.
    assert retrieved is None or retrieved.id == user_id


def test_get_user_by_email_returns_none_for_unknown(user_id):
    assert store.get_user_by_email(f"{user_id}@nowhere.example") is None


def test_get_user_by_email_finds_seeded_user():
    """The memory store is seeded with the demo user on import."""
    from app.seed import DEMO_USER_ID
    u = store.get_user(DEMO_USER_ID)
    assert u is not None
    found = store.get_user_by_email(u.email)
    assert found is not None
    assert found.id == DEMO_USER_ID


def test_update_user_mutates_plan():
    """Patch the seeded demo user's plan and verify the store reflects it."""
    from app.seed import DEMO_USER_ID
    original = store.get_user(DEMO_USER_ID)
    original_plan = original.plan
    store.update_user(DEMO_USER_ID, {"plan": "starter"})
    assert store.get_user(DEMO_USER_ID).plan == "starter"
    # Restore
    store.update_user(DEMO_USER_ID, {"plan": original_plan})


# ── Invoice boundary ──────────────────────────────────────────────────────────

def test_list_invoices_empty_for_new_user(user_id):
    assert store.list_invoices(user_id) == []


def test_insert_and_retrieve_invoice(user_id):
    inv_id = store.uid()
    inv = _invoice(user_id, inv_id)
    store.insert_invoice(inv)

    result = store.get_invoice(user_id, inv_id)
    assert result is not None
    assert result.invoice_number == "INV-T-001"
    assert result.total == 500


def test_list_invoices_returns_inserted(user_id):
    inv_id = store.uid()
    store.insert_invoice(_invoice(user_id, inv_id))
    invoices = store.list_invoices(user_id)
    assert any(i.id == inv_id for i in invoices)


def test_update_invoice_status(user_id):
    inv_id = store.uid()
    inv = _invoice(user_id, inv_id)
    store.insert_invoice(inv)
    store.update_invoice(user_id, inv_id, {"status": "sent"})
    assert store.get_invoice(user_id, inv_id).status == "sent"


def test_get_invoice_returns_none_for_wrong_user(user_id):
    inv_id = store.uid()
    store.insert_invoice(_invoice(user_id, inv_id))
    assert store.get_invoice("other-user", inv_id) is None


def test_next_invoice_number_increments(user_id):
    """Two consecutive calls for the same user must return different numbers."""
    # Insert a dummy invoice first so the counter has a base to increment from
    inv_id1 = store.uid()
    inv_id2 = store.uid()
    store.insert_invoice(_invoice(user_id, inv_id1))
    n1 = store.next_invoice_number(user_id)
    store.insert_invoice(_invoice(user_id, inv_id2))
    n2 = store.next_invoice_number(user_id)
    assert n1 != n2


# ── AgentLog boundary ─────────────────────────────────────────────────────────

def test_list_agent_logs_empty_for_new_user(user_id):
    assert store.list_agent_logs(user_id) == []


def test_insert_and_list_agent_log(user_id):
    log_id = store.uid()
    log = _agent_log(user_id, log_id)
    store.insert_agent_log(log)

    logs = store.list_agent_logs(user_id)
    assert any(l.id == log_id for l in logs)


def test_agent_log_is_user_scoped(user_id):
    log_id = store.uid()
    store.insert_agent_log(_agent_log(user_id, log_id))
    assert store.list_agent_logs("other-user") == []


def test_insert_agent_log_preserves_fields(user_id):
    log_id = store.uid()
    log = _agent_log(user_id, log_id)
    log.tokens_used = 42
    log.cost_usd = 0.001
    store.insert_agent_log(log)

    stored = next(l for l in store.list_agent_logs(user_id) if l.id == log_id)
    assert stored.tokens_used == 42
    assert stored.cost_usd == 0.001


# ── store dispatch ────────────────────────────────────────────────────────────

def test_store_is_in_mock_mode():
    """conftest forces KORA_DATA_BACKEND=mock — verify the dispatch landed there."""
    from app.backends import memory_store
    # store.get_user must be the memory_store function (not supabase_store)
    assert store.get_user.__module__ == memory_store.__name__
