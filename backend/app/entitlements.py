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
