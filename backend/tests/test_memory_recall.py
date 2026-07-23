"""Hybrid semantic memory — ranking, and the lexical fallback that keeps it alive.

The fallback matters most: if the embedding provider is unreachable, recall must
degrade to lexical-only rather than returning nothing or raising.
"""
from __future__ import annotations

from app.services import memory_recall as MR


# ── Lexical fallback (no embeddings available) ─────────────────────────────

def test_recall_ranks_by_lexical_overlap_when_embeddings_are_off(user_id, no_embeddings):
    MR.remember(user_id, "graph_fact", "Acme pushed back on pricing and asked for a discount", ref_id="a")
    MR.remember(user_id, "graph_fact", "Beta Corp always pays within five days", ref_id="b")

    hits = MR.recall(user_id, "discount pricing", k=3)

    assert hits, "lexical fallback returned nothing"
    assert "pricing" in hits[0]["content"]
    # No vectors available, so the semantic term must be absent rather than faked.
    assert hits[0]["_sim"] is None
    assert hits[0]["_lex"] > 0


def test_remember_still_persists_without_embeddings(user_id, no_embeddings):
    MR.remember(user_id, "playbook", "Owner prefers short, direct emails", ref_id="p1")
    stats = MR.stats(user_id)
    assert stats["total"] == 1
    assert stats["embedded"] == 0


# ── Semantic path (deterministic offline vectors) ──────────────────────────

def test_semantic_similarity_outranks_a_lexically_unrelated_memory(user_id, fake_embeddings):
    """The point of embeddings: match by meaning, not shared words."""
    query = "client will not settle their bill"
    on_topic = "Harbor Studios has an unpaid invoice that is badly overdue"
    off_topic = "Sunrise Bakery loved the new logo design"

    fake_embeddings(query, [1.0, 0.0])
    fake_embeddings(on_topic, [0.98, 0.2])    # near-parallel to the query
    fake_embeddings(off_topic, [0.0, 1.0])    # orthogonal

    MR.remember(user_id, "graph_fact", on_topic, ref_id="a")
    MR.remember(user_id, "graph_fact", off_topic, ref_id="b")

    hits = MR.recall(user_id, query, k=2)

    assert hits[0]["content"] == on_topic
    assert hits[0]["_sim"] > hits[1]["_sim"]
    # Zero shared terms — this ranking is purely semantic.
    assert hits[0]["_lex"] == 0.0


# ── Scoping and edge cases ─────────────────────────────────────────────────

def test_recall_can_be_scoped_to_one_client(user_id, no_embeddings):
    MR.remember(user_id, "email_intel", "Acme is happy", client_id="c-acme", ref_id="a")
    MR.remember(user_id, "email_intel", "Beta is happy", client_id="c-beta", ref_id="b")

    hits = MR.recall(user_id, "happy", k=10, client_id="c-acme", min_score=0.0)

    assert len(hits) == 1
    assert hits[0]["client_id"] == "c-acme"


def test_empty_query_and_empty_store_return_nothing(user_id, no_embeddings):
    assert MR.recall(user_id, "", k=5) == []
    assert MR.recall(user_id, "anything at all", k=5) == []
    assert MR.build_recall_brief(user_id, "anything") == ""


def test_remember_is_idempotent_on_ref_id(user_id, no_embeddings):
    MR.remember(user_id, "graph_fact", "First wording", ref_id="same")
    MR.remember(user_id, "graph_fact", "Updated wording", ref_id="same")

    assert MR.stats(user_id)["total"] == 1
    assert MR.recall(user_id, "wording", k=5, min_score=0.0)[0]["content"] == "Updated wording"


def test_blank_content_is_not_stored(user_id, no_embeddings):
    MR.remember(user_id, "graph_fact", "   ", ref_id="blank")
    assert MR.stats(user_id)["total"] == 0


def test_recall_brief_is_capped_and_prefixed(user_id, no_embeddings):
    for i in range(10):
        MR.remember(user_id, "graph_fact", f"Overdue invoice number {i} for the client", ref_id=f"r{i}")

    brief = MR.build_recall_brief(user_id, "overdue invoice", max_chars=200)

    assert brief.startswith("Relevant past context")
    assert len(brief) <= 200
