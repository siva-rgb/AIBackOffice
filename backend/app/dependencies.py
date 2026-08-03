from __future__ import annotations

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
            user = store.verify_token(token)
            if user:
                _stamp(request, user)
                return user
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        # Demo bridge (until the frontend login is wired) — resolves the seeded
        # demo user. Disable with ALLOW_DEMO_USER=false to require real auth.
        if settings.ALLOW_DEMO_USER:
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
