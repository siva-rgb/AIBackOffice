"""The verified-token cache must save round trips without weakening auth.

`store.verify_token()` costs two sequential network calls and runs before every
authenticated request — ~1.3s of the measured response time on the deployed
backend. Caching it is a latency fix sitting directly on the auth path, so the
security properties matter more than the speed-up:

  - a rejected token must never be cached, or a single failure could be replayed;
  - one tenant's cached session must never resolve another tenant's token;
  - entries must expire, so a revoked session cannot live indefinitely;
  - the cache must stay bounded, so tokens cannot grow memory without limit.
"""

from __future__ import annotations

import pytest

from app import dependencies as deps


class FakeRequest:
    def __init__(self):
        self.state = type("S", (), {})()


def _user(uid="u1", email="a@b.c", plan="pro"):
    from app.models import User

    return User(id=uid, email=email, full_name="T", plan=plan, created_at="2026-01-01T00:00:00+00:00")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    deps.clear_token_cache()
    monkeypatch.setattr(deps.settings, "KORA_DATA_BACKEND", "supabase")
    monkeypatch.setattr(deps.settings, "ENVIRONMENT", "production")
    yield
    deps.clear_token_cache()


@pytest.fixture
def verifier(monkeypatch):
    """Counts calls to the real verification path."""
    calls = {"n": 0}
    table = {"tok-a": _user("u1"), "tok-b": _user("u2", "b@b.c")}

    def verify(token):
        calls["n"] += 1
        return table.get(token)

    monkeypatch.setattr(deps.store, "verify_token", verify)
    return calls


async def _call(token):
    return await deps.get_current_user(FakeRequest(), authorization=f"Bearer {token}")


class TestItActuallyCaches:
    @pytest.mark.asyncio
    async def test_repeat_requests_skip_the_round_trip(self, verifier):
        for _ in range(5):
            user = await _call("tok-a")
            assert user.id == "u1"
        assert verifier["n"] == 1, "only the first request should reach Supabase"

    @pytest.mark.asyncio
    async def test_expiry_forces_reverification(self, verifier, monkeypatch):
        await _call("tok-a")
        monkeypatch.setattr(deps, "_TOKEN_CACHE_TTL", -1.0)
        deps.clear_token_cache()
        await _call("tok-a")
        assert verifier["n"] == 2


class TestItDoesNotWeakenAuth:
    @pytest.mark.asyncio
    async def test_a_rejected_token_is_never_cached(self, verifier):
        """A failure must be re-checked every time, not remembered."""
        for _ in range(3):
            with pytest.raises(Exception):
                await _call("bogus")
        assert verifier["n"] == 3

    @pytest.mark.asyncio
    async def test_tokens_do_not_cross_tenants(self, verifier):
        """The cache is keyed by token, so B's token must never return A."""
        assert (await _call("tok-a")).id == "u1"
        assert (await _call("tok-b")).id == "u2"
        assert (await _call("tok-a")).id == "u1"
        assert verifier["n"] == 2

    @pytest.mark.asyncio
    async def test_an_expired_entry_is_not_served(self, verifier, monkeypatch):
        await _call("tok-a")
        key = deps._token_key("tok-a")
        expires, user = deps._token_cache[key]
        deps._token_cache[key] = (expires - 10_000, user)  # force staleness
        assert deps._cached_user("tok-a") is None

    def test_raw_tokens_are_not_held_in_the_cache(self):
        """Keys are hashed, so the structure holds no usable credential."""
        deps._cache_user("super-secret-token", _user())
        assert "super-secret-token" not in deps._token_cache
        assert all(len(k) == 64 for k in deps._token_cache)


class TestBounded:
    def test_the_cache_does_not_grow_without_limit(self):
        for i in range(deps._TOKEN_CACHE_MAX + 50):
            deps._cache_user(f"tok-{i}", _user(f"u{i}"))
        assert len(deps._token_cache) <= deps._TOKEN_CACHE_MAX

    def test_expired_entries_are_reclaimed_before_clearing(self, monkeypatch):
        monkeypatch.setattr(deps, "_TOKEN_CACHE_TTL", -1.0)
        for i in range(deps._TOKEN_CACHE_MAX):
            deps._cache_user(f"old-{i}", _user())
        monkeypatch.setattr(deps, "_TOKEN_CACHE_TTL", 30.0)
        deps._cache_user("fresh", _user("fresh-user"))
        assert deps._cached_user("fresh") is not None
