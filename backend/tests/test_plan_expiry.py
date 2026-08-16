"""The launch trial has to actually end.

Early users are promised the full suite for 90 days and the Free plan after
that. The failure mode is silent and one-directional: if expiry does not work,
everyone who signed up in the launch window keeps Pro forever, nobody complains,
and the first sign of it is a bill for model calls nobody is paying for.

Two properties matter, and the second is what makes the first safe:

  * a lapsed plan stops unlocking features AT THE GATE, computed per request —
    not swept by a nightly job, because a job that fails to run leaves lapsed
    trials working and its failure looks exactly like success;
  * the stored plan is written back to free once it lapses, so the billing
    screen, the pricing page and the usage dashboard stop disagreeing with what
    the user can actually do.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import entitlements as ent
from app.config import settings
from app.models import User


def _user(plan: str = "pro", expires_in_days: float | None = None, **kw) -> User:
    expires = None
    if expires_in_days is not None:
        expires = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()
    return User(
        id=kw.get("id", "u1"),
        email="u@example.com",
        plan=plan,
        plan_expires_at=expires,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


class TestEffectivePlan:
    def test_a_live_trial_still_grants_pro(self):
        assert ent.effective_plan(_user("pro", expires_in_days=30)) == "pro"

    def test_a_lapsed_trial_is_free(self):
        """The whole point. Stored plan still says pro; the answer is free."""
        assert ent.effective_plan(_user("pro", expires_in_days=-1)) == "free"

    def test_a_plan_with_no_expiry_never_lapses(self):
        """A paying customer has no expiry and must not be downgraded by this."""
        assert ent.effective_plan(_user("pro", expires_in_days=None)) == "pro"

    def test_expiry_on_a_free_account_changes_nothing(self):
        assert ent.effective_plan(_user("free", expires_in_days=-5)) == "free"

    def test_the_boundary_is_closed(self):
        """At the exact moment of expiry the trial is over, not still running."""
        u = _user("pro")
        u.plan_expires_at = datetime.now(timezone.utc).isoformat()
        assert ent.effective_plan(u) == "free"

    def test_an_unparseable_expiry_does_not_revoke_access(self):
        """A bad value is a data problem. Failing open keeps a paying customer
        working; failing closed locks them out of what they bought."""
        u = _user("pro")
        u.plan_expires_at = "not-a-date"
        assert ent.effective_plan(u) == "pro"


class TestTheGateUsesIt:
    """`enforce_plan` reading user.plan directly is exactly how a lapsed trial
    would keep working."""

    def test_a_lapsed_pro_is_refused_a_pro_route(self):
        assert not ent.allows(ent.effective_plan(_user("pro", expires_in_days=-1)), "POST", "/api/contracts/generate")

    def test_a_live_pro_is_allowed(self):
        assert ent.allows(ent.effective_plan(_user("pro", expires_in_days=1)), "POST", "/api/contracts/generate")

    def test_a_lapsed_pro_keeps_the_free_features(self):
        """Lapsing must not lock someone out of their own books."""
        plan = ent.effective_plan(_user("pro", expires_in_days=-1))
        assert ent.allows(plan, "GET", "/api/clients")
        assert ent.allows(plan, "GET", "/api/invoices")


class TestDaysRemaining:
    def test_it_rounds_up(self):
        """Eight hours left is "1 day", not "0 days" while it still works."""
        assert ent.days_remaining(_user("pro", expires_in_days=0.33)) == 1

    def test_a_full_window(self):
        assert ent.days_remaining(_user("pro", expires_in_days=89.5)) == 90

    def test_a_lapsed_plan_is_zero_not_negative(self):
        assert ent.days_remaining(_user("pro", expires_in_days=-3)) == 0

    def test_no_expiry_is_none(self):
        assert ent.days_remaining(_user("pro")) is None


class TestGrantSetsTheWindow:
    @pytest.fixture
    def writes(self, monkeypatch):
        captured = []
        import app.store as store_mod

        monkeypatch.setattr(store_mod, "update_user", lambda uid, patch: captured.append(patch))
        monkeypatch.setattr(settings, "SIGNUP_PLAN", "pro", raising=False)
        return captured

    def test_ninety_days_is_recorded(self, monkeypatch, writes):
        monkeypatch.setattr(settings, "SIGNUP_PLAN_DAYS", 90, raising=False)
        assert ent.grant_signup_plan("u1", "free") == "pro"
        patch = writes[0]
        assert patch["plan"] == "pro"
        expires = datetime.fromisoformat(patch["plan_expires_at"])
        days = (expires - datetime.now(timezone.utc)).total_seconds() / 86400
        assert 89.9 < days < 90.1

    def test_zero_days_means_no_expiry(self, monkeypatch, writes):
        """A permanent grant is still possible — the flag controls it."""
        monkeypatch.setattr(settings, "SIGNUP_PLAN_DAYS", 0, raising=False)
        ent.grant_signup_plan("u1", "free")
        assert "plan_expires_at" not in writes[0]

    def test_a_paying_customer_is_never_given_an_expiry(self, monkeypatch, writes):
        """Granting must not stamp a deadline onto an account that already
        holds the tier — that would cancel a real subscription."""
        monkeypatch.setattr(settings, "SIGNUP_PLAN_DAYS", 90, raising=False)
        assert ent.grant_signup_plan("u1", "pro") is None
        assert writes == []


class TestSettleLapsed:
    @pytest.fixture
    def writes(self, monkeypatch):
        captured = []
        import app.store as store_mod

        monkeypatch.setattr(store_mod, "update_user", lambda uid, patch: captured.append(patch))
        return captured

    def test_a_lapsed_plan_is_written_back_to_free(self, writes):
        assert ent.settle_lapsed_plan(_user("pro", expires_in_days=-1)) is True
        assert writes == [{"plan": "free", "plan_expires_at": None}]

    def test_a_live_trial_is_left_alone(self, writes):
        assert ent.settle_lapsed_plan(_user("pro", expires_in_days=10)) is False
        assert writes == []

    def test_an_account_with_no_expiry_is_left_alone(self, writes):
        assert ent.settle_lapsed_plan(_user("pro")) is False
        assert writes == []

    def test_it_is_idempotent_once_free(self, writes):
        assert ent.settle_lapsed_plan(_user("free", expires_in_days=-1)) is False
        assert writes == []

    def test_a_write_failure_is_not_fatal(self, monkeypatch):
        """Auth must not fail because a billing write did."""
        import app.store as store_mod

        def _boom(uid, patch):
            raise RuntimeError("db down")

        monkeypatch.setattr(store_mod, "update_user", _boom)
        assert ent.settle_lapsed_plan(_user("pro", expires_in_days=-1)) is False


class TestTheRequestPathSettlesIt:
    def test_stamping_a_lapsed_user_downgrades_the_object_in_place(self, monkeypatch):
        """The verified-token cache holds this very instance — without updating
        it, the response to this request still claims Pro, and so does every
        cached request for the next 30 seconds."""
        from app import dependencies

        import app.store as store_mod

        monkeypatch.setattr(store_mod, "update_user", lambda uid, patch: None)
        user = _user("pro", expires_in_days=-1)
        dependencies._settle_lapsed_trial(user)
        assert user.plan == "free"
        assert user.plan_expires_at is None

    def test_a_live_trial_is_untouched(self, monkeypatch):
        from app import dependencies

        user = _user("pro", expires_in_days=5)
        dependencies._settle_lapsed_trial(user)
        assert user.plan == "pro"
        assert user.plan_expires_at is not None
