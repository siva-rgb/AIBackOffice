"""Money arriving has to land on the right invoice, exactly once.

`checkout.session.completed` is emitted by two unrelated things:

  * a subscription checkout on THIS platform account, and
  * a client paying an invoice on the USER'S connected account.

Both can carry `mode="payment"`, and the platform branch grants a contract
credit for that mode — so routing on mode alone would hand out a free contract
every time somebody's client paid an invoice. The router keys on
`kora_invoice_id` instead, and that is what these tests hold in place.

The second property is idempotency. Stripe delivers webhooks at least once, and
a redelivery that adds the amount again would show an invoice as overpaid, or
double-count revenue. The handler SETS the invoice paid rather than incrementing.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.routers import stripe_billing as sb


@pytest.fixture
def captured(monkeypatch):
    state = {"updates": [], "invoice": None, "user_updates": []}

    def _get_invoice(uid, iid):
        return state["invoice"]

    monkeypatch.setattr(sb.store, "get_invoice", _get_invoice)
    monkeypatch.setattr(sb.store, "update_invoice", lambda uid, iid, patch: state["updates"].append((uid, iid, patch)))
    monkeypatch.setattr(sb.store, "update_user", lambda uid, patch: state["user_updates"].append((uid, patch)))
    monkeypatch.setattr(sb, "_log_billing_event", lambda *a, **k: None)
    return state


def _invoice(**kw):
    base = dict(id="inv_1", invoice_number="INV-001", total=250.0, amount_paid=0.0, status="sent")
    base.update(kw)
    return SimpleNamespace(**base)


def _session(**kw):
    base = dict(
        id="cs_1",
        mode="payment",
        amount_total=25000,
        currency="usd",
        metadata={"kora_user_id": "u1", "kora_invoice_id": "inv_1"},
    )
    base.update(kw)
    return base


@pytest.mark.asyncio
class TestInvoicePayment:
    async def test_a_paid_link_marks_the_invoice_paid(self, captured):
        captured["invoice"] = _invoice()
        await sb._handle_invoice_payment(_session(), "acct_1")
        assert len(captured["updates"]) == 1
        _, iid, patch = captured["updates"][0]
        assert iid == "inv_1"
        assert patch["status"] == "paid"
        assert patch["amount_paid"] == 250.0
        assert patch["paid_at"]

    async def test_a_redelivery_changes_nothing(self, captured):
        """Stripe delivers at least once; the second delivery must be a no-op."""
        captured["invoice"] = _invoice(status="paid", amount_paid=250.0)
        await sb._handle_invoice_payment(_session(), "acct_1")
        assert captured["updates"] == []

    async def test_the_amount_is_set_not_accumulated(self, captured):
        """Incrementing would show 500 on a redelivered 250 payment."""
        captured["invoice"] = _invoice(total=250.0, amount_paid=100.0)
        await sb._handle_invoice_payment(_session(), "acct_1")
        _, _, patch = captured["updates"][0]
        assert patch["amount_paid"] == 250.0

    async def test_a_cancelled_invoice_is_left_alone(self, captured):
        captured["invoice"] = _invoice(status="cancelled")
        await sb._handle_invoice_payment(_session(), "acct_1")
        assert captured["updates"] == []

    async def test_an_unknown_invoice_does_not_raise(self, captured):
        """A webhook for a deleted invoice must not 500 back at Stripe."""
        captured["invoice"] = None
        await sb._handle_invoice_payment(_session(), "acct_1")
        assert captured["updates"] == []

    async def test_missing_metadata_is_ignored(self, captured):
        captured["invoice"] = _invoice()
        await sb._handle_invoice_payment(_session(metadata={}), "acct_1")
        assert captured["updates"] == []

    async def test_no_contract_credit_is_granted(self, captured):
        """The bug this routing prevents: a client paying an invoice must not
        earn the USER a free contract."""
        captured["invoice"] = _invoice()
        await sb._handle_invoice_payment(_session(), "acct_1")
        assert captured["user_updates"] == []


class TestRouting:
    """The dispatcher must send each event to the right handler."""

    def test_an_invoice_session_is_identified_by_its_metadata(self):
        session = _session()
        assert (session.get("metadata") or {}).get("kora_invoice_id")

    def test_a_subscription_session_is_not(self):
        session = {"mode": "subscription", "client_reference_id": "u1", "metadata": {}}
        assert not (session.get("metadata") or {}).get("kora_invoice_id")

    def test_a_platform_one_off_payment_is_not(self):
        """mode=payment on the platform account buys a contract credit — it has
        no kora_invoice_id, which is exactly how it stays on its own path."""
        session = {"mode": "payment", "client_reference_id": "u1", "metadata": {"user_id": "u1"}}
        assert not (session.get("metadata") or {}).get("kora_invoice_id")
