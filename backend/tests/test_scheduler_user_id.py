"""The scheduler has to know which tenant it is acting for.

Cron requests carry a shared secret, not a session, so nothing on the request
says who to act as. Nine routers each resolved that independently, and every one
of them fell back to the literal string ``"demo-user"`` when the lookup missed.
Against Postgres that is not a user id at all, it is a malformed UUID, so the
miss surfaced as ``22P02 invalid input syntax for type uuid`` — an opaque 500,
raised three frames below the actual mistake, on every scheduled run.

The miss was real, not theoretical: the demo tenant's row was repointed to a
different email and ``DEMO_EMAIL`` stayed where it was. These tests pin the two
properties that would have caught it — a miss never yields a non-UUID id, and it
reports itself as configuration rather than as a database error.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import dependencies
from app.config import settings
from app.models import User
from app.seed import DEMO_USER_ID


REAL_UUID = "dbb91cc1-f313-4588-98d6-b20ac44d4d4b"


@pytest.fixture
def cfg(monkeypatch):
    """Reset the two settings this reads, so a test states its own world."""
    monkeypatch.setattr(settings, "SCHEDULER_USER_ID", "", raising=False)
    monkeypatch.setattr(settings, "DEMO_EMAIL", "demo@kora.app", raising=False)
    return monkeypatch


def _lookup_returns(monkeypatch, user: User | None):
    monkeypatch.setattr(dependencies.store, "get_user_by_email", lambda email: user)


def _user(uid: str, email: str) -> User:
    return User(id=uid, email=email, created_at="2026-01-01T00:00:00Z")


class TestExplicitOverride:
    def test_scheduler_user_id_wins_over_the_email_lookup(self, cfg):
        """An id is stable; the demo account's email has already moved once."""
        cfg.setattr(settings, "SCHEDULER_USER_ID", REAL_UUID)
        cfg.setattr(settings, "KORA_DATA_BACKEND", "supabase")
        _lookup_returns(cfg, _user("some-other-id", "demo@kora.app"))
        assert dependencies.scheduler_user_id() == REAL_UUID

    def test_the_override_does_not_need_the_email_to_resolve(self, cfg):
        cfg.setattr(settings, "SCHEDULER_USER_ID", REAL_UUID)
        cfg.setattr(settings, "KORA_DATA_BACKEND", "supabase")

        def _explode(email):  # pragma: no cover - must never be called
            raise AssertionError("lookup should be skipped when the id is pinned")

        cfg.setattr(dependencies.store, "get_user_by_email", _explode)
        assert dependencies.scheduler_user_id() == REAL_UUID


class TestSupabaseLookup:
    def test_a_hit_returns_the_tenants_real_id(self, cfg):
        cfg.setattr(settings, "KORA_DATA_BACKEND", "supabase")
        _lookup_returns(cfg, _user(REAL_UUID, "demo@kora.app"))
        assert dependencies.scheduler_user_id() == REAL_UUID

    def test_a_miss_returns_none_rather_than_a_non_uuid(self, cfg):
        """The regression. Returning DEMO_USER_ID here is what produced 22P02."""
        cfg.setattr(settings, "KORA_DATA_BACKEND", "supabase")
        _lookup_returns(cfg, None)
        assert dependencies.scheduler_user_id() is None

    def test_a_miss_never_yields_the_mock_sentinel(self, cfg):
        cfg.setattr(settings, "KORA_DATA_BACKEND", "supabase")
        _lookup_returns(cfg, None)
        assert dependencies.scheduler_user_id() != DEMO_USER_ID


class TestMockMode:
    def test_mock_mode_still_uses_the_seeded_demo_id(self, cfg):
        """Off Supabase there is no UUID column to offend, and the seed uses it."""
        cfg.setattr(settings, "KORA_DATA_BACKEND", "mock")
        assert dependencies.scheduler_user_id() == DEMO_USER_ID


class TestRequireVariant:
    def test_it_passes_a_resolved_id_straight_through(self, cfg):
        cfg.setattr(settings, "SCHEDULER_USER_ID", REAL_UUID)
        assert dependencies.require_scheduler_user_id() == REAL_UUID

    def test_an_unresolvable_tenant_is_503_not_500(self, cfg):
        """Config the operator can fix, reported as config — not as a crash."""
        cfg.setattr(settings, "KORA_DATA_BACKEND", "supabase")
        _lookup_returns(cfg, None)
        with pytest.raises(HTTPException) as exc:
            dependencies.require_scheduler_user_id()
        assert exc.value.status_code == 503

    def test_the_error_names_both_ways_to_fix_it(self, cfg):
        cfg.setattr(settings, "KORA_DATA_BACKEND", "supabase")
        cfg.setattr(settings, "DEMO_EMAIL", "stale@kora.app")
        _lookup_returns(cfg, None)
        with pytest.raises(HTTPException) as exc:
            dependencies.require_scheduler_user_id()
        detail = exc.value.detail
        assert "SCHEDULER_USER_ID" in detail
        assert "DEMO_EMAIL" in detail
        # Naming the value that missed is what turns this into a one-step fix.
        assert "stale@kora.app" in detail


class TestNoRouterKeepsItsOwnCopy:
    """Nine copies drifting apart is how one bug became nine identical bugs."""

    def test_routers_share_the_single_helper(self):
        import pathlib

        routers = pathlib.Path(dependencies.__file__).parent / "routers"
        offenders = [p.name for p in routers.glob("*.py") if "def _scheduler_user_id" in p.read_text(encoding="utf-8")]
        assert not offenders, f"local scheduler-tenant helpers reintroduced in: {offenders}"

    def test_every_cron_route_uses_the_failing_variant(self):
        """`scheduler_user_id()` returns None on a miss; a router that used it
        directly would pass None to the store and reproduce the original 500."""
        import pathlib
        import re

        routers = pathlib.Path(dependencies.__file__).parent / "routers"
        bad = []
        for p in routers.glob("*.py"):
            src = p.read_text(encoding="utf-8")
            # Match a bare call, not the require_ prefixed one.
            if re.search(r"(?<!require_)\bscheduler_user_id\(\)", src):
                bad.append(p.name)
        assert not bad, f"these call the nullable variant instead of require_: {bad}"
