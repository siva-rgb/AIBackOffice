"""The shared demo tenant must not be erasable by whoever is signed into it.

Right-to-erasure assumes the caller owns what they destroy. That holds for a
real tenant and breaks for the published demo account: every evaluator signs in
with the same printed credentials, so one "delete my account" click revokes the
owner's Google grant, wipes the seeded clients/invoices/meetings, and deletes
the auth identity behind the login itself — for everyone who arrives later.

The guard refuses (409) instead of faking success. A `deleted: true` that
deleted nothing is the exact dishonesty `_delete_payload` exists to avoid, and
a judge reading the response would be told a falsehood.

Every assertion below is written so it fails if the guard is scoped too widely
(a real tenant losing its right to erasure) as well as too narrowly.
"""

from __future__ import annotations

import pytest

from app.routers import account


DEMO = "11111111-1111-1111-1111-111111111111"
REAL = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def protect(monkeypatch):
    """Set PROTECTED_TENANT_IDS for the duration of a test."""

    def _set(value: str):
        monkeypatch.setattr(account.settings, "PROTECTED_TENANT_IDS", value)

    return _set


class TestMatching:
    def test_the_configured_tenant_is_protected(self, protect):
        protect(DEMO)
        assert account._is_protected_tenant(DEMO) is True

    def test_a_real_tenant_is_not(self, protect):
        protect(DEMO)
        assert account._is_protected_tenant(REAL) is False

    def test_empty_config_protects_nobody(self, protect):
        """The default. Self-service deletion must work everywhere by default."""
        protect("")
        assert account._is_protected_tenant(DEMO) is False

    def test_multiple_ids_are_supported(self, protect):
        protect(f"{DEMO},{REAL}")
        assert account._is_protected_tenant(DEMO) is True
        assert account._is_protected_tenant(REAL) is True

    def test_whitespace_and_blanks_are_tolerated(self, protect):
        """Hand-edited env vars pick up spaces and trailing commas."""
        protect(f"  {DEMO} , , {REAL}  ")
        assert account._is_protected_tenant(DEMO) is True
        assert account._is_protected_tenant(REAL) is True

    def test_an_empty_user_id_is_never_protected(self, protect):
        """A blank id must not match the blank entries a sloppy config leaves."""
        protect(f"{DEMO},,")
        assert account._is_protected_tenant("") is False

    def test_matching_is_exact_not_substring(self, protect):
        """A prefix of a protected id is a different tenant and stays deletable."""
        protect(DEMO)
        assert account._is_protected_tenant(DEMO[:-1]) is False
        assert account._is_protected_tenant(DEMO + "x") is False


class TestEndpoint:
    """The guard must actually block the route, not merely compute a boolean."""

    @staticmethod
    def _user(user_id):
        from app.models import User

        return User(id=user_id, email="demo@kora.app", full_name="Demo", created_at="2026-01-01T00:00:00+00:00")

    @pytest.mark.asyncio
    async def test_protected_tenant_is_refused_and_nothing_is_deleted(self, protect, monkeypatch):
        from fastapi import HTTPException

        protect(DEMO)
        called = []
        monkeypatch.setattr(account, "_delete_payload", lambda *a, **k: called.append(1))

        with pytest.raises(HTTPException) as excinfo:
            await account.delete_account(self._user(DEMO))

        assert excinfo.value.status_code == 409
        assert not called, "the deletion pipeline must never be entered"

    @pytest.mark.asyncio
    async def test_the_refusal_explains_itself(self, protect):
        """A judge hitting this should understand why, and what still works."""
        from fastapi import HTTPException

        protect(DEMO)
        with pytest.raises(HTTPException) as excinfo:
            await account.delete_account(self._user(DEMO))

        detail = str(excinfo.value.detail).lower()
        assert "shared" in detail
        assert "nothing was deleted" in detail
        assert "export" in detail, "the working alternative should be named"

    @pytest.mark.asyncio
    async def test_a_real_tenant_still_reaches_deletion(self, protect, monkeypatch):
        """The regression that would matter most: breaking GDPR for real users."""
        protect(DEMO)

        async def fake_delete(user):
            return {"deleted": True, "user_request_id": "req-1"}

        monkeypatch.setattr(account, "_delete_payload", fake_delete)
        result = await account.delete_account(self._user(REAL))
        assert result["deleted"] is True

    @pytest.mark.asyncio
    async def test_deletion_is_unaffected_when_the_guard_is_unconfigured(self, protect, monkeypatch):
        protect("")

        async def fake_delete(user):
            return {"deleted": True, "user_request_id": "req-2"}

        monkeypatch.setattr(account, "_delete_payload", fake_delete)
        result = await account.delete_account(self._user(DEMO))
        assert result["deleted"] is True
