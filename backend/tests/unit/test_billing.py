"""Unit tests for app/services/billing.py — plan limits and feature gating.

Covers:
- get_user_plan (user found, user missing)
- require_plan (allowed, denied, boundary)
- check_feature (all plan tiers, unknown feature)
- check_transaction_limit (unlimited plan, limited plan under/over/at limit)
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from app.services.billing import (
    PLAN_LIMITS,
    PLAN_RANK,
    check_feature,
    check_transaction_limit,
    get_user_plan,
    require_plan,
)
from app.models import Transaction, User


def _user(plan: str = "pro") -> User:
    return User(id="u-1", email="u@example.com", plan=plan,
                created_at=datetime.now(timezone.utc).isoformat())


def _tx(days_ago: int = 0) -> Transaction:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return Transaction(
        id=f"tx-{days_ago}", user_id="u-1", date=ts[:10],
        description="test", amount=-10.0, type="expense",
        created_at=ts,
    )


def _month_start() -> datetime:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _tx_this_month(seq: int = 0) -> Transaction:
    """Transaction with created_at inside the current calendar month (UTC)."""
    ts = (_month_start() + timedelta(hours=seq + 1)).isoformat()
    return Transaction(
        id=f"tx-month-{seq}", user_id="u-1", date=ts[:10],
        description="test", amount=-10.0, type="expense",
        created_at=ts,
    )


def _tx_before_month(seq: int = 0) -> Transaction:
    """Transaction with created_at before the current calendar month (UTC)."""
    ts = (_month_start() - timedelta(days=1 + seq)).isoformat()
    return Transaction(
        id=f"tx-old-{seq}", user_id="u-1", date=ts[:10],
        description="test", amount=-10.0, type="expense",
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


# ── check_feature ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("plan,feature,expected", [
    ("free",    "invoice_followups",  False),
    ("free",    "cashflow_forecast",  False),
    ("starter", "invoice_followups",  True),
    ("starter", "cashflow_forecast",  False),
    ("pro",     "cashflow_forecast",  True),
    ("pro",     "butler_full",        True),
    ("free",    "butler_full",        False),
    ("pro",     "nonexistent",        False),
])
def test_check_feature(monkeypatch, plan, feature, expected):
    from app import store
    monkeypatch.setattr(store, "get_user", lambda uid: _user(plan))
    assert check_feature("u-1", feature) is expected


# ── check_transaction_limit ───────────────────────────────────────────────────

def test_transaction_limit_unlimited_for_pro(monkeypatch):
    from app import store
    monkeypatch.setattr(store, "get_user", lambda uid: _user("pro"))
    monkeypatch.setattr(store, "list_transactions", lambda uid: [])
    result = check_transaction_limit("u-1")
    assert result["allowed"] is True
    assert result["limit"] is None


def test_transaction_limit_unlimited_for_starter(monkeypatch):
    from app import store
    monkeypatch.setattr(store, "get_user", lambda uid: _user("starter"))
    monkeypatch.setattr(store, "list_transactions", lambda uid: [])
    result = check_transaction_limit("u-1")
    assert result["allowed"] is True
    assert result["limit"] is None


def test_transaction_limit_free_under_limit(monkeypatch):
    from app import store
    monkeypatch.setattr(store, "get_user", lambda uid: _user("free"))
    monkeypatch.setattr(store, "list_transactions", lambda uid: [_tx(0), _tx(1)])
    result = check_transaction_limit("u-1")
    assert result["allowed"] is True
    assert result["limit"] == 20
    assert result["used"] == 2
    assert result["remaining"] == 18


def test_transaction_limit_free_at_limit(monkeypatch):
    from app import store
    monkeypatch.setattr(store, "get_user", lambda uid: _user("free"))
    txs = [_tx_this_month(i) for i in range(20)]
    monkeypatch.setattr(store, "list_transactions", lambda uid: txs)
    result = check_transaction_limit("u-1")
    assert result["allowed"] is False
    assert result["remaining"] == 0


def test_transaction_limit_excludes_old_transactions(monkeypatch):
    from app import store
    monkeypatch.setattr(store, "get_user", lambda uid: _user("free"))
    # 19 this month + 5 from before month_start
    this_month = [_tx_this_month(i) for i in range(19)]
    old = [_tx_before_month(i) for i in range(5)]
    monkeypatch.setattr(store, "list_transactions", lambda uid: this_month + old)
    result = check_transaction_limit("u-1")
    assert result["allowed"] is True
    assert result["used"] == 19
