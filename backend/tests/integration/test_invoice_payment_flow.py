"""End-to-end checks for invoice payments, through the HTTP layer.

The unit tests pin each piece; these prove the pieces are actually wired to each
other. Three things are worth checking at this level because they are exactly
what a user or their client would hit first:

  * sending an invoice with no Stripe connected must produce NO payment link —
    the whole point of the change, and the old code's fabricated URL was
    invisible until a client clicked it;
  * asking for a link without a connected account must fail as configuration
    (409 with an actionable message), not as a 500;
  * a completed payment must move the invoice and must NOT be mistaken for the
    platform's own one-off checkout, which grants a contract credit.

Runs against the mock backend, so no Stripe key and no network are involved.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("KORA_DATA_BACKEND", "mock")

from app import store  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Invoice  # noqa: E402
from app.routers import stripe_billing  # noqa: E402
from app.seed import DEMO_USER_ID  # noqa: E402
from app.services import invoice_payments  # noqa: E402

client = TestClient(app)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def invoice():
    inv = Invoice(
        id=store.uid("inv"),
        user_id=DEMO_USER_ID,
        invoice_number="INV-FLOW-1",
        client_name="Flow Test Ltd",
        client_email="client@example.com",
        total=500.0,
        currency="USD",
        status="draft",
        due_date="2026-09-01",
        payment_link=None,
        created_at=_now(),
    )
    store.insert_invoice(inv)
    return inv


@pytest.fixture(autouse=True)
def no_stripe(monkeypatch):
    """Default state for a fresh user: no connected account."""
    monkeypatch.setattr(invoice_payments.store, "get_stripe_connection", lambda uid: None)


class TestSendingWithoutStripe:
    def test_no_payment_link_is_invented(self, invoice, monkeypatch):
        """The regression. `send_invoice` used to write
        https://pay.stripe.com/demo/{number}, which redirects to Stripe's own
        marketing page — a client clicking Pay Now got an advert."""
        monkeypatch.setattr("app.services.email_service.send_invoice_email", lambda **kw: "msg_1")
        r = client.post(f"/api/invoices/{invoice.id}/send")
        assert r.status_code == 200, r.text
        assert not r.json().get("paymentLink")

    def test_the_invoice_still_sends(self, invoice, monkeypatch):
        """A missing button must not block the invoice — it still has its PDF
        and its due date, and bank transfer still works."""
        sent = {}
        monkeypatch.setattr(
            "app.services.email_service.send_invoice_email",
            lambda **kw: sent.update(kw) or "msg_1",
        )
        r = client.post(f"/api/invoices/{invoice.id}/send")
        assert r.status_code == 200
        assert r.json()["status"] == "sent"
        assert sent["payment_link"] is None

    def test_a_stored_placeholder_is_not_reused(self, monkeypatch):
        """An invoice sent before this change carries a dead link. Re-sending
        must not keep it."""
        inv = Invoice(
            id=store.uid("inv"),
            user_id=DEMO_USER_ID,
            invoice_number="INV-OLD",
            client_name="Old Client",
            client_email="old@example.com",
            total=100.0,
            status="draft",
            due_date="2026-09-01",
            payment_link="https://pay.stripe.com/demo/INV-OLD",
            created_at=_now(),
        )
        store.insert_invoice(inv)
        monkeypatch.setattr("app.services.email_service.send_invoice_email", lambda **kw: "m")
        client.post(f"/api/invoices/{inv.id}/send")
        assert not invoice_payments.is_placeholder_link(store.get_invoice(DEMO_USER_ID, inv.id).payment_link or "")


class TestPaymentLinkEndpoint:
    def test_no_stripe_account_is_409_not_500(self, invoice):
        """Nothing is broken — the account just is not connected. A 500 would
        send the user to the logs instead of to Settings."""
        r = client.post(f"/api/invoices/{invoice.id}/payment-link")
        assert r.status_code == 409
        assert "Connect your Stripe account" in r.json()["detail"]

    def test_a_missing_invoice_is_404(self):
        r = client.post("/api/invoices/does-not-exist/payment-link")
        assert r.status_code == 404

    def test_a_link_is_created_and_stored(self, invoice, monkeypatch):
        monkeypatch.setattr(
            invoice_payments,
            "create_payment_link",
            lambda uid, inv: "https://buy.stripe.com/test_LIVE",
        )
        r = client.post(f"/api/invoices/{invoice.id}/payment-link")
        assert r.status_code == 200, r.text
        assert r.json()["paymentLink"] == "https://buy.stripe.com/test_LIVE"
        assert store.get_invoice(DEMO_USER_ID, invoice.id).payment_link == "https://buy.stripe.com/test_LIVE"

    def test_a_paid_invoice_is_refused(self, invoice, monkeypatch):
        store.update_invoice(DEMO_USER_ID, invoice.id, {"status": "paid"})
        r = client.post(f"/api/invoices/{invoice.id}/payment-link")
        assert r.status_code == 409


class TestWebhookMovesTheInvoice:
    @pytest.mark.asyncio
    async def test_a_link_payment_marks_it_paid(self, invoice, monkeypatch):
        monkeypatch.setattr(stripe_billing, "_log_billing_event", lambda *a, **k: None)
        await stripe_billing._handle_invoice_payment(
            {
                "id": "cs_1",
                "mode": "payment",
                "amount_total": 50000,
                "currency": "usd",
                "metadata": {"kora_user_id": DEMO_USER_ID, "kora_invoice_id": invoice.id},
            },
            "acct_1",
        )
        updated = store.get_invoice(DEMO_USER_ID, invoice.id)
        assert updated.status == "paid"
        assert float(updated.amount_paid) == 500.0

    @pytest.mark.asyncio
    async def test_it_does_not_grant_a_contract_credit(self, invoice, monkeypatch):
        """Both a subscription checkout and an invoice payment emit
        checkout.session.completed with mode="payment". Routing on mode alone
        would hand the user a free contract every time a client paid."""
        monkeypatch.setattr(stripe_billing, "_log_billing_event", lambda *a, **k: None)
        before = store.get_user(DEMO_USER_ID)
        before_credits = getattr(before, "contract_credits", 0) or 0
        await stripe_billing._handle_invoice_payment(
            {
                "id": "cs_2",
                "mode": "payment",
                "amount_total": 50000,
                "currency": "usd",
                "metadata": {"kora_user_id": DEMO_USER_ID, "kora_invoice_id": invoice.id},
            },
            "acct_1",
        )
        after = store.get_user(DEMO_USER_ID)
        assert (getattr(after, "contract_credits", 0) or 0) == before_credits

    @pytest.mark.asyncio
    async def test_the_user_is_told(self, invoice, monkeypatch):
        """The invoice going quiet is not the same as the user being informed."""
        monkeypatch.setattr(stripe_billing, "_log_billing_event", lambda *a, **k: None)
        before = len(store.list_alerts(DEMO_USER_ID))
        await stripe_billing._handle_invoice_payment(
            {
                "id": "cs_3",
                "mode": "payment",
                "amount_total": 50000,
                "currency": "usd",
                "metadata": {"kora_user_id": DEMO_USER_ID, "kora_invoice_id": invoice.id},
            },
            "acct_1",
        )
        alerts = store.list_alerts(DEMO_USER_ID)
        assert len(alerts) == before + 1
        assert alerts[0].type == "payment_reconciled"


class TestScheduledSyncRoute:
    def test_a_wrong_secret_never_reaches_the_cross_tenant_fan_out(self, monkeypatch):
        """The security property that matters: a bad secret must not be able to
        trigger work across every tenant. It falls through to the ordinary
        signed-in path instead, which only ever touches the caller's own data.

        (Asserting a 401 here would only hold on the Supabase backend — in mock
        mode every request resolves to the seeded demo user by design.)"""
        from app.config import settings

        monkeypatch.setattr(settings, "CRON_SECRET", "the-real-secret")
        called = []
        monkeypatch.setattr(store, "list_connected_stripe_user_ids", lambda: called.append(1) or [])

        r = client.post("/api/stripe-connect/run", headers={"x-cron-secret": "wrong"})
        assert called == [], "a wrong secret reached the cross-tenant fan-out"
        assert r.json().get("trigger") != "scheduler"

    def test_the_cron_path_fans_out_over_every_connected_tenant(self, monkeypatch):
        """Bookkeeping is per-tenant: syncing only the scheduler's own account
        would leave every other connected user as stale as before."""
        from app.config import settings

        monkeypatch.setattr(settings, "CRON_SECRET", "test-secret")
        monkeypatch.setattr(store, "list_connected_stripe_user_ids", lambda: ["u1", "u2", "u3"])

        seen = []

        async def _fake_sync(uid):
            seen.append(uid)
            return {"synced_count": 2}

        monkeypatch.setattr("app.services.stripe_sync.sync_stripe_transactions", _fake_sync)
        r = client.post("/api/stripe-connect/run", headers={"x-cron-secret": "test-secret"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["trigger"] == "scheduler"
        assert body["tenants"] == 3
        assert body["transactions_synced"] == 6
        assert seen == ["u1", "u2", "u3"]

    def test_one_tenant_failing_does_not_stop_the_rest(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "CRON_SECRET", "test-secret")
        monkeypatch.setattr(store, "list_connected_stripe_user_ids", lambda: ["ok1", "bad", "ok2"])

        async def _fake_sync(uid):
            if uid == "bad":
                raise RuntimeError("stripe refused")
            return {"synced_count": 1}

        monkeypatch.setattr("app.services.stripe_sync.sync_stripe_transactions", _fake_sync)
        r = client.post("/api/stripe-connect/run", headers={"x-cron-secret": "test-secret"})
        assert r.status_code == 200
        assert r.json()["transactions_synced"] == 2
        assert r.json()["tenants_failed"] == 1
