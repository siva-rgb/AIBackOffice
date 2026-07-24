"""Notion connector — tenant isolation, auth-mode, and read-only page parsing.

Everything here is offline: only the pure helpers, auth-mode resolution and
selection persistence are exercised. No `_request` call is made, so no network
is touched. Since M9 the connector is READ-ONLY — there are no write/mapping
helpers left to test.
"""
from __future__ import annotations

from app.services import notion_connector as N


# ── Tenant isolation — the highest-severity property in the repo ────────────

def test_multi_tenant_never_falls_back_to_the_shared_key(monkeypatch, settings, user_id):
    """A user without their own token must get NO token once OAuth is configured.

    Regression for a real cross-tenant leak: `_token()` used to fall back to the
    server-level NOTION_API_KEY, which would read one user's memory against the
    *owner's* Notion workspace.
    """
    monkeypatch.setattr(settings, "NOTION_API_KEY", "ntn_owner_secret")
    monkeypatch.setattr(settings, "NOTION_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "NOTION_OAUTH_CLIENT_SECRET", "client-secret")

    assert N.is_multi_tenant() is True
    assert N._token(user_id) is None, (
        "cross-tenant leak: an unconnected user resolved to the owner's shared key"
    )


def test_single_tenant_still_uses_the_shared_key(monkeypatch, settings, user_id):
    """The fallback is intentional when there is only one tenant — keep it working."""
    monkeypatch.setattr(settings, "NOTION_API_KEY", "ntn_owner_secret")
    monkeypatch.setattr(settings, "NOTION_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(settings, "NOTION_OAUTH_CLIENT_SECRET", "")

    assert N.is_multi_tenant() is False
    assert N._token(user_id) == "ntn_owner_secret"


def test_status_does_not_claim_api_key_mode_when_it_is_inert(monkeypatch, settings, user_id):
    """`authMode` must report the mode actually in force, not a key it ignores."""
    monkeypatch.setattr(settings, "NOTION_API_KEY", "ntn_owner_secret")
    monkeypatch.setattr(settings, "NOTION_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "NOTION_OAUTH_CLIENT_SECRET", "client-secret")

    status = N.status(user_id)
    assert status["authMode"] is None
    assert status["connected"] is False
    assert status["oauthConfigured"] is True


def test_status_reports_the_ingest_selection(monkeypatch, settings, user_id):
    """Single-tenant (shared key) so the user is 'connected'; selection round-trips."""
    monkeypatch.setattr(settings, "NOTION_API_KEY", "ntn_owner_secret")
    monkeypatch.setattr(settings, "NOTION_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(settings, "NOTION_OAUTH_CLIENT_SECRET", "")

    N.set_ingest_pages(user_id, ["page-a", "page-b", ""])   # blank dropped
    status = N.status(user_id)
    assert status["connected"] is True
    assert status["selectedPageCount"] == 2
    assert status["selectedPageIds"] == ["page-a", "page-b"]


# ── Graceful degradation — never raise when unconfigured ───────────────────

def test_read_page_text_degrades_without_a_connection(user_id):
    out = N.read_page_text(user_id, "page-1")
    assert out["ok"] is False
    assert "not connected" in out["error"].lower()


def test_list_parent_pages_degrades_without_a_connection(user_id):
    out = N.list_parent_pages(user_id)
    assert out["ok"] is False
    assert out["pages"] == []


# ── Read-only block parsing (pure, no network) ──────────────────────────────

def test_block_text_extracts_prose_from_common_blocks():
    para = {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello world"}]}}
    assert N._block_text(para) == "Hello world"

    heading = {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Roadmap"}]}}
    assert N._block_text(heading) == "Roadmap"

    todo = {"type": "to_do", "to_do": {"checked": True, "rich_text": [{"plain_text": "Ship v2"}]}}
    assert N._block_text(todo) == "[x] Ship v2"


def test_block_text_ignores_non_text_blocks():
    assert N._block_text({"type": "image", "image": {}}) == ""
    assert N._block_text({"type": "divider", "divider": {}}) == ""


def test_page_title_reads_the_title_property():
    page = {"properties": {"Name": {"type": "title", "title": [{"plain_text": "Q3 Plan"}]}}}
    assert N._page_title(page) == "Q3 Plan"


def test_the_write_side_is_gone():
    """M9 read-only guarantee: the mirror/write API no longer exists."""
    for removed in ("provision_tasks_db", "push_task", "pull_changes", "sync",
                    "task_to_properties", "page_to_patch"):
        assert not hasattr(N, removed), f"{removed} should have been removed (read-only)"
