from __future__ import annotations

import hashlib
import time

from fastapi import Depends, Header, HTTPException, Request

from .config import settings
from .models import User
from .seed import DEMO_USER_ID
from . import store
from .utils.request_context import set_user_id

# Auth + plan-gate dependencies (SKILL.md §16 Rules 2 & 7).
#
# In mock mode every request resolves to the seeded demo user. The real
# implementation verifies the forwarded Supabase JWT with auth.getUser()
# (a network call — never trust getSession) and returns that user. The route
# signatures don't change when you swap the body of get_current_user().

_PLAN_RANK = {"free": 0, "starter": 1, "pro": 2}

# ── Verified-token cache ────────────────────────────────────────────────────
# store.verify_token() costs TWO sequential network round trips — auth.get_user()
# against Supabase, then the profile row — and it runs before EVERY authenticated
# request. Measured against the deployed backend that was ~1.3s of the response
# time on endpoints that do almost no work, and a dashboard render fires several
# requests at once, each paying it again.
#
# The trade this buys: a session that is revoked, or a plan that changes, stays
# in effect for up to TTL seconds on instances that already cached it. That is
# why the window is deliberately small — long enough to cover one page's burst
# of parallel calls and a navigation or two, short enough that a revoked token
# is not meaningfully useful. Anything longer would be trading real auth
# freshness for diminishing latency returns.
#
# Per-process and non-authoritative: it is a latency cache, never a source of
# truth, and losing it costs only speed. Tokens are keyed by hash so raw
# credentials are not held in a long-lived structure.
_TOKEN_CACHE_TTL = 30.0
_TOKEN_CACHE_MAX = 512
_token_cache: dict[str, tuple[float, User]] = {}


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cached_user(token: str) -> User | None:
    entry = _token_cache.get(_token_key(token))
    if not entry:
        return None
    expires_at, user = entry
    if expires_at <= time.monotonic():
        _token_cache.pop(_token_key(token), None)
        return None
    return user


def _cache_user(token: str, user: User) -> None:
    """Only successful verifications are cached — a rejected token must hit
    Supabase every time, so a token cannot be denied once and then pass later
    (or vice versa) from stale state."""
    now = time.monotonic()
    if len(_token_cache) >= _TOKEN_CACHE_MAX:
        for key in [k for k, (exp, _) in _token_cache.items() if exp <= now]:
            _token_cache.pop(key, None)
        if len(_token_cache) >= _TOKEN_CACHE_MAX:
            _token_cache.clear()  # bounded memory beats clever eviction here
    _token_cache[_token_key(token)] = (now + _TOKEN_CACHE_TTL, user)


def clear_token_cache() -> None:
    """Drop every cached verification. Used by tests, and available to any code
    that needs an immediate re-check rather than waiting out the TTL."""
    _token_cache.clear()


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> User:
    if settings.KORA_DATA_BACKEND == "supabase":
        token = _bearer(authorization)
        # Real auth: verify the Supabase access token and load the profile.
        if token and token != "demo":
            user = _cached_user(token)
            if user is None:
                user = store.verify_token(token)
                if user:
                    _cache_user(token, user)
            if user:
                _stamp(request, user)
                return user
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        # Demo bridge (until the frontend login is wired) — resolves the seeded
        # demo user. Disable with ALLOW_DEMO_USER=false to require real auth.
        #
        # Deployed environments ignore the flag entirely. It defaults to True, so
        # honouring it outside development means every /api/* route serves the
        # seeded user's real data to any anonymous caller on the internet — which
        # is exactly what the staging smoke gate caught. A deploy that forgets to
        # set ALLOW_DEMO_USER=false must fail closed, not leak.
        if settings.ALLOW_DEMO_USER and settings.ENVIRONMENT not in ("production", "staging"):
            user = store.get_user_by_email(settings.DEMO_EMAIL)
            if user:
                _stamp(request, user)
                return user
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Mock mode: always the seeded demo user.
    user = store.get_user(DEMO_USER_ID)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    _stamp(request, user)
    return user


def _stamp(request: Request, user: User) -> None:
    """M11.2 — mirror user_id onto both the ContextVar and `request.state`.

    The contextvar is the fast-path used by services in the same task; the
    `request.state` mirror survives Starlette's BaseHTTPMiddleware context
    boundary (the well-known ContextVar-not-propagated-across-tasks quirk).
    """
    set_user_id(user.id)
    request.state.user_id = user.id


def require_plan(min_plan: str):
    """Dependency factory that enforces a minimum plan, read server-side."""

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if _PLAN_RANK.get(user.plan, 0) < _PLAN_RANK.get(min_plan, 0):
            raise HTTPException(status_code=403, detail=f"Upgrade to {min_plan} required")
        return user

    return _dep


def verify_cron_secret(x_cron_secret: str | None = Header(default=None)) -> bool:
    """True when a valid scheduler secret is present (SKILL.md §16 Rule 8)."""
    return bool(x_cron_secret) and x_cron_secret == settings.CRON_SECRET


# ── Which tenant the scheduler acts for ─────────────────────────────────────
# Cron requests carry a shared secret, not a session, so there is no user on the
# request to act as. Nine routers each grew their own copy of this lookup, and
# every copy carried the same fault: when the lookup missed it fell back to the
# literal string DEMO_USER_ID ("demo-user"). That is a valid id in mock mode and
# a *syntactically invalid UUID* against Postgres, so the miss surfaced as
# `22P02 invalid input syntax for type uuid` — a 500 with a traceback, three
# frames below the real problem, on every scheduled run of every agent.
#
# The miss was not hypothetical: the demo tenant's row was later repointed to a
# different email, and DEMO_EMAIL was never moved with it. A lookup keyed on a
# mutable field is the wrong anchor for something ops depends on, so
# SCHEDULER_USER_ID pins the tenant by id and takes precedence.
#
# Returning None on a miss is the point. The scheduler asking for a tenant that
# does not exist is a configuration error, and it should say so plainly rather
# than hand a bad id to the database and let it fail as a 500.
def scheduler_user_id() -> str | None:
    """The tenant scheduled runs act for, or None when none is configured."""
    if settings.SCHEDULER_USER_ID:
        return settings.SCHEDULER_USER_ID
    if settings.KORA_DATA_BACKEND == "supabase":
        user = store.get_user_by_email(settings.DEMO_EMAIL)
        return user.id if user else None
    return DEMO_USER_ID


def require_scheduler_user_id() -> str:
    """As above, but fails with an actionable 503 instead of a database error."""
    user_id = scheduler_user_id()
    if not user_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "No scheduler tenant is configured. Set SCHEDULER_USER_ID to the "
                f"tenant's id, or point DEMO_EMAIL (currently {settings.DEMO_EMAIL!r}) "
                "at a user that exists."
            ),
        )
    return user_id
