"""The published prices must describe the gate that is actually enforced.

The pricing page used to keep its own copy of the tiers. It drifted: it sold a
cash-flow forecast as Pro when POLICY unlocks it at Starter, advertised a
"20 transactions/month" cap and an "Invoice follow-up agent" that nothing
enforces, and omitted two capabilities that genuinely are paid. A prospect could
disprove it in about a minute, and the second table it had copied from
(PLAN_LIMITS) was dead code no route ever consulted.

The comparison is now derived from POLICY. These tests exist to keep the
derivation honest, because the failure mode is silent — a gated route with no
label just quietly vanishes from the page a customer is reading before they pay.
"""

from __future__ import annotations

import pytest

from app.entitlements import (
    FEATURE_LABELS,
    FREE,
    FREE_FEATURES,
    POLICY,
    PRO,
    STARTER,
    grant_signup_plan,
    plan_features,
    plans_payload,
)


class TestCatalogueMatchesPolicy:
    def test_every_gated_route_is_described(self):
        """A premium route with no label disappears from the page silently."""
        missing = sorted(set(POLICY) - set(FEATURE_LABELS))
        assert not missing, f"gated but undescribed: {missing}"

    def test_nothing_is_advertised_that_is_not_gated(self):
        """The original bug: paid bullets for capabilities anyone can use."""
        extra = sorted(set(FEATURE_LABELS) - set(POLICY))
        assert not extra, f"described as paid but ungated: {extra}"


class TestTierAssignment:
    def test_cash_flow_forecast_is_advertised_at_the_tier_that_unlocks_it(self):
        """The specific mismatch: sold as Pro, enforced at Starter."""
        starter = plan_features(STARTER)
        assert any("Cash-flow" in f for f in starter)
        assert not any("Cash-flow" in f for f in plan_features(PRO))

    def test_contract_drafting_is_pro(self):
        assert any("Contract" in f for f in plan_features(PRO))

    def test_the_four_contract_routes_collapse_to_one_bullet(self):
        """Four routes are one capability to a buyer, not four line items."""
        contract_bullets = [f for f in plan_features(PRO) if "Contract" in f]
        assert len(contract_bullets) == 1

    def test_free_advertises_nothing_that_is_gated(self):
        """Each free bullet is a claim about an ungated route."""
        gated_labels = set(FEATURE_LABELS.values())
        assert not (set(FREE_FEATURES) & gated_labels)


class TestPayloadShape:
    def test_three_tiers_in_ascending_order(self):
        assert [p["id"] for p in plans_payload()] == [FREE, STARTER, PRO]

    def test_each_paid_tier_inherits_the_one_below(self):
        payload = {p["id"]: p for p in plans_payload()}
        assert "Everything in Free" in payload[STARTER]["features"]
        assert "Everything in Starter" in payload[PRO]["features"]

    def test_free_has_no_price_id(self):
        assert plans_payload({"starter": "s", "pro": "p"})[0]["priceId"] is None

    def test_price_ids_are_passed_through(self):
        payload = {p["id"]: p for p in plans_payload({"starter": "price_S", "pro": "price_P"})}
        assert payload[STARTER]["priceId"] == "price_S"
        assert payload[PRO]["priceId"] == "price_P"

    def test_an_unconfigured_price_id_is_null_not_empty_string(self):
        """The page disables the button on null; "" would render as clickable."""
        payload = {p["id"]: p for p in plans_payload({"starter": "", "pro": ""})}
        assert payload[STARTER]["priceId"] is None

    def test_every_tier_carries_a_price_and_features(self):
        for plan in plans_payload():
            assert plan["price"], plan["id"]
            assert plan["features"], plan["id"]


class TestSignupGrant:
    """Granting the evaluation tier must not become a way to rewrite plans."""

    @pytest.fixture
    def store_calls(self, monkeypatch):
        calls = []
        from app import entitlements as ent
        import app.store as store_mod

        monkeypatch.setattr(store_mod, "update_user", lambda uid, data: calls.append((uid, data)))
        monkeypatch.setattr(ent, "_RANK", ent._RANK)
        return calls

    def _set(self, monkeypatch, value):
        from app.config import settings

        monkeypatch.setattr(settings, "SIGNUP_PLAN", value, raising=False)

    def test_disabled_by_default(self, monkeypatch, store_calls):
        self._set(monkeypatch, "")
        assert grant_signup_plan("u-1", "free") is None
        assert not store_calls

    def test_grants_the_configured_plan_to_a_free_account(self, monkeypatch, store_calls):
        self._set(monkeypatch, "pro")
        assert grant_signup_plan("u-1", "free") == "pro"
        assert store_calls == [("u-1", {"plan": "pro"})]

    def test_never_downgrades_a_paying_account(self, monkeypatch, store_calls):
        """Re-running onboarding must not knock a Pro customer back to Starter."""
        self._set(monkeypatch, "starter")
        assert grant_signup_plan("u-1", "pro") is None
        assert not store_calls

    def test_is_idempotent_at_the_same_tier(self, monkeypatch, store_calls):
        self._set(monkeypatch, "pro")
        assert grant_signup_plan("u-1", "pro") is None
        assert not store_calls

    def test_an_unknown_plan_name_is_ignored(self, monkeypatch, store_calls):
        """A typo in deployment config must not write garbage into the column."""
        self._set(monkeypatch, "enterprise")
        assert grant_signup_plan("u-1", "free") is None
        assert not store_calls

    def test_free_is_not_a_grant(self, monkeypatch, store_calls):
        self._set(monkeypatch, "free")
        assert grant_signup_plan("u-1", "free") is None
        assert not store_calls

    def test_case_and_whitespace_are_tolerated(self, monkeypatch, store_calls):
        self._set(monkeypatch, "  PRO  ")
        assert grant_signup_plan("u-1", "free") == "pro"

    def test_a_store_failure_does_not_block_onboarding(self, monkeypatch):
        self._set(monkeypatch, "pro")
        import app.store as store_mod

        def _boom(uid, data):
            raise RuntimeError("column missing")

        monkeypatch.setattr(store_mod, "update_user", _boom)
        assert grant_signup_plan("u-1", "free") is None
