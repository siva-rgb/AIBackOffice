"""Unit tests for app/dependencies.py — auth and plan-gate logic.

Covers the lines not exercised by the integration suite:
- get_current_user in supabase mode (valid token, invalid token, demo bridge,
  ALLOW_DEMO_USER=False)
- require_plan factory (allowed, denied)
- verify_cron_secret (match, mismatch, missing)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.dependencies import _bearer, get_current_user, require_plan, verify_cron_secret
from app.models import User


def _user(plan: str = "pro") -> User:
    return User(
        id="u-1",
        email="u@example.com",
        plan=plan,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _fake_request():
    """A minimal stand-in for `fastapi.Request`.

    `get_current_user` (M11.2) needs a `Request` to stamp `request.state.user_id`.
    We don't need the ASGI plumbing — just an object with a mutable `state`
    attribute — because the unit tests are about the auth flow, not HTTP.
    """
    r = MagicMock()
    r.state = MagicMock()
    r.state.user_id = None
    return r


# ── _bearer ─────────────────────────────────────────────────────────────────


def test_bearer_extracts_token():
    assert _bearer("Bearer abc123") == "abc123"


def test_bearer_case_insensitive():
    assert _bearer("bearer tok") == "tok"


def test_bearer_none_on_missing():
    assert _bearer(None) is None
    assert _bearer("Basic xyz") is None


# ── get_current_user — mock mode ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_mode_returns_demo_user(monkeypatch):
    from app import store

    monkeypatch.setattr("app.dependencies.settings.KORA_DATA_BACKEND", "mock")
    u = _user()
    monkeypatch.setattr(store, "get_user", lambda uid: u)
    result = await get_current_user(_fake_request(), authorization=None)
    assert result is u


@pytest.mark.asyncio
async def test_mock_mode_raises_401_when_no_user(monkeypatch):
    from app import store

    monkeypatch.setattr("app.dependencies.settings.KORA_DATA_BACKEND", "mock")
    monkeypatch.setattr(store, "get_user", lambda uid: None)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_fake_request(), authorization=None)
    assert exc.value.status_code == 401


# ── get_current_user — supabase mode ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_supabase_mode_valid_token(monkeypatch):
    from app import store

    monkeypatch.setattr("app.dependencies.settings.KORA_DATA_BACKEND", "supabase")
    u = _user()
    monkeypatch.setattr(store, "verify_token", lambda t: u)
    result = await get_current_user(_fake_request(), authorization="Bearer real-token")
    assert result is u


@pytest.mark.asyncio
async def test_supabase_mode_invalid_token_raises_401(monkeypatch):
    from app import store

    monkeypatch.setattr("app.dependencies.settings.KORA_DATA_BACKEND", "supabase")
    monkeypatch.setattr(store, "verify_token", lambda t: None)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_fake_request(), authorization="Bearer bad-token")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_supabase_demo_bridge_allowed(monkeypatch):
    from app import store

    monkeypatch.setattr("app.dependencies.settings.KORA_DATA_BACKEND", "supabase")
    monkeypatch.setattr("app.dependencies.settings.ALLOW_DEMO_USER", True)
    # Pinned: the bridge is development-only, so this must not depend on whatever
    # ENVIRONMENT the local .env happens to carry.
    monkeypatch.setattr("app.dependencies.settings.ENVIRONMENT", "development")
    u = _user()
    monkeypatch.setattr(store, "get_user_by_email", lambda email: u)
    result = await get_current_user(_fake_request(), authorization=None)
    assert result is u


@pytest.mark.asyncio
async def test_supabase_demo_bridge_disabled_raises_401(monkeypatch):
    monkeypatch.setattr("app.dependencies.settings.KORA_DATA_BACKEND", "supabase")
    monkeypatch.setattr("app.dependencies.settings.ALLOW_DEMO_USER", False)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_fake_request(), authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_supabase_demo_bridge_user_not_found_raises_401(monkeypatch):
    from app import store

    monkeypatch.setattr("app.dependencies.settings.KORA_DATA_BACKEND", "supabase")
    monkeypatch.setattr("app.dependencies.settings.ALLOW_DEMO_USER", True)
    monkeypatch.setattr("app.dependencies.settings.ENVIRONMENT", "development")
    monkeypatch.setattr(store, "get_user_by_email", lambda email: None)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(_fake_request(), authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["production", "staging"])
async def test_demo_bridge_never_applies_in_deployed_environments(monkeypatch, environment):
    """ALLOW_DEMO_USER must not be honourable in a deployed environment.

    Regression guard for the staging UAT finding: the flag defaults to True, so a
    deploy that forgot to set ALLOW_DEMO_USER=false served the seeded demo user's
    real invoices, clients and transactions to any anonymous caller on the public
    internet. Config alone is not enough — the code has to fail closed even when
    the flag is left on.
    """
    from app import store

    monkeypatch.setattr("app.dependencies.settings.KORA_DATA_BACKEND", "supabase")
    monkeypatch.setattr("app.dependencies.settings.ALLOW_DEMO_USER", True)
    monkeypatch.setattr("app.dependencies.settings.ENVIRONMENT", environment)
    # The seeded demo user exists and is resolvable — the only thing standing
    # between an anonymous request and their data is the environment check.
    monkeypatch.setattr(store, "get_user_by_email", lambda email: _user())

    with pytest.raises(HTTPException) as exc:
        await get_current_user(_fake_request(), authorization=None)
    assert exc.value.status_code == 401


# ── require_plan ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_plan_allows_sufficient_plan(monkeypatch):
    from app import store

    monkeypatch.setattr("app.dependencies.settings.KORA_DATA_BACKEND", "mock")
    u = _user(plan="pro")
    monkeypatch.setattr(store, "get_user", lambda uid: u)
    dep = require_plan("starter")
    result = await dep(user=u)
    assert result is u


@pytest.mark.asyncio
async def test_require_plan_blocks_insufficient_plan(monkeypatch):
    u = _user(plan="free")
    dep = require_plan("starter")
    with pytest.raises(HTTPException) as exc:
        await dep(user=u)
    assert exc.value.status_code == 403
    assert "starter" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_require_plan_exact_match_allowed():
    u = _user(plan="starter")
    dep = require_plan("starter")
    result = await dep(user=u)
    assert result is u


# ── verify_cron_secret ───────────────────────────────────────────────────────


def test_cron_secret_matches(monkeypatch):
    monkeypatch.setattr("app.dependencies.settings.CRON_SECRET", "s3cr3t")
    assert verify_cron_secret("s3cr3t") is True


def test_cron_secret_mismatch(monkeypatch):
    monkeypatch.setattr("app.dependencies.settings.CRON_SECRET", "s3cr3t")
    assert verify_cron_secret("wrong") is False


def test_cron_secret_missing():
    assert verify_cron_secret(None) is False
