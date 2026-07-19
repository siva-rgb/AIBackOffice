from __future__ import annotations

from datetime import datetime, timezone

from .. import store

PLAN_RANK = {"free": 0, "starter": 1, "pro": 2}

PLAN_LIMITS = {
    "free": {
        "transactions_per_month": 20,
        "contracts_per_month": 1,
        "invoice_followups": False,
        "cashflow_forecast": False,
        "butler_full": False,
        "morning_briefing": False,
        "proposals": False,
    },
    "starter": {
        "transactions_per_month": None,
        "contracts_per_month": None,
        "invoice_followups": True,
        "cashflow_forecast": False,
        "butler_full": False,
        "morning_briefing": True,
        "proposals": False,
    },
    "pro": {
        "transactions_per_month": None,
        "contracts_per_month": None,
        "invoice_followups": True,
        "cashflow_forecast": True,
        "butler_full": True,
        "morning_briefing": True,
        "proposals": True,
    },
}


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


def check_feature(user_id: str, feature: str) -> bool:
    plan = get_user_plan(user_id)
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    return bool(limits.get(feature, False))


def check_transaction_limit(user_id: str) -> dict:
    plan = get_user_plan(user_id)
    limit = PLAN_LIMITS[plan]["transactions_per_month"]
    if limit is None:
        return {"allowed": True, "limit": None, "used": 0, "remaining": None}

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    transactions = store.list_transactions(user_id)
    used = sum(1 for t in transactions if getattr(t, "created_at", "") >= month_start)

    return {
        "allowed": used < limit,
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
    }
