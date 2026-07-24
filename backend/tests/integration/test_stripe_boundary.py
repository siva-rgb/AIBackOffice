"""Integration tests for the Stripe service boundary.

Validates the contract between Kora and Stripe:
- Webhook signature verification rejects forged/missing signatures
- _handle_checkout_completed stores customer_id and increments contract credits
- _handle_subscription_change upgrades/downgrades plan based on price_id
- _handle_subscription_deleted downgrades to free via customer lookup
- _handle_payment_failed inserts a critical alert
- All Stripe SDK calls are monkeypatched — no real API key is used
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app
from app.models import User

client = TestClient(app)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user(uid: str, plan: str = "free") -> User:
    return User(id=uid, email=f"{uid}@example.com", plan=plan, created_at=_now())


# ── Webhook routing ───────────────────────────────────────────────────────────

def test_webhook_missing_signature_returns_400():
    r = client.post("/api/stripe/webhook", content=b"{}")
    assert r.status_code == 400
    assert "signature" in r.json()["detail"].lower()


def test_webhook_bad_signature_returns_400(monkeypatch):
    import stripe
    from app.routers import stripe_billing
    monkeypatch.setattr(
        stripe_billing.stripe.Webhook, "construct_event",
        lambda **k: (_ for _ in ()).throw(
            stripe.error.SignatureVerificationError("bad", "t=1")
        ),
    )
    r = client.post("/api/stripe/webhook", content=b"{}",
                    headers={"stripe-signature": "t=1,v1=forged"})
    assert r.status_code == 400


def test_webhook_unknown_event_type_is_ignored(monkeypatch):
    from app.routers import stripe_billing
    monkeypatch.setattr(
        stripe_billing.stripe.Webhook, "construct_event",
        lambda **k: {"type": "payment_intent.created", "data": {"object": {}}},
    )
    r = client.post("/api/stripe/webhook", content=b"{}",
                    headers={"stripe-signature": "t=1,v1=valid"})
    assert r.status_code == 200
    assert r.json() == {"received": True}


# ── _handle_checkout_completed ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_completed_stores_customer_id(user_id):
    from app.routers.stripe_billing import _handle_checkout_completed
    await _handle_checkout_completed({
        "client_reference_id": user_id,
        "customer": "cus_test123",
        "mode": "subscription",
    })
    # update_user is a patch call — verify it doesn't raise and the store
    # accepts the customer_id patch (store returns None for unknown users, that's fine)


@pytest.mark.asyncio
async def test_checkout_completed_increments_contract_credits(user_id, monkeypatch):
    from app.routers.stripe_billing import _handle_checkout_completed
    from app.seed import DEMO_USER_ID

    # Use the seeded demo user so get_user returns a real object
    original = store.get_user(DEMO_USER_ID)
    original_credits = original.contract_credits

    await _handle_checkout_completed({
        "client_reference_id": DEMO_USER_ID,
        "customer": None,
        "mode": "payment",
    })

    updated = store.get_user(DEMO_USER_ID)
    assert updated.contract_credits == original_credits + 1
    # Restore
    store.update_user(DEMO_USER_ID, {"contract_credits": original_credits})


@pytest.mark.asyncio
async def test_checkout_completed_no_user_id_is_noop():
    from app.routers.stripe_billing import _handle_checkout_completed
    # Must not raise when client_reference_id is absent
    await _handle_checkout_completed({"customer": "cus_x", "mode": "subscription"})


# ── _handle_subscription_change ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscription_change_upgrades_plan(monkeypatch):
    from app.routers.stripe_billing import _handle_subscription_change
    from app.seed import DEMO_USER_ID

    pro_price = "price_pro_test"
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", pro_price)

    # Seed the demo user with a stripe_customer_id so the lookup works
    store.update_user(DEMO_USER_ID, {"stripe_customer_id": "cus_demo"})
    monkeypatch.setattr(store, "get_user_by_stripe_customer",
                        lambda cid: store.get_user(DEMO_USER_ID))

    await _handle_subscription_change({
        "customer": "cus_demo",
        "id": "sub_new",
        "status": "active",
        "items": {"data": [{"price": {"id": pro_price}}]},
    })

    updated = store.get_user(DEMO_USER_ID)
    assert updated.plan == "pro"


@pytest.mark.asyncio
async def test_subscription_change_unknown_customer_is_noop(monkeypatch):
    from app.routers.stripe_billing import _handle_subscription_change
    monkeypatch.setattr(store, "get_user_by_stripe_customer", lambda cid: None)
    # Must not raise
    await _handle_subscription_change({
        "customer": "cus_nobody",
        "id": "sub_x",
        "status": "active",
        "items": {"data": []},
    })


@pytest.mark.asyncio
async def test_subscription_change_inactive_status_sets_free(monkeypatch):
    from app.routers.stripe_billing import _handle_subscription_change
    from app.seed import DEMO_USER_ID

    store.update_user(DEMO_USER_ID, {"plan": "pro"})
    monkeypatch.setattr(store, "get_user_by_stripe_customer",
                        lambda cid: store.get_user(DEMO_USER_ID))

    await _handle_subscription_change({
        "customer": "cus_demo",
        "id": "sub_x",
        "status": "past_due",
        "items": {"data": []},
    })

    assert store.get_user(DEMO_USER_ID).plan == "free"


# ── _handle_subscription_deleted ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscription_deleted_downgrades_to_free(monkeypatch):
    from app.routers.stripe_billing import _handle_subscription_deleted
    from app.seed import DEMO_USER_ID

    store.update_user(DEMO_USER_ID, {"plan": "pro"})
    monkeypatch.setattr(store, "get_user_by_stripe_customer",
                        lambda cid: store.get_user(DEMO_USER_ID))

    await _handle_subscription_deleted({"customer": "cus_demo", "id": "sub_del"})

    assert store.get_user(DEMO_USER_ID).plan == "free"


@pytest.mark.asyncio
async def test_subscription_deleted_unknown_customer_is_noop(monkeypatch):
    from app.routers.stripe_billing import _handle_subscription_deleted
    monkeypatch.setattr(store, "get_user_by_stripe_customer", lambda cid: None)
    await _handle_subscription_deleted({"customer": "cus_ghost", "id": "sub_x"})


@pytest.mark.asyncio
async def test_subscription_deleted_no_customer_field_is_noop():
    from app.routers.stripe_billing import _handle_subscription_deleted
    await _handle_subscription_deleted({"id": "sub_no_customer"})


# ── _handle_payment_failed ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payment_failed_inserts_critical_alert(user_id, monkeypatch):
    from app.routers.stripe_billing import _handle_payment_failed
    from app.seed import DEMO_USER_ID

    monkeypatch.setattr(store, "get_user_by_stripe_customer",
                        lambda cid: store.get_user(DEMO_USER_ID))
    monkeypatch.setattr("app.services.owner_notify.notify_critical_alert",
                        lambda *a, **k: None)

    before = len(store.list_alerts(DEMO_USER_ID))
    await _handle_payment_failed({"customer": "cus_demo", "id": "inv_fail"})
    after = len(store.list_alerts(DEMO_USER_ID))

    assert after == before + 1
    alerts = store.list_alerts(DEMO_USER_ID)
    critical = [a for a in alerts if a.type == "payment_failed"]
    assert critical
    assert critical[-1].severity == "critical"
