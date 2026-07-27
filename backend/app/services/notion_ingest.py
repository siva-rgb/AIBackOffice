"""Notion → semantic memory ingestion (M9).

Reads the pages a user chose to share and folds their text into `agent_memory`
as `kind="notion"` rows, so the agent recalls that content by relevance
wherever it already uses hybrid recall (client view, PM analysts, chat). This is
the whole payoff of the read-only integration: Notion stops being a separate
place the user has to check and becomes another source the agent just *knows*.

Two properties matter and are tested:
 * **Idempotent per page.** Each page's chunks use ref_ids `"{page_id}#{i}"`, and
   a re-ingest clears that page's old chunks first — so re-running never
   duplicates and a shrunk page never leaves stale tail chunks. A page whose
   read *fails* keeps its previous memory rather than being wiped.
 * **Provenance.** Every row carries `source="notion"` and the page id + URL in
   metadata, so a recalled fact can always be traced back to its Notion page.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import store
from . import memory_recall, notion_connector

MEMORY_KIND = "notion"
_CHUNK_CHARS = 1500  # keep each memory row well under the 2000-char store cap
_MAX_CHUNKS_PER_PAGE = 8  # bound one giant page's footprint


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunk(text: str) -> list[str]:
    """Split page text into recall-sized chunks on paragraph boundaries."""
    chunks: list[str] = []
    buf = ""
    for para in (text or "").split("\n"):
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 1 > _CHUNK_CHARS and buf:
            chunks.append(buf.strip())
            buf = ""
        buf += para + "\n"
        if len(chunks) >= _MAX_CHUNKS_PER_PAGE:
            break
    if buf.strip() and len(chunks) < _MAX_CHUNKS_PER_PAGE:
        chunks.append(buf.strip())
    return chunks


def ingest(user_id: str) -> dict:
    """Read every selected page and (re)index it into agent_memory. Never raises.

    Returns counts. A no-op (structured, not an exception) when Notion is not
    connected or no pages are selected.
    """
    if not notion_connector.is_connected(user_id):
        return {"ok": False, "error": "Notion is not connected.", "pages": 0, "chunks": 0}

    page_ids = notion_connector._selected_page_ids(user_id)
    if not page_ids:
        return {"ok": True, "pages": 0, "chunks": 0, "note": "No pages selected to read."}

    pages_done = chunks_written = failed = 0
    for page_id in page_ids:
        read = notion_connector.read_page_text(user_id, page_id)
        if not read.get("ok"):
            failed += 1
            continue  # keep this page's previous memory rather than wiping it

        title = read.get("title") or "Untitled"
        url = read.get("url")
        body = f"{title}\n{read.get('text', '')}".strip()

        # Clear only THIS page's prior chunks, then re-add — idempotent, and a
        # shrunk page leaves no stale tail. Scoped to kind + this page's prefix
        # so it can never touch another page or another memory kind.
        store.delete_agent_memory(user_id, kind=MEMORY_KIND, ref_id_prefix=f"{page_id}#")

        for i, chunk in enumerate(_chunk(body)):
            memory_recall.remember(
                user_id,
                MEMORY_KIND,
                chunk,
                ref_type="notion_page",
                ref_id=f"{page_id}#{i}",
                salience=0.6,
                source="notion",
                metadata={"pageId": page_id, "title": title, "url": url},
            )
            chunks_written += 1
        pages_done += 1

    try:
        store.update_notion_connection(user_id, {"last_ingest_at": _now(), "updated_at": _now(), "last_error": None})
    except Exception:
        pass

    return {"ok": True, "pages": pages_done, "chunks": chunks_written, "failed": failed}


def purge(user_id: str) -> int:
    """Remove all of this user's Notion-sourced memories (and only those).

    Called on disconnect so revoking Notion also revokes what Kora learned from
    it — the content stops influencing recall immediately.
    """
    try:
        return store.delete_agent_memory(user_id, kind=MEMORY_KIND)
    except Exception as exc:
        print(f"[notion_ingest] purge failed: {exc}")
        return 0
