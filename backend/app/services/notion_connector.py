"""Notion connector — a READ-ONLY intelligence source.

Kora does not manage tasks inside Notion and never writes to a user's workspace.
Instead, a user who already keeps notes/specs/roadmaps in Notion connects it,
picks which pages to share, and Kora *reads* that content and folds it into its
semantic memory (`agent_memory`, kind="notion"). From then on the agent recalls
those facts by relevance — in the client view, the PM analysts, and chat — the
same way it recalls email intel and meeting notes.

Direction of data is one-way, Notion → Kora. There is deliberately no
`push`/`provision`/`sync-back` path: the whole point is that Notion is the
human's space and Kora treats it as a source, not a mirror it owns. (History:
this module used to be a two-way task mirror; the write side was removed in M9.)

Auth: a per-user OAuth token (multi-tenant) or a server-level `NOTION_API_KEY`
internal integration (single workspace / self-host). Everything degrades
gracefully: when Notion isn't connected, reads report "not connected" rather
than raising.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import store
from ..config import settings
from .token_encryption import decrypt_token, encrypt_token

_API = "https://api.notion.com/v1"

# Block types whose rich_text we treat as readable prose when ingesting a page.
_TEXT_BLOCKS = (
    "paragraph", "heading_1", "heading_2", "heading_3", "quote", "callout",
    "bulleted_list_item", "numbered_list_item", "to_do", "toggle", "code",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Connection ──────────────────────────────────────────────────────────────
def is_multi_tenant() -> bool:
    """True when a public OAuth integration is configured.

    This is the tenant-isolation switch. Once OAuth exists, EVERY user must
    authorize their own workspace — see `_token`.
    """
    return bool(settings.NOTION_OAUTH_CLIENT_ID and settings.NOTION_OAUTH_CLIENT_SECRET)


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
    if is_multi_tenant():
        return None
    return settings.NOTION_API_KEY or None


def _selected_page_ids(user_id: str) -> list[str]:
    try:
        conn = store.get_notion_connection(user_id) or {}
    except Exception:
        conn = {}
    return list(conn.get("ingest_page_ids") or [])


def is_connected(user_id: str) -> bool:
    return bool(_token(user_id))


def status(user_id: str) -> dict:
    try:
        conn = store.get_notion_connection(user_id) or {}
    except Exception:
        conn = {}
    return {
        "connected": bool(_token(user_id)),
        # Report the mode actually in force. Once OAuth is configured every user
        # must authorize their own workspace, so the shared NOTION_API_KEY is
        # inert for anyone who hasn't connected — claiming "api_key" there would
        # be a lie. Mirrors the isolation rule in `_token`.
        "authMode": (
            "oauth" if conn.get("access_token")
            else None if is_multi_tenant()
            else "api_key" if settings.NOTION_API_KEY
            else None
        ),
        "workspaceName": conn.get("workspace_name"),
        "selectedPageIds": list(conn.get("ingest_page_ids") or []),
        "selectedPageCount": len(conn.get("ingest_page_ids") or []),
        "lastIngestAt": conn.get("last_ingest_at"),
        "lastError": conn.get("last_error"),
        "oauthConfigured": bool(settings.NOTION_OAUTH_CLIENT_ID and settings.NOTION_OAUTH_CLIENT_SECRET),
    }


def set_ingest_pages(user_id: str, page_ids: list[str]) -> dict:
    """Persist the user's chosen pages/databases to read. Read-only selection —
    nothing is written to Notion."""
    clean = [str(p) for p in (page_ids or []) if str(p).strip()]
    store.upsert_notion_connection(user_id, {
        "ingest_page_ids": clean, "updated_at": _now(), "last_error": None,
    })
    return {"ok": True, "selectedPageCount": len(clean)}


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


def _record_error(user_id: str, message: str) -> None:
    try:
        store.update_notion_connection(user_id, {"last_error": message[:300], "updated_at": _now()})
    except Exception:
        pass


# ── Read: pages the user granted + their text content ────────────────────────
def _plain(rich: list | None) -> str:
    """Concatenate a Notion rich_text array to plain text."""
    if not rich:
        return ""
    return "".join(t.get("plain_text") or t.get("text", {}).get("content", "") for t in rich)


def _page_title(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return _plain(prop.get("title")).strip()
    return ""


def list_parent_pages(user_id: str, limit: int = 50) -> dict:
    """Pages this user granted the integration access to — the ingest picker.

    Multi-tenant users pick which of their OWN pages Kora may read; we can't
    assume ids from server config because they belong to another workspace.
    """
    token = _token(user_id)
    if not token:
        return {"ok": False, "error": "Notion is not connected.", "pages": []}
    try:
        res = _request("POST", "/search", token, {
            "filter": {"property": "object", "value": "page"},
            "page_size": limit,
        })
    except RuntimeError as exc:
        _record_error(user_id, str(exc))
        return {"ok": False, "error": str(exc), "pages": []}

    pages = []
    for p in res.get("results", []):
        title = _page_title(p)
        pages.append({"id": p.get("id"), "title": title or "Untitled", "url": p.get("url")})
    return {"ok": True, "pages": pages}


def _block_text(block: dict) -> str:
    """Readable text from one block, or "" for non-text blocks."""
    btype = block.get("type", "")
    if btype not in _TEXT_BLOCKS:
        return ""
    body = block.get(btype) or {}
    text = _plain(body.get("rich_text"))
    if btype == "to_do":
        mark = "[x]" if body.get("checked") else "[ ]"
        text = f"{mark} {text}".strip()
    return text.strip()


def read_page_text(user_id: str, page_id: str, *, max_chars: int = 8000) -> dict:
    """Read one page's title + block text (top level, paginated). Read-only.

    Returns {ok, pageId, title, url, text}. Never writes to Notion.
    """
    token = _token(user_id)
    if not token:
        return {"ok": False, "error": "Notion is not connected."}
    try:
        page = _request("GET", f"/pages/{page_id}", token)
        title = _page_title(page)
        url = page.get("url")
        parts: list[str] = []
        cursor: str | None = None
        # Paginate the block children; cap total length so one huge page can't
        # blow the embedding/token budget.
        while True:
            path = f"/blocks/{page_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            res = _request("GET", path, token)
            for b in res.get("results", []):
                t = _block_text(b)
                if t:
                    parts.append(t)
            if len("\n".join(parts)) >= max_chars or not res.get("has_more"):
                break
            cursor = res.get("next_cursor")
            if not cursor:
                break
        text = "\n".join(parts)[:max_chars].strip()
        return {"ok": True, "pageId": page_id, "title": title, "url": url, "text": text}
    except RuntimeError as exc:
        _record_error(user_id, str(exc))
        return {"ok": False, "error": str(exc), "pageId": page_id}


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
