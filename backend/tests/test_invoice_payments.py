"""The Pay Now button has to work, or not be there.

`send_invoice` used to fabricate `https://pay.stripe.com/demo/{number}` whenever
an invoice had no link — which was always, because nothing ever created one.
Every invoice this app has sent carried a button that 404s, and it fails in the
worst possible place: in front of the user's own client, on the one element the
email asks them to click.

So the property under test is not "a link is produced". It is **no link is ever
invented**. An invoice with no button still gets paid by bank transfer; an
invoice with a broken button costs the user credibility.

The rest is money arithmetic, where being approximately right is being wrong.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import invoice_payments as ip


def _invoice(**kw):
    base = dict(
        id="inv_1",
        invoice_number="INV-001",
        total=100.0,
        amount_paid=0.0,
        currency="USD",
        payment_link=None,
        status="sent",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestNeverInventALink:
    def test_the_fabricated_url_is_recognised_as_a_placeholder(self):
        """The exact string the old code produced."""
        assert ip.is_placeholder_link("https://pay.stripe.com/demo/INV-001")

    def test_a_real_stripe_link_is_not_a_placeholder(self):
        assert not ip.is_placeholder_link("https://buy.stripe.com/test_abc123")

    def test_no_link_and_no_stripe_account_yields_none(self, monkeypatch):
        """The whole point: an unconnected user gets NO button, not a fake one."""
        monkeypatch.setattr(ip.store, "get_stripe_connection", lambda uid: None)
        assert ip.ensure_payment_link("u1", _invoice()) is None

    def test_a_placeholder_is_replaced_rather_than_reused(self, monkeypatch):
        """A previously "sent" invoice must not keep its dead link forever."""
        monkeypatch.setattr(ip.store, "get_stripe_connection", lambda uid: None)
        inv = _invoice(payment_link="https://pay.stripe.com/demo/INV-001")
        assert ip.ensure_payment_link("u1", inv) is None

    def test_a_real_link_is_reused_without_calling_stripe(self, monkeypatch):
        def _explode(*a, **k):  # pragma: no cover - must not be reached
            raise AssertionError("should not create a second link")

        monkeypatch.setattr(ip, "create_payment_link", _explode)
        inv = _invoice(payment_link="https://buy.stripe.com/test_abc")
        assert ip.ensure_payment_link("u1", inv) == "https://buy.stripe.com/test_abc"

    def test_a_stripe_outage_does_not_break_sending(self, monkeypatch):
        """The send path must survive Stripe being down — the invoice and its
        PDF still need to reach the client."""

        def _boom(*a, **k):
            raise RuntimeError("stripe unreachable")

        monkeypatch.setattr(ip, "create_payment_link", _boom)
        assert ip.ensure_payment_link("u1", _invoice()) is None


class TestMinorUnits:
    def test_dollars_become_cents(self):
        assert ip.to_minor_units(100.0, "USD") == 10000
        assert ip.to_minor_units(29.99, "usd") == 2999

    def test_yen_has_no_subunit(self):
        """Multiplying JPY by 100 overcharges the payer one hundred fold."""
        assert ip.to_minor_units(5000.0, "JPY") == 5000

    @pytest.mark.parametrize("code", ["KRW", "VND", "XAF", "CLP"])
    def test_every_zero_decimal_currency(self, code):
        assert ip.to_minor_units(1000.0, code) == 1000

    def test_three_decimal_currencies_scale_by_a_thousand(self):
        """Treating BHD as two-decimal undercharges by 10x."""
        assert ip.to_minor_units(10.0, "BHD") == 10000

    def test_three_decimal_amounts_are_multiples_of_ten(self):
        """Stripe rejects three-decimal amounts that are not."""
        assert ip.to_minor_units(10.123, "KWD") % 10 == 0

    def test_rounding_does_not_lose_a_cent(self):
        """0.1 + 0.2 float arithmetic must not turn 1.15 into 114."""
        assert ip.to_minor_units(1.15, "USD") == 115
        assert ip.to_minor_units(0.07, "USD") == 7

    def test_an_unknown_currency_falls_back_to_two_decimals(self):
        assert ip.to_minor_units(10.0, "ZZZ") == 1000


class TestOutstandingAmount:
    def test_a_part_paid_invoice_charges_only_the_balance(self):
        """Charging the full total again would take payment twice."""
        assert ip.outstanding_amount(_invoice(total=100.0, amount_paid=40.0)) == 60.0

    def test_an_unpaid_invoice_charges_the_total(self):
        assert ip.outstanding_amount(_invoice(total=100.0, amount_paid=0)) == 100.0

    def test_an_overpaid_invoice_never_goes_negative(self):
        """A negative unit_amount is a Stripe error, not a refund."""
        assert ip.outstanding_amount(_invoice(total=100.0, amount_paid=150.0)) == 0.0

    def test_a_null_amount_paid_is_treated_as_zero(self):
        assert ip.outstanding_amount(_invoice(total=50.0, amount_paid=None)) == 50.0


class TestGuards:
    def _connected(self, monkeypatch, livemode=False):
        monkeypatch.setattr(
            ip.store,
            "get_stripe_connection",
            lambda uid: {"connected": True, "stripe_account_id": "acct_1", "livemode": livemode},
        )
        monkeypatch.setattr(ip.settings, "STRIPE_SECRET_KEY", "sk_test_x")

    def test_a_settled_invoice_is_refused(self, monkeypatch):
        self._connected(monkeypatch)
        with pytest.raises(ip.PaymentLinkUnavailable, match="nothing left to pay"):
            ip.create_payment_link("u1", _invoice(total=100.0, amount_paid=100.0))

    def test_a_disconnected_account_says_what_to_do(self, monkeypatch):
        monkeypatch.setattr(ip.store, "get_stripe_connection", lambda uid: None)
        with pytest.raises(ip.PaymentLinkUnavailable, match="Connect your Stripe account"):
            ip.create_payment_link("u1", _invoice())

    def test_a_live_account_on_a_test_deployment_is_refused_clearly(self, monkeypatch):
        """Stripe's own error for this mismatch is opaque; ours names both sides."""
        self._connected(monkeypatch, livemode=True)
        with pytest.raises(ip.PaymentLinkUnavailable, match="live.*test|test.*live"):
            ip.create_payment_link("u1", _invoice())

    def test_a_connection_row_marked_disconnected_is_not_used(self, monkeypatch):
        monkeypatch.setattr(
            ip.store,
            "get_stripe_connection",
            lambda uid: {"connected": False, "stripe_account_id": "acct_1"},
        )
        with pytest.raises(ip.PaymentLinkUnavailable):
            ip.create_payment_link("u1", _invoice())


class TestLinkCreation:
    def test_the_link_carries_the_ids_the_webhook_needs(self, monkeypatch):
        """Without this metadata a completed payment cannot be matched back to
        an invoice, and the money arrives with nothing marked paid."""
        captured = {}
        monkeypatch.setattr(
            ip.store,
            "get_stripe_connection",
            lambda uid: {"connected": True, "stripe_account_id": "acct_1", "livemode": False},
        )
        monkeypatch.setattr(ip.settings, "STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setattr(ip.stripe.Price, "create", staticmethod(lambda **k: SimpleNamespace(id="price_1")))

        def _link(**kw):
            captured.update(kw)
            return SimpleNamespace(url="https://buy.stripe.com/test_xyz")

        monkeypatch.setattr(ip.stripe.PaymentLink, "create", staticmethod(_link))

        url = ip.create_payment_link("u1", _invoice())
        assert url == "https://buy.stripe.com/test_xyz"
        assert captured["metadata"]["kora_invoice_id"] == "inv_1"
        assert captured["metadata"]["kora_user_id"] == "u1"
        assert captured["payment_intent_data"]["metadata"]["kora_invoice_id"] == "inv_1"

    def test_it_charges_on_the_connected_account_not_the_platform(self, monkeypatch):
        """Direct charges: the money must reach the user, not this platform."""
        seen = {}
        monkeypatch.setattr(
            ip.store,
            "get_stripe_connection",
            lambda uid: {"connected": True, "stripe_account_id": "acct_TARGET", "livemode": False},
        )
        monkeypatch.setattr(ip.settings, "STRIPE_SECRET_KEY", "sk_test_x")

        def _price(**k):
            seen["price_account"] = k.get("stripe_account")
            seen["unit_amount"] = k.get("unit_amount")
            return SimpleNamespace(id="price_1")

        monkeypatch.setattr(ip.stripe.Price, "create", staticmethod(_price))
        monkeypatch.setattr(
            ip.stripe.PaymentLink,
            "create",
            staticmethod(lambda **k: seen.update(link_account=k.get("stripe_account")) or SimpleNamespace(url="u")),
        )

        ip.create_payment_link("u1", _invoice(total=42.50))
        assert seen["price_account"] == "acct_TARGET"
        assert seen["link_account"] == "acct_TARGET"
        assert seen["unit_amount"] == 4250

    def test_a_new_link_is_persisted_so_it_is_made_once(self, monkeypatch):
        """The follow-up agent runs over every unpaid invoice on days 3, 7 and
        14 — without persistence each pass mints another link."""
        writes = []
        monkeypatch.setattr(ip, "create_payment_link", lambda uid, inv: "https://buy.stripe.com/test_1")
        monkeypatch.setattr(ip.store, "update_invoice", lambda uid, iid, patch: writes.append((iid, patch)))
        assert ip.ensure_payment_link("u1", _invoice()) == "https://buy.stripe.com/test_1"
        assert writes == [("inv_1", {"payment_link": "https://buy.stripe.com/test_1"})]

    def test_a_failed_persist_still_returns_the_link(self, monkeypatch):
        """The client should get their button even if our write failed."""
        monkeypatch.setattr(ip, "create_payment_link", lambda uid, inv: "https://buy.stripe.com/test_1")

        def _boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(ip.store, "update_invoice", _boom)
        assert ip.ensure_payment_link("u1", _invoice()) == "https://buy.stripe.com/test_1"


class TestSeedCarriesNoFakeLinks:
    def test_the_sample_invoices_have_no_fabricated_links(self):
        """Sample data reaches every new tenant, and a judge clicking Pay on a
        sample invoice would have hit the same dead URL."""
        from app.seed import build_seed

        for inv in build_seed("u-seed")["invoices"]:
            assert not ip.is_placeholder_link(inv.payment_link)
