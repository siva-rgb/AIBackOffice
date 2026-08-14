"""Plan entitlements — the ONE place premium gating is decided (M5).

Before this, `require_plan` existed but was wired to zero routes: the paywall
was UI-only, so a `free` user could hit every premium endpoint. This makes the
gate real and, crucially, *auditable from one table*.

`POLICY` maps `(METHOD, path-template)` → the minimum plan that unlocks it. The
`enforce_plan` dependency reads its OWN route off the request and looks the pair
up here — so the route just carries `dependencies=[Depends(enforce_plan)]` and
`POLICY` stays the single source of truth (no per-route min-plan to drift).

Two failure modes are made loud rather than silent, and both are pinned by
`test_plan_gating.py`:
  * a route gated but absent from `POLICY` → `enforce_plan` raises (mis-config),
  * a `POLICY` entry whose route isn't actually gated → the coverage test fails.
So adding a premium route without gating it, or gating one without a policy
entry, breaks the suite.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from .dependencies import get_current_user
from .models import User

FREE, STARTER, PRO = "free", "starter", "pro"
_RANK = {"free": 0, "starter": 1, "pro": 2}

# (HTTP method, route path template) → minimum plan. Premium = compute/LLM-heavy
# or money/legal generation; plain reads stay free.
# Only USER-facing premium routes appear here. Dual-purpose cron endpoints
# (butler `/run`, memory `/reindex`, graph `/run`) are deliberately NOT gated:
# `enforce_plan` runs `get_current_user`, which would force auth on the
# scheduler path — a mock-vs-prod trap. Their user-facing premium value is
# reachable through the gated routes below.
POLICY: dict[tuple[str, str], str] = {
    # Legal document generation + review — the most expensive, highest-value.
    ("POST", "/api/contracts/generate"): PRO,
    ("POST", "/api/contracts/review"): PRO,
    ("POST", "/api/contracts/review/upload"): PRO,
    ("POST", "/api/contracts/{contract_id}/review"): PRO,
    # Cash-flow forecast — the numeric projection is cheap, the AI insight isn't.
    ("GET", "/api/cashflow/forecast"): STARTER,
    # Semantic memory recall — embedding + hybrid search.
    ("POST", "/api/memory/recall"): STARTER,
    # Relationship graph rebuild (user-triggered; the cron `/run` is separate).
    ("POST", "/api/graph/sync"): STARTER,
}


# ── What the pricing page is allowed to claim ───────────────────────────────
# The published plan comparison used to be hand-written in the frontend, and it
# disagreed with this file in both directions: it sold "Morning briefing",
# "Invoice follow-up agent" and a "20 transactions/month" cap that nothing
# enforces, while listing the cash-flow forecast as Pro when POLICY unlocks it
# at Starter. A pricing page a user can disprove in a minute is worse than no
# pricing page.
#
# So the paid bullets are DERIVED from POLICY. Every key here must exist in
# POLICY and vice versa — `test_plan_catalogue.py` fails otherwise, which means
# gating a new route without describing it (or describing one that isn't gated)
# breaks the build rather than shipping a false claim.
#
# Several routes deliberately share a label: the four contract routes are one
# capability to a buyer, not four. Duplicate labels collapse when the payload is
# built, preserving first-seen order.
FEATURE_LABELS: dict[tuple[str, str], str] = {
    ("POST", "/api/contracts/generate"): "Contract drafting & AI risk review",
    ("POST", "/api/contracts/review"): "Contract drafting & AI risk review",
    ("POST", "/api/contracts/review/upload"): "Contract drafting & AI risk review",
    ("POST", "/api/contracts/{contract_id}/review"): "Contract drafting & AI risk review",
    ("GET", "/api/cashflow/forecast"): "Cash-flow forecast with AI insight",
    ("POST", "/api/memory/recall"): "Semantic search across your whole business",
    ("POST", "/api/graph/sync"): "Client relationship graph",
}

# What every account gets without paying. This cannot be derived: gating is
# allow-by-default, so "free" is everything absent from POLICY — an open-ended
# set no table can enumerate. These strings are therefore a curated summary, and
# each one is a claim about an UNGATED route. Adding any of these capabilities to
# POLICY later without moving its bullet would make this list false, which is the
# mistake being corrected here.
FREE_FEATURES: tuple[str, ...] = (
    "Unlimited transactions & bookkeeping",
    "Invoicing, clients and contract storage",
    "Butler morning briefing & quick capture",
    "Invoice follow-up agent",
    "Gmail, Drive, Calendar and Notion connections",
)

# Prices are shown to buyers, so they live in exactly one place rather than being
# retyped in the UI. Verified against the Stripe API on 2026-08-14: starter
# $29.00/month, pro $49.00/month, both active recurring prices. Changing a price
# in Stripe means changing it here too — nothing enforces the pair at runtime,
# because the amount actually charged comes from the Stripe price id, not this
# string.
_TIERS: tuple[tuple[str, str, str, str, str], ...] = (
    # id, display name, price, period, one-line positioning
    (FREE, "Free", "$0", "forever", "Run your books and get paid."),
    (STARTER, "Starter", "$29", "/month", "Add the agents that watch your numbers."),
    (PRO, "Pro", "$49", "/month", "Everything, including legal drafting."),
)


def plan_features(plan: str) -> list[str]:
    """Bullets unlocked AT this tier, in POLICY order, de-duplicated by label."""
    out: list[str] = []
    for route, need in POLICY.items():
        if need != plan:
            continue
        label = FEATURE_LABELS.get(route)
        if label and label not in out:
            out.append(label)
    return out


def plans_payload(price_ids: dict[str, str] | None = None) -> list[dict]:
    """The published plan comparison, built from the enforcement table.

    Each paid tier lists what IT adds, plus an explicit "Everything in <lower>"
    line — the same shape the hand-written page used, so the visual design is
    unchanged while the content becomes accountable to POLICY.
    """
    price_ids = price_ids or {}
    plans: list[dict] = []
    previous: str | None = None
    for plan_id, name, price, period, tagline in _TIERS:
        features = list(FREE_FEATURES) if plan_id == FREE else []
        if previous:
            features.append(f"Everything in {previous}")
        features.extend(plan_features(plan_id))
        plans.append(
            {
                "id": plan_id,
                "name": name,
                "price": price,
                "period": period,
                "tagline": tagline,
                "features": features,
                "priceId": price_ids.get(plan_id) or None,
                "popular": plan_id == STARTER,
            }
        )
        previous = name
    return plans


def grant_signup_plan(user_id: str, current_plan: str | None) -> str | None:
    """Apply SIGNUP_PLAN to a new account, returning the plan set (or None).

    Only ever moves a plan UP, and only from the free tier. An account that has
    paid, or that an operator has already promoted, must not be rewritten by a
    deployment flag — and re-running onboarding must not silently re-grant a tier
    someone downgraded from.
    """
    from .config import settings  # local: config imports nothing from here

    wanted = (settings.SIGNUP_PLAN or "").strip().lower()
    if wanted not in _RANK or wanted == FREE:
        return None
    if rank(current_plan) >= _RANK[wanted]:
        return None

    from . import store

    try:
        store.update_user(user_id, {"plan": wanted})
    except Exception as exc:  # pragma: no cover - depends on live schema
        # A failed grant must not block onboarding; the user simply stays free.
        print(f"[signup-plan] could not grant {wanted} to {user_id} ({type(exc).__name__}: {str(exc)[:100]})")
        return None
    return wanted


def rank(plan: str | None) -> int:
    return _RANK.get(plan or "free", 0)


def min_plan_for(method: str, path: str) -> str | None:
    return POLICY.get((method.upper(), path))


def allows(plan: str | None, method: str, path: str) -> bool:
    """True when `plan` may access this route (or the route isn't premium)."""
    need = min_plan_for(method, path)
    return need is None or rank(plan) >= _RANK[need]


async def enforce_plan(request: Request, user: User = Depends(get_current_user)) -> User:
    """Side-effect dependency: 403 unless the user's plan meets this route's policy.

    Reads its own route template off the request, so one dependency gates every
    premium route straight from `POLICY`. A gated route missing from `POLICY` is a
    configuration error and is raised loudly (500) rather than silently allowed.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    need = min_plan_for(request.method, path)
    if need is None:
        raise RuntimeError(f"enforce_plan is attached to {request.method} {path} but it has no " f"POLICY entry — add one to app/entitlements.POLICY.")
    if rank(user.plan) < _RANK[need]:
        raise HTTPException(
            status_code=403,
            detail=f"Upgrade to {need} to use this feature.",
        )
    return user
