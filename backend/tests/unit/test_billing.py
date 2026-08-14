"""Unit tests for app/services/billing.py — which plan a user is on.

Covers:
- get_user_plan (user found, user missing)
- require_plan (allowed, denied, boundary)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from app.services.billing import (
    get_user_plan,
    require_plan,
)
from app.models import Transaction, User


def _user(plan: str = "pro") -> User:
    return User(id="u-1", email="u@example.com", plan=plan, created_at=datetime.now(timezone.utc).isoformat())


def _tx(days_ago: int = 0) -> Transaction:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return Transaction(
        id=f"tx-{days_ago}",
        user_id="u-1",
        date=ts[:10],
        description="test",
        amount=-10.0,
        type="expense",
        created_at=ts,
    )


def _month_start() -> datetime:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _tx_this_month(seq: int = 0) -> Transaction:
    """Transaction with created_at inside the current calendar month (UTC)."""
    ts = (_month_start() + timedelta(hours=seq + 1)).isoformat()
    return Transaction(
        id=f"tx-month-{seq}",
        user_id="u-1",
        date=ts[:10],
        description="test",
        amount=-10.0,
        type="expense",
        created_at=ts,
    )


def _tx_before_month(seq: int = 0) -> Transaction:
    """Transaction with created_at before the current calendar month (UTC)."""
    ts = (_month_start() - timedelta(days=1 + seq)).isoformat()
    return Transaction(
        id=f"tx-old-{seq}",
        user_id="u-1",
        date=ts[:10],
        description="test",
        amount=-10.0,
        type="expense",
        created_at=ts,
    )


# ── get_user_plan ─────────────────────────────────────────────────────────────


def test_get_user_plan_returns_plan(monkeypatch):
    from app import store

    monkeypatch.setattr(store, "get_user", lambda uid: _user("starter"))
    assert get_user_plan("u-1") == "starter"


def test_get_user_plan_missing_user_returns_free(monkeypatch):
    from app import store

    monkeypatch.setattr(store, "get_user", lambda uid: None)
    assert get_user_plan("missing") == "free"


def test_get_user_plan_none_plan_returns_free(monkeypatch):
    from app import store

    u = _user("pro")
    u.plan = None  # type: ignore[assignment]
    monkeypatch.setattr(store, "get_user", lambda uid: u)
    assert get_user_plan("u-1") == "free"


# ── require_plan ─────────────────────────────────────────────────────────────


def test_require_plan_allowed(monkeypatch):
    from app import store

    monkeypatch.setattr(store, "get_user", lambda uid: _user("pro"))
    result = require_plan("u-1", "starter")
    assert result["allowed"] is True
    assert result["current_plan"] == "pro"


def test_require_plan_denied(monkeypatch):
    from app import store

    monkeypatch.setattr(store, "get_user", lambda uid: _user("free"))
    result = require_plan("u-1", "starter")
    assert result["allowed"] is False
    assert result["required_plan"] == "starter"


def test_require_plan_exact_match_allowed(monkeypatch):
    from app import store

    monkeypatch.setattr(store, "get_user", lambda uid: _user("starter"))
    assert require_plan("u-1", "starter")["allowed"] is True


def test_require_plan_pro_required_starter_denied(monkeypatch):
    from app import store

    monkeypatch.setattr(store, "get_user", lambda uid: _user("starter"))
    assert require_plan("u-1", "pro")["allowed"] is False
