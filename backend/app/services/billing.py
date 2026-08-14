"""Plan lookup for billing.

This module once also held PLAN_LIMITS — a second, hand-maintained table of
what each tier unlocked. Nothing ever called the helpers that read it, so it
silently disagreed with app/entitlements.POLICY (the real gate) and with the
published pricing page, which had copied from it. Two tables describing the
same thing, one of them enforced. Entitlements now live in exactly one place;
this module only answers which plan a user is on.
"""

from __future__ import annotations

from .. import store

PLAN_RANK = {"free": 0, "starter": 1, "pro": 2}


def get_user_plan(user_id: str) -> str:
    user = store.get_user(user_id)
    if not user:
        return "free"
    return getattr(user, "plan", None) or "free"


def require_plan(user_id: str, min_plan: str) -> dict:
    current = get_user_plan(user_id)
    return {
        "allowed": PLAN_RANK.get(current, 0) >= PLAN_RANK.get(min_plan, 0),
        "current_plan": current,
        "required_plan": min_plan,
    }
