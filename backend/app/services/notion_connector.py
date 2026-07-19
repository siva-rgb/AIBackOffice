"""Notion connector — mirrors the canonical KORA task ledger into Notion.

**KORA is the source of truth.** Notion is a mirror the owner can read and edit
in a workspace their whole team already understands. Every task carries
`external_ref` (the Notion page id) so pushes and pulls are idempotent and the
two sides can never fork into duplicates.

Conflict model (KORA-canonical, but the human wins on the human fields):
  * KORA owns linkage + provenance — client_id, engagement_id, source, source_ref.
    Notion can never change these.
  * Notion may override the "working" fields a person naturally edits on a board:
    title, status, priority, due date. Last write wins by timestamp.

Schema ownership: KORA **provisions** its own Tasks database (`provision_tasks_db`)
with the exact properties it expects, under `NOTION_PARENT_PAGE_ID`. That is the
whole reason sync is robust — if we mapped onto a user-built database, a renamed
property would silently break it.

Auth: a per-user OAuth token (multi-tenant) or a server-level `NOTION_API_KEY`
internal integration (single workspace / self-host). Everything degrades
gracefully: when Notion isn't configured, `sync()` reports "not connected"
rather than raising.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import store
from ..config import settings
from .token_encryption import decrypt_token, encrypt_token

_API = "https://api.notion.com/v1"

# KORA task status  ->  Notion select option (and back)
_STATUS_TO_NOTION = {
    "todo": "To do", "in_progress": "In progress", "blocked": "Blocked",
    "done": "Done", "cancelled": "Cancelled",
}
_STATUS_FROM_NOTION = {v.lower(): k for k, v in _STATUS_TO_NOTION.items()}
_PRIORITY_TO_NOTION = {"low": "Low", "medium": "Medium", "high": "High", "urgent": "Urgent"}
_PRIORITY_FROM_NOTION = {v.lower(): k for k, v in _PRIORITY_TO_NOTION.items()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Connection ──────────────────────────────────────────────────────────────
def _token(user_id: str) -> str | None:
    """Per-user OAuth token, else the server-level internal-integration key."""
    try:
        conn = store.get_notion_connection(user_id) or {}
    except Exception:
        conn = {}
    raw = conn.get("access_token")
    if raw:
        try:
            return decrypt_token(raw)
        except Exception:
            return raw  # tolerate a plaintext token written in dev
    return settings.NOTION_API_KEY or None


def _tasks_db_id(user_id: str) -> str | None:
    try:
        conn = store.get_notion_connection(user_id) or {}
    except Exception:
        conn = {}
    return conn.get("tasks_db_id")


def is_connected(user_id: str) -> bool:
    return bool(_token(user_id))


def status(user_id: str) -> dict:
    try:
        conn = store.get_notion_connection(user_id) or {}
    except Exception:
        conn = {}
    return {
        "connected": bool(_token(user_id)),
        "authMode": "oauth" if conn.get("access_token") else ("api_key" if settings.NOTION_API_KEY else None),
        "workspaceName": conn.get("workspace_name"),
        "tasksDbId": conn.get("tasks_db_id"),
        "provisioned": bool(conn.get("tasks_db_id")),
        "lastSyncAt": conn.get("last_sync_at"),
        "lastError": conn.get("last_error"),
        "oauthConfigured": bool(settings.NOTION_OAUTH_CLIENT_ID and settings.NOTION_OAUTH_CLIENT_SECRET),
    }


def disconnect(user_id: str) -> None:
    try:
        store.delete_notion_connection(user_id)
    except Exception:
        pass


# ── HTTP ────────────────────────────────────────────────────────────────────
def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": settings.NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    """One Notion API call. Raises RuntimeError with a readable message on failure."""
    import httpx
    url = f"{_API}{path}"
    try:
        with httpx.Client(timeout=30.0) as c:
            r = c.request(method, url, headers=_headers(token), json=payload)
    except Exception as exc:
        raise RuntimeError(f"Notion request failed: {str(exc)[:160]}")
    if r.status_code >= 400:
        detail = ""
        try:
            detail = r.json().get("message", "")
        except Exception:
            detail = r.text[:160]
        raise RuntimeError(f"Notion {r.status_code}: {detail[:200]}")
    try:
        return r.json()
    except Exception:
        return {}


# ── Pure mapping (no network — unit-testable) ───────────────────────────────
def task_to_properties(task, client_name: str | None = None) -> dict:
    """KORA task → Notion page properties for the KORA-provisioned schema."""
    props: dict = {
        "Name": {"title": [{"text": {"content": (task.title or "Untitled")[:2000]}}]},
        "Status": {"select": {"name": _STATUS_TO_NOTION.get(task.status, "To do")}},
        "Priority": {"select": {"name": _PRIORITY_TO_NOTION.get(task.priority, "Medium")}},
        # KoraId is what makes the pull direction safe — it maps a Notion page
        # back to the canonical row regardless of what the user renamed.
        "KoraId": {"rich_text": [{"text": {"content": task.id}}]},
        "Source": {"rich_text": [{"text": {"content": task.source or "manual"}}]},
    }
    if task.due_date:
        props["Due"] = {"date": {"start": str(task.due_date)[:10]}}
    if client_name:
        props["Client"] = {"rich_text": [{"text": {"content": client_name[:200]}}]}
    if task.owner:
        props["Owner"] = {"rich_text": [{"text": {"content": str(task.owner)[:200]}}]}
    return props


def _plain(prop: dict | None, kind: str = "rich_text") -> str:
    if not prop:
        return ""
    items = prop.get(kind) or []
    return "".join(i.get("plain_text") or i.get("text", {}).get("content", "") for i in items).strip()


def page_to_patch(page: dict) -> dict:
    """Notion page → the KORA task fields Notion is allowed to override.

    Deliberately narrow: title/status/priority/due only. Linkage and provenance
    stay KORA-owned so an edit in Notion can never re-parent a task."""
    props = page.get("properties") or {}
    patch: dict = {}

    title = _plain(props.get("Name"), "title")
    if title:
        patch["title"] = title[:300]

    sel = (props.get("Status") or {}).get("select") or {}
    mapped = _STATUS_FROM_NOTION.get(str(sel.get("name", "")).lower())
    if mapped:
        patch["status"] = mapped

    psel = (props.get("Priority") or {}).get("select") or {}
    pmapped = _PRIORITY_FROM_NOTION.get(str(psel.get("name", "")).lower())
    if pmapped:
        patch["priority"] = pmapped

    due = (props.get("Due") or {}).get("date") or {}
    if due.get("start"):
        patch["due_date"] = str(due["start"])[:10]

    return patch


def page_kora_id(page: dict) -> str:
    return _plain(((page.get("properties") or {}).get("KoraId")), "rich_text")


# ── Provisioning ────────────────────────────────────────────────────────────
_DB_SCHEMA = {
    "Name": {"title": {}},
    "Status": {"select": {"options": [
        {"name": "To do", "color": "gray"}, {"name": "In progress", "color": "blue"},
        {"name": "Blocked", "color": "red"}, {"name": "Done", "color": "green"},
        {"name": "Cancelled", "color": "default"},
    ]}},
    "Priority": {"select": {"options": [
        {"name": "Low", "color": "gray"}, {"name": "Medium", "color": "yellow"},
        {"name": "High", "color": "orange"}, {"name": "Urgent", "color": "red"},
    ]}},
    "Due": {"date": {}},
    "Client": {"rich_text": {}},
    "Owner": {"rich_text": {}},
    "Source": {"rich_text": {}},
    "KoraId": {"rich_text": {}},
}


def provision_tasks_db(user_id: str, parent_page_id: str | None = None) -> dict:
    """Create the KORA-owned Tasks database in the user's Notion workspace.
    Idempotent: returns the existing database if one is already provisioned."""
    token = _token(user_id)
    if not token:
        return {"ok": False, "error": "Notion is not connected."}
    existing = _tasks_db_id(user_id)
    if existing:
        return {"ok": True, "tasksDbId": existing, "created": False}

    parent = parent_page_id or settings.NOTION_PARENT_PAGE_ID
    if not parent:
        return {"ok": False, "error": "Set NOTION_PARENT_PAGE_ID (a page shared with the integration) "
                                      "or pass a parent page id."}
    try:
        db = _request("POST", "/databases", token, {
            "parent": {"type": "page_id", "page_id": parent},
            "title": [{"type": "text", "text": {"content": "KORA — Client Tasks"}}],
            "properties": _DB_SCHEMA,
        })
    except RuntimeError as exc:
        _record_error(user_id, str(exc))
        return {"ok": False, "error": str(exc)}

    db_id = db.get("id")
    store.upsert_notion_connection(user_id, {
        "tasks_db_id": db_id, "connected": True, "updated_at": _now(), "last_error": None,
    })
    return {"ok": True, "tasksDbId": db_id, "created": True, "url": db.get("url")}


def _record_error(user_id: str, message: str) -> None:
    try:
        store.update_notion_connection(user_id, {"last_error": message[:300], "updated_at": _now()})
    except Exception:
        pass


# ── Push: KORA → Notion ─────────────────────────────────────────────────────
def push_task(user_id: str, task, client_name: str | None = None) -> dict:
    """Create or update this task's mirrored Notion page."""
    token = _token(user_id)
    db_id = _tasks_db_id(user_id)
    if not token or not db_id:
        return {"ok": False, "error": "Notion not connected/provisioned."}

    props = task_to_properties(task, client_name)
    try:
        if task.external_ref:
            page = _request("PATCH", f"/pages/{task.external_ref}", token, {"properties": props})
        else:
            page = _request("POST", "/pages", token,
                            {"parent": {"database_id": db_id}, "properties": props})
    except RuntimeError as exc:
        _record_error(user_id, str(exc))
        return {"ok": False, "error": str(exc)}

    store.update_task(user_id, task.id, {
        "external_ref": page.get("id"), "external_url": page.get("url"), "synced_at": _now(),
    })
    return {"ok": True, "pageId": page.get("id"), "url": page.get("url")}


# ── Pull: Notion → KORA ─────────────────────────────────────────────────────
def pull_changes(user_id: str) -> dict:
    """Apply Notion-side edits back onto the canonical tasks.

    Notion's webhooks are newer and not guaranteed for every workspace, so we
    poll the database sorted by last_edited_time — reliable and cheap at the
    volumes a freelancer's board has.
    """
    token = _token(user_id)
    db_id = _tasks_db_id(user_id)
    if not token or not db_id:
        return {"ok": False, "error": "Notion not connected/provisioned.", "updated": 0}

    try:
        res = _request("POST", f"/databases/{db_id}/query", token, {
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
            "page_size": 100,
        })
    except RuntimeError as exc:
        _record_error(user_id, str(exc))
        return {"ok": False, "error": str(exc), "updated": 0}

    updated = 0
    for page in res.get("results", []):
        try:
            kora_id = page_kora_id(page)
            task = (store.get_task(user_id, kora_id) if kora_id
                    else store.find_task_by_external_ref(user_id, page.get("id", "")))
            if not task:
                continue
            patch = page_to_patch(page)
            # Only write fields that actually differ — keeps updated_at honest.
            diff = {k: v for k, v in patch.items() if getattr(task, k, None) != v}
            if not diff:
                continue
            if not task.external_ref:
                diff["external_ref"] = page.get("id")
            diff["synced_at"] = _now()
            from .task_ledger import update_task as ledger_update
            ledger_update(user_id, task.id, diff)
            updated += 1
        except Exception as exc:
            print(f"[notion] pull row skipped: {exc}")
    return {"ok": True, "updated": updated, "scanned": len(res.get("results", []))}


# ── Full sync ───────────────────────────────────────────────────────────────
def sync(user_id: str, *, push_limit: int = 100) -> dict:
    """Push canonical tasks to Notion, then pull back human edits. Idempotent."""
    if not is_connected(user_id):
        return {"ok": False, "error": "Notion is not connected.", "pushed": 0, "updated": 0}
    if not _tasks_db_id(user_id):
        prov = provision_tasks_db(user_id)
        if not prov.get("ok"):
            return {"ok": False, "error": prov.get("error"), "pushed": 0, "updated": 0}

    # Client names for the mirrored "Client" column.
    names: dict[str, str] = {}
    try:
        names = {c.id: c.name for c in store.list_clients(user_id)}
    except Exception:
        pass

    pushed = failed = 0
    try:
        tasks = store.list_tasks(user_id)
    except Exception as exc:
        return {"ok": False, "error": f"Could not read tasks: {str(exc)[:160]}", "pushed": 0, "updated": 0}

    for t in tasks[:push_limit]:
        # Skip rows already mirrored and unchanged since the last push.
        if t.external_ref and t.synced_at and (t.updated_at or "") <= t.synced_at:
            continue
        r = push_task(user_id, t, names.get(t.client_id or ""))
        if r.get("ok"):
            pushed += 1
        else:
            failed += 1

    pull = pull_changes(user_id)
    try:
        store.update_notion_connection(user_id, {"last_sync_at": _now(), "updated_at": _now()})
    except Exception:
        pass
    return {
        "ok": True, "pushed": pushed, "failed": failed,
        "updated": pull.get("updated", 0), "scanned": pull.get("scanned", 0),
    }


# ── OAuth (public integration) ──────────────────────────────────────────────
def oauth_authorize_url(state: str = "") -> str | None:
    if not settings.NOTION_OAUTH_CLIENT_ID:
        return None
    from urllib.parse import urlencode
    q = urlencode({
        "client_id": settings.NOTION_OAUTH_CLIENT_ID,
        "response_type": "code",
        "owner": "user",
        "redirect_uri": settings.NOTION_OAUTH_REDIRECT_URI,
        **({"state": state} if state else {}),
    })
    return f"https://api.notion.com/v1/oauth/authorize?{q}"


def exchange_code(user_id: str, code: str) -> dict:
    """Exchange an OAuth code for a workspace token and persist it (encrypted)."""
    if not (settings.NOTION_OAUTH_CLIENT_ID and settings.NOTION_OAUTH_CLIENT_SECRET):
        return {"ok": False, "error": "Notion OAuth is not configured."}
    import base64
    import httpx
    basic = base64.b64encode(
        f"{settings.NOTION_OAUTH_CLIENT_ID}:{settings.NOTION_OAUTH_CLIENT_SECRET}".encode()
    ).decode()
    try:
        with httpx.Client(timeout=30.0) as c:
            r = c.post(f"{_API}/oauth/token",
                       headers={"Authorization": f"Basic {basic}",
                                "Content-Type": "application/json",
                                "Notion-Version": settings.NOTION_VERSION},
                       json={"grant_type": "authorization_code", "code": code,
                             "redirect_uri": settings.NOTION_OAUTH_REDIRECT_URI})
        if r.status_code >= 400:
            return {"ok": False, "error": f"Notion OAuth {r.status_code}: {r.text[:200]}"}
        data = r.json()
    except Exception as exc:
        return {"ok": False, "error": f"Notion OAuth failed: {str(exc)[:160]}"}

    token = data.get("access_token", "")
    try:
        stored = encrypt_token(token)
    except Exception:
        stored = token
    store.upsert_notion_connection(user_id, {
        "access_token": stored,
        "workspace_id": data.get("workspace_id"),
        "workspace_name": data.get("workspace_name"),
        "bot_id": data.get("bot_id"),
        "connected": True,
        "last_error": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return {"ok": True, "workspaceName": data.get("workspace_name")}
