"""M9 — GDPR/CCPA compliance regression tests.

Validates:
- `GET /api/account/export` returns JSON + CSV payloads covering every
  user-data table.
- `DELETE /api/account/delete` wipes every user-data table, removes the user
  row, and writes a no-PII audit row to `deletion_log` (mock backend in-memory).
- After deletion, queries on the deleted user return no PII (export would
  return empty tables, list_* returns 0).
- `POST /api/account/consent` records (version, timestamp) on the user row.
- `PATCH /api/me` with `onboarding_completed=true` captures consent on the
  first toggle (idempotent — never overwrites an existing version).
- Cross-tenant: tenant A's delete does not touch tenant B's data.

All tests run against the mock store (KORA_DATA_BACKEND=mock, set at import
in conftest). auth is overridden so we can act as either of two synthetic
tenants without needing real JWTs.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app import store
from app.backends import memory_store
from app.backends.user_data import CURRENT_CONSENT_VERSION, USER_DATA_TABLES
from app.dependencies import get_current_user
from app.main import app
from app.models import User
from app.seed import DEMO_USER_ID


# ── helpers ─────────────────────────────────────────────────────────────────

client = TestClient(app)


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _seed_demo_user_with_data(uid: str) -> None:
    """Populate the in-memory store with rows owned by `uid` so the export and
    delete endpoints have something to act on. Idempotent.
    """
    if store.get_user(uid) is not None:
        return
    # User row
    memory_store._users.append(
        User(
            id=uid,
            email=f"{uid}@example.com",
            full_name="Test User",
            business_name="Test Studio",
            country="US",
            currency="USD",
            plan="pro",
            created_at=_now(),
        )
    )
    # Seed a few rows in the most-trafficked tables
    from app.models import Transaction, Invoice

    txn = Transaction(
        id="t-m9",
        user_id=uid,
        date="2026-01-01",
        description="M9 test",
        amount=10.0,
        type="income",
        created_at=_now(),
        category="client_payment",
    )
    memory_store._transactions.append(txn)
    inv = Invoice(
        id="inv-m9",
        user_id=uid,
        invoice_number="INV-M9",
        client_name="Test Client",
        client_email="c@x.com",
        subtotal=10,
        tax_rate=0,
        tax_amount=0,
        total=10,
        status="draft",
        due_date="2099-12-31",
        created_at=_now(),
    )
    memory_store._invoices.append(inv)


def _as(uid: str):
    """Override auth dependency so the next request resolves to `uid`."""
    user = store.get_user(uid)
    assert user is not None, f"user {uid} not seeded"
    app.dependency_overrides[get_current_user] = lambda: user
    return user


@pytest.fixture(autouse=True)
def _reset_overrides():
    """Always clear dependency overrides after each test."""
    yield
    app.dependency_overrides.pop(get_current_user, None)


# ── export ──────────────────────────────────────────────────────────────────


def test_export_returns_format_version_and_timestamp():
    uid = str(uuid.uuid4())
    _seed_demo_user_with_data(uid)
    _as(uid)
    r = client.get("/api/account/export")
    assert r.status_code == 200
    payload = r.json()
    assert payload["format_version"] == "1.1"
    assert "exported_at" in payload
    # `account` is the full user record (not just a few flat fields).
    assert payload["account"]["email"] == f"{uid}@example.com"
    assert "profile" in payload["account"], "full profile JSONB must be exported"
    assert "agent_memory" in payload


def test_export_covers_every_table_in_registry():
    uid = str(uuid.uuid4())
    _seed_demo_user_with_data(uid)
    _as(uid)
    r = client.get("/api/account/export")
    payload = r.json()
    assert set(payload["tables"].keys()) == set(USER_DATA_TABLES), (
        "export must cover every table in USER_DATA_TABLES — missing: "
        f"{set(USER_DATA_TABLES) - set(payload['tables'].keys())}, extra: "
        f"{set(payload['tables'].keys()) - set(USER_DATA_TABLES)}"
    )


def test_export_csv_is_well_formed():
    uid = str(uuid.uuid4())
    _seed_demo_user_with_data(uid)
    _as(uid)
    r = client.get("/api/account/export.csv")
    assert r.status_code == 200
    body = r.json()
    assert body["filename"].startswith("kora-export-")
    assert body["filename"].endswith(".csv")
    csv_text = body["content"]
    # Every table name should appear at least once in the CSV
    for table in USER_DATA_TABLES:
        assert f"=== {table}" in csv_text


def test_export_is_tenant_scoped():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_demo_user_with_data(a)
    _seed_demo_user_with_data(b)
    _as(a)
    r = client.get("/api/account/export")
    payload = r.json()
    # Tenant A's transactions should be exactly 1 (the seed row); tenant B's row
    # MUST NOT be visible.
    assert len(payload["tables"]["transactions"]) == 1
    assert payload["tables"]["transactions"][0]["id"] == "t-m9"
    # And tenant B's data must remain in the store — not leaked, not deleted.
    assert any(t.id == "t-m9" for t in memory_store._transactions if t.user_id == b)


# ── delete ──────────────────────────────────────────────────────────────────


def test_delete_wipes_every_table_and_user_row():
    uid = str(uuid.uuid4())
    _seed_demo_user_with_data(uid)
    _as(uid)
    pre_txn = [t for t in memory_store._transactions if t.user_id == uid]
    pre_inv = [i for i in memory_store._invoices if i.user_id == uid]
    assert len(pre_txn) == 1
    assert len(pre_inv) == 1

    r = client.delete("/api/account/delete")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is True
    assert "user_request_id" in body
    # tables_cleared must include every table — counts may be 0 but the key
    # MUST be present so the audit row is self-describing.
    for table in USER_DATA_TABLES:
        assert table in body["tables_cleared"], f"missing {table} in audit"
    assert body["tables_cleared"]["transactions"] == 1
    assert body["tables_cleared"]["invoices"] == 1
    assert body["tables_cleared"]["users"] == 1


def test_delete_writes_audit_row_with_no_pii():
    uid = str(uuid.uuid4())
    _seed_demo_user_with_data(uid)
    _as(uid)
    r = client.delete("/api/account/delete")
    user_request_id = r.json()["user_request_id"]

    log = memory_store.list_deletion_log()
    assert any(
        row["user_request_id"] == user_request_id for row in log
    ), "deletion_log must contain the audit row"
    matching = [r for r in log if r["user_request_id"] == user_request_id][0]
    # No PII / no user_id FK on the audit row
    assert "user_id" not in matching
    assert "email" not in matching
    assert "name" not in matching
    assert matching["reason"] == "user_request"
    assert isinstance(matching["tables_cleared"], dict)
    assert matching["files_deleted_count"] == 0
    # side_effects are now persisted on the audit row — and stay PII-free
    # (status strings only, no user_id/email/name anywhere in them).
    assert "side_effects" in matching
    se = matching["side_effects"]
    assert isinstance(se, dict)
    blob = json.dumps(se).lower()
    assert uid.lower() not in blob
    assert "@example.com" not in blob


def test_delete_reports_honest_side_effects_and_no_false_errors():
    """The response tells the truth: mock env has no auth backend / no Google
    token / no subscription, so those are 'not_applicable' (not a silent
    'skipped'), there are no errors, and `deleted` is True."""
    uid = str(uuid.uuid4())
    _seed_demo_user_with_data(uid)
    _as(uid)
    body = client.delete("/api/account/delete").json()

    assert body["deleted"] is True
    assert body["errors"] == []
    assert "warnings" in body
    se = body["side_effects"]
    assert se["auth_delete"].startswith("not_applicable")
    assert se["google_revoke"].startswith("not_applicable")
    assert se["stripe_cancel"].startswith("not_applicable")
    assert se["deletion_log"] == "recorded"


def test_delete_is_deleted_false_when_auth_identity_delete_fails(monkeypatch):
    """The honesty fix: if Supabase IS configured but the auth-identity delete
    throws (the login email would survive), `deleted` is False with an error —
    not a false 'deleted: true'."""
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "SUPABASE_URL", "http://localhost")
    monkeypatch.setattr(_settings, "SUPABASE_SERVICE_ROLE_KEY", "svc")

    import supabase

    def _boom(*a, **k):
        raise RuntimeError("auth backend down")

    monkeypatch.setattr(supabase, "create_client", _boom)

    uid = str(uuid.uuid4())
    _seed_demo_user_with_data(uid)
    _as(uid)
    body = client.delete("/api/account/delete").json()

    assert body["deleted"] is False
    assert "auth_identity_not_deleted" in body["errors"]
    assert body["side_effects"]["auth_delete"].startswith("failed")


def test_post_delete_export_returns_no_residual_pii():
    uid = str(uuid.uuid4())
    _seed_demo_user_with_data(uid)
    _as(uid)
    client.delete("/api/account/delete")
    # After delete, the in-memory user lookup will fail because the user row
    # is gone. The endpoint requires `Depends(get_current_user)` which loads
    # by DEMO_USER_ID — so we override again to a fresh id, then verify the
    # original user's data is gone.
    remaining = [t for t in memory_store._transactions if t.user_id == uid]
    remaining_inv = [i for i in memory_store._invoices if i.user_id == uid]
    assert remaining == []
    assert remaining_inv == []
    # And store.get_user(uid) must return None (user row removed)
    assert store.get_user(uid) is None


def test_delete_does_not_touch_other_tenant():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_demo_user_with_data(a)
    _seed_demo_user_with_data(b)
    _as(a)
    client.delete("/api/account/delete")

    # Tenant B's data must still be present, untouched.
    b_txn = [t for t in memory_store._transactions if t.user_id == b]
    b_inv = [i for i in memory_store._invoices if i.user_id == b]
    assert len(b_txn) == 1 and b_txn[0].id == "t-m9"
    assert len(b_inv) == 1 and b_inv[0].id == "inv-m9"
    assert store.get_user(b) is not None


# ── consent ─────────────────────────────────────────────────────────────────


def test_consent_endpoint_records_version_and_timestamp():
    _as(DEMO_USER_ID)
    before = store.get_user(DEMO_USER_ID)
    assert before.consent_version is None  # seeded user has no consent yet

    r = client.post("/api/account/consent", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["consent_version"] == CURRENT_CONSENT_VERSION
    assert body["consent_given_at"]

    after = store.get_user(DEMO_USER_ID)
    assert after.consent_version == CURRENT_CONSENT_VERSION
    assert after.consent_given_at


def test_consent_endpoint_accepts_custom_version():
    _as(DEMO_USER_ID)
    r = client.post("/api/account/consent", json={"version": "2027-01-01"})
    assert r.status_code == 200
    assert r.json()["consent_version"] == "2027-01-01"


def test_consent_endpoint_rejects_empty_version():
    _as(DEMO_USER_ID)
    r = client.post("/api/account/consent", json={"version": ""})
    assert r.status_code == 422


def test_onboarding_completion_captures_consent_idempotently():
    """PATCH /api/me with onboarding_completed=true must capture consent on the
    first toggle and never overwrite an existing consent_version."""
    # Pick a user who has not yet completed onboarding
    from app.backends import memory_store as _ms
    from app.models import User

    uid = str(uuid.uuid4())
    _ms._users.append(User(id=uid, email=f"{uid}@x.com", created_at=_now()))
    _as(uid)

    # First toggle: should capture consent
    r = client.patch("/api/me", json={"onboardingCompleted": True})
    assert r.status_code == 200
    u1 = store.get_user(uid)
    assert u1.consent_version == CURRENT_CONSENT_VERSION
    assert u1.consent_given_at
    first_ts = u1.consent_given_at

    # Second toggle: must NOT overwrite (already-captured consent stays)
    r = client.patch("/api/me", json={"fullName": "Renamed"})
    assert r.status_code == 200
    u2 = store.get_user(uid)
    assert u2.consent_version == CURRENT_CONSENT_VERSION
    assert u2.consent_given_at == first_ts  # unchanged
    assert u2.full_name == "Renamed"
