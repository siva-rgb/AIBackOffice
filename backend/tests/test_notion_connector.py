"""Notion connector — mapping fidelity and, critically, tenant isolation.

Everything here is offline: only the pure mapping helpers and the auth-mode
resolution are exercised. No `_request` call is made, so no network is touched.
"""
from __future__ import annotations

from app.services import notion_connector as N
from app.services import task_ledger as TL


# ── Tenant isolation — the highest-severity property in the repo ────────────

def test_multi_tenant_never_falls_back_to_the_shared_key(monkeypatch, settings, user_id):
    """A user without their own token must get NO token once OAuth is configured.

    Regression for a real cross-tenant leak: `_token()` used to fall back to the
    server-level NOTION_API_KEY, which would sync one user's client tasks into
    the *owner's* Notion workspace.
    """
    # The shared owner key is present — this is the dangerous condition.
    monkeypatch.setattr(settings, "NOTION_API_KEY", "ntn_owner_secret")
    # ...and a public OAuth integration is configured, so we are multi-tenant.
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


# ── Graceful degradation — never raise when unconfigured ───────────────────

def test_sync_and_provision_degrade_without_credentials(user_id):
    """Unconfigured Notion returns a structured error rather than blowing up."""
    sync = N.sync(user_id)
    assert sync["ok"] is False
    assert "not connected" in sync["error"].lower()
    assert sync["pushed"] == 0

    prov = N.provision_tasks_db(user_id)
    assert prov["ok"] is False


# ── Pure mapping round-trip ────────────────────────────────────────────────

def test_task_maps_to_notion_properties(user_id):
    task = TL.create_task(user_id, {
        "title": "Ship the landing page",
        "due_date": "2026-08-01",
        "priority": "urgent",
        "owner": "me",
    })
    TL.update_task(user_id, task.id, {"status": "in_progress"})
    from app import store
    task = store.get_task(user_id, task.id)

    props = N.task_to_properties(task, client_name="Acme Corp")

    assert props["Name"]["title"][0]["text"]["content"] == "Ship the landing page"
    assert props["Status"]["select"]["name"] == "In progress"
    assert props["Priority"]["select"]["name"] == "Urgent"
    assert props["Due"]["date"]["start"] == "2026-08-01"
    assert props["Client"]["rich_text"][0]["text"]["content"] == "Acme Corp"
    # KoraId is what lets the pull direction find the canonical row again.
    assert props["KoraId"]["rich_text"][0]["text"]["content"] == task.id


def test_notion_page_maps_back_to_a_task_patch():
    page = {
        "id": "page-1",
        "properties": {
            "Name": {"title": [{"plain_text": "Ship the landing page (v2)"}]},
            "Status": {"select": {"name": "Done"}},
            "Priority": {"select": {"name": "High"}},
            "Due": {"date": {"start": "2026-08-05"}},
            "KoraId": {"rich_text": [{"plain_text": "task-abc"}]},
        },
    }
    patch = N.page_to_patch(page)

    assert patch["title"] == "Ship the landing page (v2)"
    assert patch["status"] == "done"
    assert patch["priority"] == "high"
    assert patch["due_date"] == "2026-08-05"
    assert N.page_kora_id(page) == "task-abc"


def test_notion_cannot_reparent_a_task():
    """Linkage and provenance are KORA-owned; a Notion edit must never touch them.

    Without this, someone editing a page in Notion could silently move a task to
    a different client or rewrite where it came from.
    """
    page = {
        "id": "page-1",
        "properties": {
            "Name": {"title": [{"plain_text": "Anything"}]},
            "Status": {"select": {"name": "To do"}},
            # A hostile/edited page trying to claim different linkage:
            "Client": {"rich_text": [{"plain_text": "Some Other Client"}]},
            "Source": {"rich_text": [{"plain_text": "manual"}]},
        },
    }
    patch = N.page_to_patch(page)

    for forbidden in ("client_id", "engagement_id", "source", "source_ref", "external_ref"):
        assert forbidden not in patch, f"Notion was allowed to override {forbidden}"


def test_unknown_status_is_ignored_rather_than_guessed():
    """A renamed/unmapped select value must not corrupt the canonical status."""
    page = {
        "id": "page-1",
        "properties": {
            "Name": {"title": [{"plain_text": "Task"}]},
            "Status": {"select": {"name": "Wibble"}},
        },
    }
    patch = N.page_to_patch(page)
    assert "status" not in patch
    assert patch["title"] == "Task"
