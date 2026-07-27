"""Plan gating is real and auditable (M5).

Before M5 the paywall was UI-only — a `free` user could hit every premium
endpoint. These pin that the gate is now enforced server-side from ONE policy
table, and — the load-bearing one — that the policy and the routes can't drift:
a premium route added without a gate, or a gate without a policy entry, fails
`test_every_gated_route_is_in_policy_and_vice_versa`.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import entitlements as E
from app.dependencies import get_current_user
from app.main import app
from app.models import User

client = TestClient(app)


def _all_api_routes():
    """Iterate every APIRoute registered on the app.

    `app.routes` only surfaces the `_IncludedRouter` wrappers added by
    `include_router(...)`, not the inner APIRoute objects. Inspecting those
    wrappers for `dependant` / `path` returns nothing, which silently neutralises
    the policy-vs-routes drift test. Walk through `original_router.routes` to
    reach the real route objects.
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        inner = getattr(route, "original_router", None)
        if inner is not None and hasattr(inner, "routes"):
            for sub in inner.routes:
                if isinstance(sub, APIRoute):
                    yield sub


def _user(plan: str) -> User:
    return User(id="u-1", email="u@example.com", plan=plan,
                created_at=datetime.now(timezone.utc).isoformat())


def _override(plan: str):
    app.dependency_overrides[get_current_user] = lambda: _user(plan)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _call(method: str, path: str):
    # Fill any path param; the gate runs before the handler so the value is moot.
    path = path.replace("{contract_id}", "test-id")
    return client.request(method, path, json={})


# ── Criterion 1 · a free user is refused every premium route ────────────────

@pytest.mark.parametrize("route", sorted(E.POLICY), ids=lambda r: f"{r[0]} {r[1]}")
def test_free_user_is_403_on_every_premium_route(route):
    _override("free")
    method, path = route
    r = _call(method, path)
    assert r.status_code == 403, f"{method} {path} let a free user through ({r.status_code})"
    assert "upgrade" in r.json()["detail"].lower()


# ── Criterion 2 · a sufficiently-planned user is NOT gated ──────────────────

@pytest.mark.parametrize("route", sorted(E.POLICY), ids=lambda r: f"{r[0]} {r[1]}")
def test_pro_user_is_not_gated(route):
    """`pro` outranks every tier, so it must never see a 403 from the gate.

    A non-403 (even a 422 for an empty body) proves the request cleared the gate
    and reached handler/body validation."""
    _override("pro")
    method, path = route
    r = _call(method, path)
    assert r.status_code != 403, f"{method} {path} wrongly gated a pro user"


def test_starter_clears_starter_gates_but_not_pro_gates():
    _override("starter")
    # A starter-tier route: allowed.
    assert _call("POST", "/api/memory/recall").status_code != 403
    # A pro-tier route: still gated.
    assert _call("POST", "/api/contracts/generate").status_code == 403


# ── Criterion 3 · policy and routes cannot drift (the load-bearing test) ────

def _gated_routes() -> set[tuple[str, str]]:
    """Every (method, path) whose route carries the enforce_plan dependency."""
    found: set[tuple[str, str]] = set()
    for route in _all_api_routes():
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        calls = {d.call for d in dependant.dependencies}
        if E.enforce_plan in calls:
            for m in (getattr(route, "methods", None) or []):
                found.add((m, route.path))
    return found


def test_every_gated_route_is_in_policy_and_vice_versa():
    gated = _gated_routes()
    policy = set(E.POLICY)

    # A route gated without a policy entry would 500 at request time (enforce_plan
    # raises). A policy entry whose route isn't gated is dead config.
    assert gated - policy == set(), f"gated but not in POLICY: {gated - policy}"
    assert policy - gated == set(), f"in POLICY but not actually gated: {policy - gated}"


def test_every_policy_route_actually_exists():
    registered = {(m, r.path) for r in _all_api_routes()
                  for m in (getattr(r, "methods", None) or [])}
    missing = set(E.POLICY) - registered
    assert missing == set(), f"POLICY references non-existent routes: {missing}"


# ── The policy helpers ──────────────────────────────────────────────────────

def test_allows_respects_rank():
    assert E.allows("pro", "POST", "/api/contracts/generate") is True
    assert E.allows("free", "POST", "/api/contracts/generate") is False
    assert E.allows("starter", "POST", "/api/memory/recall") is True
    assert E.allows("free", "POST", "/api/memory/recall") is False
    # A non-premium route is allowed for everyone, including free.
    assert E.allows("free", "GET", "/api/clients") is True


def test_unknown_plan_ranks_as_free():
    assert E.rank(None) == 0 and E.rank("nonsense") == 0
