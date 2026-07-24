"""Notion read-only intelligence source (M9).

Covers the milestone's success criteria: read-only + idempotent ingest with
provenance, disconnect purge, graceful degradation, and — the payoff — a fact
that exists ONLY in a Notion page reaching the PM agent via recall.

Everything is offline: `notion_connector.read_page_text` is monkeypatched, so no
network is touched and no Notion write can occur.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import store
from app.models import Client
from app.services import llm, memory_recall, notion_connector, notion_ingest, pm_agent


def _now():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def client(user_id):
    c = Client(id=store.uid("client"), user_id=user_id, name="Acme Corp",
               status="active", last_activity_at=_now(), created_at=_now())
    store.insert_client(c)
    return c


@pytest.fixture
def connected(monkeypatch, user_id):
    """Pretend Notion is connected with one selected page, and stub the reader."""
    monkeypatch.setattr(notion_connector, "is_connected", lambda uid: True)
    monkeypatch.setattr(notion_connector, "_selected_page_ids", lambda uid: ["page-1"])

    pages = {"page-1": {
        "ok": True, "pageId": "page-1", "title": "Acme roadmap",
        "url": "https://notion.so/acme", "text": "Delivery status: the redesign is blocked "
        "on BRANDASSETS_XYZ from the client.",
    }}
    monkeypatch.setattr(notion_connector, "read_page_text",
                        lambda uid, pid, **kw: pages.get(pid, {"ok": False, "error": "not found"}))
    return pages


# ── Criterion 2 · ingest + provenance ──────────────────────────────────────

def test_ingest_writes_notion_memory_with_provenance(user_id, connected):
    result = notion_ingest.ingest(user_id)
    assert result["ok"] is True and result["pages"] == 1 and result["chunks"] >= 1

    rows = store.get_agent_memory(user_id, kinds=["notion"])
    assert rows, "nothing was ingested into agent_memory"
    row = rows[0]
    assert row["source"] == "notion"
    assert row["ref_id"].startswith("page-1#")
    assert row["metadata"]["pageId"] == "page-1"
    assert row["metadata"]["url"] == "https://notion.so/acme"
    assert "BRANDASSETS_XYZ" in row["content"]


def test_ingest_is_idempotent(user_id, connected):
    notion_ingest.ingest(user_id)
    first = len(store.get_agent_memory(user_id, kinds=["notion"]))
    notion_ingest.ingest(user_id)
    second = len(store.get_agent_memory(user_id, kinds=["notion"]))
    assert first == second, "re-ingest duplicated rows"


def test_a_shrunk_page_leaves_no_stale_chunks(user_id, monkeypatch):
    monkeypatch.setattr(notion_connector, "is_connected", lambda uid: True)
    monkeypatch.setattr(notion_connector, "_selected_page_ids", lambda uid: ["page-1"])

    big = "\n".join(f"Paragraph {i} " + "x" * 400 for i in range(6))   # multi-chunk
    state = {"text": big}
    monkeypatch.setattr(notion_connector, "read_page_text",
                        lambda uid, pid, **kw: {"ok": True, "pageId": pid, "title": "P",
                                               "url": None, "text": state["text"]})
    notion_ingest.ingest(user_id)
    assert len(store.get_agent_memory(user_id, kinds=["notion"])) > 1

    state["text"] = "Now just one line."     # page shrank
    notion_ingest.ingest(user_id)
    rows = store.get_agent_memory(user_id, kinds=["notion"])
    assert len(rows) == 1, "stale tail chunks survived a shrink"


def test_a_failed_page_read_keeps_prior_memory(user_id, monkeypatch):
    monkeypatch.setattr(notion_connector, "is_connected", lambda uid: True)
    monkeypatch.setattr(notion_connector, "_selected_page_ids", lambda uid: ["page-1"])
    ok = {"ok": True, "pageId": "page-1", "title": "P", "url": None, "text": "Good content here."}
    monkeypatch.setattr(notion_connector, "read_page_text", lambda uid, pid, **kw: ok)
    notion_ingest.ingest(user_id)
    assert store.get_agent_memory(user_id, kinds=["notion"])

    # Now the read fails — prior memory must survive, not be wiped.
    monkeypatch.setattr(notion_connector, "read_page_text",
                        lambda uid, pid, **kw: {"ok": False, "error": "Notion 502"})
    result = notion_ingest.ingest(user_id)
    assert result["failed"] == 1
    assert store.get_agent_memory(user_id, kinds=["notion"]), "a failed read wiped good memory"


# ── Criterion 4 · privacy: disconnect purges only Notion memory ─────────────

def test_purge_removes_only_notion_memory(user_id, connected):
    memory_recall.remember(user_id, "note", "a non-Notion memory", ref_id="note-1")
    notion_ingest.ingest(user_id)
    assert store.get_agent_memory(user_id, kinds=["notion"])

    removed = notion_ingest.purge(user_id)
    assert removed >= 1
    assert store.get_agent_memory(user_id, kinds=["notion"]) == []
    # The unrelated memory is untouched.
    assert store.get_agent_memory(user_id, kinds=["note"])


# ── Criterion 5 · graceful degradation ─────────────────────────────────────

def test_ingest_is_a_noop_when_not_connected(user_id, monkeypatch):
    monkeypatch.setattr(notion_connector, "is_connected", lambda uid: False)
    result = notion_ingest.ingest(user_id)
    assert result["ok"] is False and result["pages"] == 0


def test_ingest_is_a_noop_when_no_pages_selected(user_id, monkeypatch):
    monkeypatch.setattr(notion_connector, "is_connected", lambda uid: True)
    monkeypatch.setattr(notion_connector, "_selected_page_ids", lambda uid: [])
    result = notion_ingest.ingest(user_id)
    assert result["ok"] is True and result["pages"] == 0


# ── Criterion 3 · the agent actually USES it ───────────────────────────────

def test_notion_fact_is_recalled_by_relevance(user_id, connected):
    notion_ingest.ingest(user_id)
    hits = memory_recall.recall(user_id, "brandassets redesign blocked", kinds=["notion"])
    assert hits, "ingested Notion content was not recalled"
    assert "BRANDASSETS_XYZ" in hits[0]["content"]


def test_notion_content_reaches_the_pm_analyst(user_id, client, connected, monkeypatch):
    """The payoff: a fact that lives ONLY in Notion is handed to the analysts.

    We capture the brief each analyst receives and assert the Notion fact is in
    it — proving the composed client view is informed by Notion, not just the
    ledger numbers.
    """
    notion_ingest.ingest(user_id)
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    # Forcing is_configured also enables embeddings; keep recall lexical so the
    # test never reaches the (blank) gateway.
    from app.services import embeddings
    monkeypatch.setattr(embeddings, "is_enabled", lambda: False)

    seen: list[str] = []

    def capturing_chat(system, user, **kw):
        seen.append(user)
        return llm.LLMResult('{"summary":"ok","highlights":[],"concerns":[]}', 10, 5, 1, "fake")

    pm_agent.compose_client_view(user_id, client.id, chat=capturing_chat)

    assert any("BRANDASSETS_XYZ" in brief for brief in seen), (
        "the Notion-sourced fact never reached an analyst brief"
    )
