"""Each tenant's starter business must look like its own.

Seeding every tenant with a byte-identical business backfired: two people
compared screens, saw the same clients and the same totals, and concluded the
app leaked data between accounts. It did not — the rows had distinct ids and
correct user_ids — but "looks like a breach" is a worse first impression than
an empty dashboard.

The risk in fixing it is desynchronisation. Client names are join keys (butler
matches invoices to clients BY NAME) and they also appear inside generated email
bodies and alert copy, as do the amounts. A rename that misses the free text
leaves the app contradicting itself in front of a judge, which is its own kind
of broken. These tests pin both halves: tenants differ, and each tenant stays
internally consistent.
"""

from __future__ import annotations

import re

import pytest

from app.services import sample_data as sd
from app.seed import build_seed


A = "11111111-1111-1111-1111-111111111111"
B = "22222222-2222-2222-2222-222222222222"


def personalized(uid: str) -> dict:
    return sd._personalize(build_seed(uid), uid)


class TestTenantsDiffer:
    def test_two_tenants_get_different_client_names(self):
        """The regression that started this."""
        a = {c.name for c in personalized(A)["clients"]}
        b = {c.name for c in personalized(B)["clients"]}
        assert not (a & b), f"overlapping client names: {a & b}"

    def test_two_tenants_get_different_totals(self):
        a = sum(i.total for i in personalized(A)["invoices"])
        b = sum(i.total for i in personalized(B)["invoices"])
        assert a != b

    def test_names_do_not_collapse_onto_each_other(self):
        """Distinct seeded clients must stay distinct after renaming."""
        for uid in (A, B, "abc", "zzz-9"):
            names = [c.name for c in personalized(uid)["clients"]]
            assert len(names) == len(set(names)), f"{uid} collapsed: {names}"

    def test_the_original_names_are_gone(self):
        names = {c.name for c in personalized(A)["clients"]}
        assert "Acme Corp" not in names
        assert "Blue Label LLC" not in names


class TestDeterministic:
    def test_the_same_tenant_reproduces_the_same_business(self):
        """A re-seed must not invent a second, different sample."""
        first = [c.name for c in personalized(A)["clients"]]
        second = [c.name for c in personalized(A)["clients"]]
        assert first == second

    def test_totals_are_reproducible_too(self):
        one = sum(i.total for i in personalized(A)["invoices"])
        two = sum(i.total for i in personalized(A)["invoices"])
        assert one == two


class TestInternallyConsistent:
    def test_every_invoice_still_matches_a_client(self):
        """butler joins invoices to clients by name — this is the join key."""
        data = personalized(A)
        clients = {c.name for c in data["clients"]}
        invoice_names = {i.client_name for i in data["invoices"] if i.client_name}
        unmatched = {n for n in invoice_names if n not in clients}
        # The seed intentionally includes one invoice for a non-client; the point
        # is that renaming must not INCREASE the mismatch.
        original = build_seed(A)
        orig_clients = {c.name for c in original["clients"]}
        orig_unmatched = {i.client_name for i in original["invoices"] if i.client_name and i.client_name not in orig_clients}
        assert len(unmatched) == len(orig_unmatched)

    def test_generated_text_uses_the_new_names(self):
        """Alert and email copy must not still name the original client."""
        data = personalized(A)
        blob = " ".join(str(a.body) for a in data["alerts"]) + " ".join(str(l.action) for l in data["agent_logs"])
        assert "Blue Label LLC" not in blob
        assert "Acme Corp" not in blob

    def test_amounts_in_text_are_rescaled_with_the_data(self):
        """The overdue alert quotes an amount; it must match the invoice."""
        data = personalized(A)
        bodies = [str(a.body) for a in data["alerts"] if "late" in str(a.body)]
        assert bodies, "expected an overdue alert"
        quoted = {float(m.replace(",", "")) for b in bodies for m in re.findall(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)", b)}
        totals = {round(i.total, 2) for i in data["invoices"]}
        assert quoted & totals, f"quoted {quoted} matches no invoice total {totals}"

    def test_non_money_numbers_are_untouched(self):
        """Scaling must not corrupt confidence scores or similar."""
        data = personalized(A)
        for txn in data["transactions"]:
            conf = getattr(txn, "confidence", None)
            if conf is not None:
                assert 0.0 <= conf <= 1.0

    def test_record_counts_are_unchanged(self):
        original, varied = build_seed(A), personalized(A)
        for key in ("clients", "invoices", "transactions", "contracts", "alerts"):
            assert len(varied[key]) == len(original[key]), key


class TestScaling:
    @pytest.mark.parametrize("uid", [A, B, "x", "another-tenant-id", "0"])
    def test_the_multiplier_stays_believable(self, uid):
        s = sd._scale_for(uid)
        assert 0.55 <= s <= 1.75

    def test_totals_stay_positive(self):
        assert all(i.total > 0 for i in personalized(B)["invoices"])
