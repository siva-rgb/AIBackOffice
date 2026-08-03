"""M7a — Stripe downgrade blocks premium routes.

`entitlements.enforce_plan` is wired to premium routes (M5). This pins the
end-to-end path: a Stripe subscription-deleted webhook downgrades the user's
plan in the store, and the next request to a gated route gets 403.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import store
from app.dependencies import get_current_user
from app.main import app
from app.seed import DEMO_USER_ID

client = TestClient(app)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def _restore_demo_plan():
    original = store.get_user(DEMO_USER_ID).plan
    yield
    store.update_user(DEMO_USER_ID, {"plan": original})


@pytest.mark.asyncio
async def test_stripe_downgrade_blocks_premium_route(monkeypatch, _restore_demo_plan):
    from app.routers.stripe_billing import _handle_subscription_deleted

    store.update_user(DEMO_USER_ID, {"plan": "pro"})
    monkeypatch.setattr(store, "get_user_by_stripe_customer", lambda cid: store.get_user(DEMO_USER_ID))

    await _handle_subscription_deleted({"customer": "cus_demo", "id": "sub_del"})
    assert store.get_user(DEMO_USER_ID).plan == "free"

    demo = store.get_user(DEMO_USER_ID)
    app.dependency_overrides[get_current_user] = lambda: demo

    r = client.post("/api/contracts/generate", json={})
    assert r.status_code == 403
    assert "upgrade" in r.json()["detail"].lower()


def test_pro_user_clears_gate_after_upgrade(_restore_demo_plan):
    store.update_user(DEMO_USER_ID, {"plan": "pro"})
    demo = store.get_user(DEMO_USER_ID)
    app.dependency_overrides[get_current_user] = lambda: demo

    r = client.post("/api/contracts/generate", json={})
    assert r.status_code != 403
