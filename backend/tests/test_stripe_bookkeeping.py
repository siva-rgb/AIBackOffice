"""Money that arrives has to land in the books, once, on the right invoice.

Three separate faults sat between "a client paid" and "the books are correct":

  1. `sync_stripe_transactions` had exactly one caller — the Sync button in
     Settings. Income stayed outside the books until somebody clicked, so the
     P&L, the forecast and the revenue-goal tracking all read stale numbers.

  2. The payment-link webhook marks an invoice paid immediately, which removed
     it from `reconcile_payments`'s pool of open invoices. The matching income
     then arrived looking unclaimed and could be matched against a DIFFERENT
     open invoice with the same client and amount — two equal retainers, or one
     client settling two identical invoices, is exactly that shape.

  3. Transactions deduped on (date, description, amount), so two genuine
     payments from the same client on the same day for the same amount became
     one row. Revenue understated, no error anywhere.

Each is pinned below.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.backends import memory_store
from app.models import Transaction
from app.services import stripe_sync


def _txn(**kw):
    base = dict(
        id="tx1",
        user_id="u1",
        date="2026-08-14",
        description="Acme — Stripe payment",
        amount=500.0,
        currency="USD",
        type="income",
        category="client_payment",
        source="stripe_connect",
        external_id=None,
        created_at="2026-08-14T00:00:00Z",
    )
    base.update(kw)
    return Transaction(**base)


class TestDedupeBySourceId:
    def setup_method(self):
        memory_store._transactions.clear()

    def test_two_identical_payments_are_two_rows(self):
        """The regression: same client, same day, same amount — genuinely two
        payments. Shape-based dedupe kept only one and lost the revenue."""
        a = _txn(id="tx1", external_id="txn_AAA")
        b = _txn(id="tx2", external_id="txn_BBB")
        inserted = memory_store.insert_transactions([a, b])
        assert len(inserted) == 2

    def test_the_same_payment_synced_twice_is_one_row(self):
        """Re-syncing must still not duplicate."""
        memory_store.insert_transactions([_txn(id="tx1", external_id="txn_AAA")])
        again = memory_store.insert_transactions([_txn(id="tx2", external_id="txn_AAA")])
        assert again == []

    def test_rows_without_a_source_id_keep_shape_dedupe(self):
        """CSV imports have no external id and must stay protected — otherwise
        re-uploading a statement doubles the books."""
        memory_store.insert_transactions([_txn(id="tx1", source="csv")])
        again = memory_store.insert_transactions([_txn(id="tx2", source="csv")])
        assert again == []

    def test_a_stripe_row_does_not_suppress_a_csv_row(self):
        """Different dedupe domains: the same payment seen through both a bank
        CSV and Stripe is a reconciliation question, not a reason to drop one
        silently at insert time."""
        memory_store.insert_transactions([_txn(id="tx1", external_id="txn_AAA")])
        csv_row = memory_store.insert_transactions([_txn(id="tx2", source="csv")])
        assert len(csv_row) == 1


class TestCurrencyConversion:
    def test_yen_is_not_divided_by_a_hundred(self):
        """Stripe reports 5000 for ¥5,000. /100 books it as ¥50."""
        from app.services.invoice_payments import from_minor_units

        assert from_minor_units(5000, "JPY") == 5000.0

    def test_dollars_still_divide(self):
        from app.services.invoice_payments import from_minor_units

        assert from_minor_units(4250, "USD") == 42.50

    def test_the_round_trip_is_stable(self):
        from app.services.invoice_payments import from_minor_units, to_minor_units

        for amount, code in [(42.50, "USD"), (5000.0, "JPY"), (10.0, "BHD")]:
            assert from_minor_units(to_minor_units(amount, code), code) == amount


class TestSettleLinkedInvoices:
    """Fix 2 — the claim that stops a payment settling the wrong invoice."""

    def _rows(self, invoice_id="inv_A"):
        return [
            {
                "date": "2026-08-14",
                "description": "Acme — Stripe payment",
                "amount": 500.0,
                "invoice_id": invoice_id,
                "stripe_id": "txn_AAA",
            }
        ]

    def test_the_transaction_is_claimed_so_it_cannot_settle_another_invoice(self, monkeypatch):
        """`reconcile_payments` builds its consumed set from exactly this key.
        Without it, invoice B (same client, same amount) gets marked paid off
        the back of a payment for invoice A."""
        logs = []
        monkeypatch.setattr(
            stripe_sync.store,
            "get_invoice",
            lambda uid, iid: SimpleNamespace(id=iid, invoice_number="INV-1", status="paid", total=500.0),
        )
        monkeypatch.setattr(stripe_sync.store, "update_invoice", lambda *a, **k: None)
        monkeypatch.setattr(stripe_sync, "log_action", lambda **kw: logs.append(kw))

        stripe_sync._settle_linked_invoices("u1", [_txn(id="tx1")], self._rows())

        assert len(logs) == 1
        assert logs[0]["output"]["reconciledTransactionId"] == "tx1"
        assert logs[0]["agent_type"] == "cross_module"

    def test_an_open_invoice_is_marked_paid(self, monkeypatch):
        """Safety net when the Stripe webhook is not wired for Connect events:
        the payment still lands, just at sync time."""
        updates = []
        monkeypatch.setattr(
            stripe_sync.store,
            "get_invoice",
            lambda uid, iid: SimpleNamespace(id=iid, invoice_number="INV-1", status="sent", total=500.0),
        )
        monkeypatch.setattr(stripe_sync.store, "update_invoice", lambda uid, iid, patch: updates.append(patch))
        monkeypatch.setattr(stripe_sync, "log_action", lambda **kw: None)

        stripe_sync._settle_linked_invoices("u1", [_txn(id="tx1")], self._rows())

        assert updates[0]["status"] == "paid"
        assert updates[0]["amount_paid"] == 500.0

    def test_an_already_paid_invoice_is_not_rewritten(self, monkeypatch):
        updates = []
        monkeypatch.setattr(
            stripe_sync.store,
            "get_invoice",
            lambda uid, iid: SimpleNamespace(id=iid, invoice_number="INV-1", status="paid", total=500.0),
        )
        monkeypatch.setattr(stripe_sync.store, "update_invoice", lambda uid, iid, patch: updates.append(patch))
        monkeypatch.setattr(stripe_sync, "log_action", lambda **kw: None)

        stripe_sync._settle_linked_invoices("u1", [_txn(id="tx1")], self._rows())
        assert updates == []

    def test_a_transaction_with_no_invoice_is_left_alone(self, monkeypatch):
        """Ordinary Stripe income must not be claimed — reconcile_payments still
        needs to be able to match it against invoices the normal way."""
        logs = []
        monkeypatch.setattr(stripe_sync, "log_action", lambda **kw: logs.append(kw))
        rows = self._rows()
        rows[0]["invoice_id"] = ""
        assert stripe_sync._settle_linked_invoices("u1", [_txn(id="tx1")], rows) == 0
        assert logs == []

    def test_a_missing_invoice_does_not_break_the_sync(self, monkeypatch):
        monkeypatch.setattr(stripe_sync.store, "get_invoice", lambda uid, iid: None)
        monkeypatch.setattr(stripe_sync, "log_action", lambda **kw: None)
        assert stripe_sync._settle_linked_invoices("u1", [_txn(id="tx1")], self._rows()) == 0

    def test_one_bad_row_does_not_stop_the_others(self, monkeypatch):
        def _get(uid, iid):
            if iid == "inv_BAD":
                raise RuntimeError("row is corrupt")
            return SimpleNamespace(id=iid, invoice_number="INV-2", status="paid", total=500.0)

        monkeypatch.setattr(stripe_sync.store, "get_invoice", _get)
        monkeypatch.setattr(stripe_sync.store, "update_invoice", lambda *a, **k: None)
        monkeypatch.setattr(stripe_sync, "log_action", lambda **kw: None)

        rows = [
            {"date": "2026-08-14", "description": "A", "amount": 500.0, "invoice_id": "inv_BAD", "stripe_id": "t1"},
            {"date": "2026-08-15", "description": "B", "amount": 500.0, "invoice_id": "inv_OK", "stripe_id": "t2"},
        ]
        txns = [_txn(id="tx1", description="A"), _txn(id="tx2", date="2026-08-15", description="B")]
        assert stripe_sync._settle_linked_invoices("u1", txns, rows) == 1


class TestChargeContext:
    """The invoice id has to survive the trip back from Stripe."""

    def test_metadata_is_read_from_the_payment_intent(self, monkeypatch):
        """We set it via payment_intent_data, so that is where it reliably is."""
        charge = {
            "billing_details": {"name": "Acme Ltd"},
            "metadata": {},
            "payment_intent": {"metadata": {"kora_invoice_id": "inv_A"}},
        }
        monkeypatch.setattr(stripe_sync.stripe.Charge, "retrieve", staticmethod(lambda *a, **k: charge))
        ctx = stripe_sync._charge_context({"source": "ch_1"}, "acct_1", "sk_test")
        assert ctx["invoice_id"] == "inv_A"
        assert ctx["customer_name"] == "Acme Ltd"

    def test_charge_metadata_wins_when_present(self, monkeypatch):
        charge = {"billing_details": {}, "metadata": {"kora_invoice_id": "inv_DIRECT"}, "payment_intent": None}
        monkeypatch.setattr(stripe_sync.stripe.Charge, "retrieve", staticmethod(lambda *a, **k: charge))
        assert stripe_sync._charge_context({"source": "ch_1"}, "a", "k")["invoice_id"] == "inv_DIRECT"

    def test_a_non_charge_movement_is_skipped(self):
        """Payouts and adjustments have no charge to look up."""
        assert stripe_sync._charge_context({"source": "po_1"}, "a", "k")["invoice_id"] == ""

    def test_a_stripe_failure_degrades_instead_of_raising(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("stripe down")

        monkeypatch.setattr(stripe_sync.stripe.Charge, "retrieve", staticmethod(_boom))
        assert stripe_sync._charge_context({"source": "ch_1"}, "a", "k") == {"customer_name": "", "invoice_id": ""}


class TestMigrationShipped:
    def test_the_migration_exists_and_keeps_both_dedupe_rules(self):
        """external_id is useless until the DB stops enforcing the old shape
        constraint — and CSV imports must keep their protection."""
        import pathlib

        sql = (pathlib.Path(__file__).resolve().parents[1] / "migrations" / "2026-08-15_transaction_external_id.sql").read_text(encoding="utf-8")
        assert "ADD COLUMN IF NOT EXISTS external_id" in sql
        assert "DROP CONSTRAINT IF EXISTS transactions_user_id_date_description_amount_key" in sql
        assert "WHERE external_id IS NULL" in sql  # CSV keeps shape dedupe
        assert "WHERE external_id IS NOT NULL" in sql  # Stripe dedupes by id


@pytest.mark.parametrize("field", ["external_id"])
def test_the_transaction_model_carries_the_field(field):
    assert field in Transaction.model_fields
