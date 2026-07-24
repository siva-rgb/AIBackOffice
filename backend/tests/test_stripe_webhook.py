"""Regression cover for Stripe webhook signature verification (M6).

The webhook moves subscription state and money, and Stripe calls it with no auth
of ours — the ONLY thing standing between a forged request and a plan upgrade is
signature verification. These pin that: no signature → 400, a bad signature →
400 and no dispatch, a verified event → dispatched. We monkeypatch Stripe's
crypto so we test OUR logic (the 400 mapping + dispatch), not Stripe's library.
"""
from __future__ import annotations

import stripe
from fastapi.testclient import TestClient

from app.main import app
from app.routers import stripe_billing

client = TestClient(app)
URL = "/api/stripe/webhook"


def test_missing_signature_header_is_rejected():
    r = client.post(URL, content=b"{}")
    assert r.status_code == 400
    assert "signature" in r.json()["detail"].lower()


def test_a_bad_signature_is_rejected_and_never_dispatched(monkeypatch):
    dispatched = []

    def raise_sig(*a, **k):
        raise stripe.error.SignatureVerificationError("bad sig", "t=1,v1=deadbeef")
    monkeypatch.setattr(stripe_billing.stripe.Webhook, "construct_event", raise_sig)
    monkeypatch.setattr(stripe_billing, "_handle_checkout_completed",
                        lambda d: dispatched.append(d))

    r = client.post(URL, content=b"{}", headers={"stripe-signature": "t=1,v1=forged"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid signature"
    assert dispatched == [], "a forged event was dispatched despite a bad signature"


def test_a_verified_event_is_dispatched(monkeypatch):
    seen = {}

    async def fake_handler(session):
        seen["session"] = session
    monkeypatch.setattr(stripe_billing.stripe.Webhook, "construct_event",
                        lambda **k: {"type": "checkout.session.completed",
                                     "data": {"object": {"client_reference_id": "u-1"}}})
    monkeypatch.setattr(stripe_billing, "_handle_checkout_completed", fake_handler)

    r = client.post(URL, content=b"{}", headers={"stripe-signature": "t=1,v1=valid"})
    assert r.status_code == 200
    assert r.json() == {"received": True}
    assert seen["session"]["client_reference_id"] == "u-1"


def test_a_handler_error_does_not_500_the_webhook(monkeypatch):
    """A failing handler must still 200 Stripe (so it doesn't infinitely retry),
    not surface a 500."""
    async def boom(_):
        raise RuntimeError("handler blew up")
    monkeypatch.setattr(stripe_billing.stripe.Webhook, "construct_event",
                        lambda **k: {"type": "checkout.session.completed",
                                     "data": {"object": {}}})
    monkeypatch.setattr(stripe_billing, "_handle_checkout_completed", boom)

    r = client.post(URL, content=b"{}", headers={"stripe-signature": "t=1,v1=valid"})
    assert r.status_code == 200 and r.json() == {"received": True}
