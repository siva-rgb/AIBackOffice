"""Hybrid semantic memory — recall past context by relevance.

A durable, embeddable memory index (`agent_memory`) the agents query when they
need PAST information for planning or a decision. It complements the structured
stores: where the Playbook and graph answer "what do we know about X" by exact
key/name, this answers "what past context is *relevant* to this situation" by
meaning.

Ranking is HYBRID:
    score = w·semantic_similarity  (embeddings, when available)
          + w·lexical_overlap      (query-term recall)
          + w·salience             (how important the memory is)
          + w·recency              (30-day half-life)

When embeddings aren't configured the semantic term drops out and recall falls
back to lexical-only — so it always returns something useful and never hard-fails.

Per-user memory is small (100s–1000s of rows), so we load the candidate rows and
score in Python — the same design as `graph_memory`. A pgvector ANN index is a
drop-in optimization later without changing this interface.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from .. import store
from . import embeddings

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "is", "are",
    "with", "this", "that", "it", "at", "by", "be", "as", "we", "our", "you",
    "your", "was", "has", "have", "had", "will", "about",
}

# Kinds recalled by default (all). Callers can narrow with `kinds=`.
KINDS = ("playbook", "graph_fact", "email_intel", "meeting", "note", "decision", "action")


def _tokens(text: str) -> set[str]:
    return {w for w in _TOKEN.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}


def _cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _lexical(q_tokens: set[str], text: str) -> float:
    if not q_tokens:
        return 0.0
    t = _tokens(text)
    if not t:
        return 0.0
    return len(q_tokens & t) / len(q_tokens)   # recall of the query's terms


def _recency(iso: str | None) -> float:
    if not iso:
        return 0.5
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
    except Exception:
        return 0.5
    return 0.5 ** (days / 30.0)   # 30-day half-life


# ── Write ───────────────────────────────────────────────────────────────────
def remember(user_id: str, kind: str, content: str, *, client_id: str | None = None,
             ref_type: str | None = None, ref_id: str | None = None,
             salience: float = 0.5, source: str | None = None,
             metadata: dict | None = None, defer_embed: bool = False) -> None:
    """Persist a recallable memory. Best-effort — never raises.

    Embeds the content when the provider is available (skip with defer_embed=True
    for bulk paths that batch-embed afterwards). Stored either way — lexical
    recall works without a vector.
    """
    content = (content or "").strip()
    if not content:
        return
    try:
        vec = None if defer_embed else embeddings.embed(content)
        store.upsert_agent_memory(user_id, {
            "kind": kind, "client_id": client_id, "ref_type": ref_type, "ref_id": ref_id,
            "content": content[:2000], "embedding": vec, "salience": float(salience),
            "source": source, "metadata": metadata or {},
        })
    except Exception as exc:
        print(f"[memory] remember failed: {exc}")


# ── Read ────────────────────────────────────────────────────────────────────
def recall(user_id: str, query: str, *, k: int = 6, client_id: str | None = None,
           kinds: list[str] | None = None, min_score: float = 0.05) -> list[dict]:
    """Top-k memories most relevant to `query`, hybrid-ranked. Each result carries
    the original row plus `_score`, `_sim` (None if lexical-only) and `_lex`."""
    query = (query or "").strip()
    if not query:
        return []
    rows = store.get_agent_memory(user_id, client_id=client_id, kinds=kinds)
    if not rows:
        return []

    q_tokens = _tokens(query)
    q_vec = embeddings.embed(query)   # None → lexical-only ranking

    scored: list[dict] = []
    for r in rows:
        emb = r.get("embedding")
        sim = _cosine(q_vec, emb) if (q_vec and emb) else None
        lex = _lexical(q_tokens, r.get("content", ""))
        sal = float(r.get("salience", 0.5) or 0.5)
        rec = _recency(r.get("updated_at") or r.get("created_at"))
        if sim is not None:
            score = 0.60 * sim + 0.20 * lex + 0.12 * sal + 0.08 * rec
        else:
            score = 0.70 * lex + 0.18 * sal + 0.12 * rec
        if score >= min_score:
            scored.append({
                **r, "_score": round(score, 4),
                "_sim": round(sim, 4) if sim is not None else None,
                "_lex": round(lex, 4),
            })
    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored[:k]


def build_recall_brief(user_id: str, query: str, *, k: int = 5,
                       client_id: str | None = None, kinds: list[str] | None = None,
                       max_chars: int = 500) -> str:
    """Serialize the top recalled memories into a prompt-injection block, or ""."""
    hits = recall(user_id, query, k=k, client_id=client_id, kinds=kinds)
    if not hits:
        return ""
    lines = ["Relevant past context (recalled by relevance):"]
    for h in hits:
        lines.append(f"- {h['content'][:200]}")
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rsplit("\n", 1)[0]
    return out


# ── Backfill / (re)embed ─────────────────────────────────────────────────────
def reindex(user_id: str, *, embed_missing: bool = True) -> dict:
    """Rebuild `agent_memory` from the existing structured stores (Playbook,
    graph facts, email intel) and embed any rows still missing a vector.
    Idempotent (upsert on kind+ref_id). Returns counts."""
    counts = {"playbook": 0, "graph_fact": 0, "email_intel": 0, "embedded": 0}

    # Playbook summaries — the learned prefs/rules/facts/intel.
    try:
        for e in store.get_playbook_entries(user_id, limit=500):
            summ = (e.get("summary") or "").strip()
            if not summ:
                continue
            remember(user_id, "playbook", summ,
                     client_id=e.get("client_id"), ref_type="playbook",
                     ref_id=str(e.get("id") or e.get("key") or summ[:60]),
                     salience=float(e.get("confidence", 0.5) or 0.5),
                     source=e.get("source"), defer_embed=True)
            counts["playbook"] += 1
    except Exception as exc:
        print(f"[memory] reindex playbook failed: {exc}")

    # Graph fact nodes — learned client facts (email/meeting commitments etc.).
    try:
        for n in store.get_kg_nodes(user_id):
            if n.get("node_type") != "fact":
                continue
            label = (n.get("label") or "").strip()
            if label:
                remember(user_id, "graph_fact", label, ref_type="kg_node",
                         ref_id=str(n.get("id")),
                         salience=float(n.get("salience", 0.6) or 0.6), defer_embed=True)
                counts["graph_fact"] += 1
    except Exception as exc:
        print(f"[memory] reindex graph failed: {exc}")

    # Email intel summaries (Supabase only; best-effort).
    try:
        from ..config import settings
        if settings.SUPABASE_URL:
            from supabase import create_client
            db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
            rows = db.table("email_intel_cache").select(
                "client_id, client_name, summary").eq("user_id", user_id).execute().data or []
            for row in rows:
                summ = (row.get("summary") or "").strip()
                if summ:
                    remember(user_id, "email_intel",
                             f"{row.get('client_name', '')}: {summ}".strip(": "),
                             client_id=row.get("client_id"), ref_type="email_intel_cache",
                             ref_id=str(row.get("client_id")), salience=0.6,
                             source="email", defer_embed=True)
                    counts["email_intel"] += 1
    except Exception as exc:
        print(f"[memory] reindex email failed: {exc}")

    # Embed rows that still lack a vector — one batched pass.
    if embed_missing and embeddings.is_enabled():
        try:
            rows = store.get_agent_memory(user_id)
            missing = [r for r in rows if not r.get("embedding") and r.get("content")]
            vecs = embeddings.embed_batch([r["content"] for r in missing])
            for r, v in zip(missing, vecs):
                if v:
                    store.upsert_agent_memory(user_id, {**r, "embedding": v})
                    counts["embedded"] += 1
        except Exception as exc:
            print(f"[memory] reindex embed failed: {exc}")

    counts["total"] = len(store.get_agent_memory(user_id))
    counts["embeddingsEnabled"] = embeddings.is_enabled()
    return counts


def stats(user_id: str) -> dict:
    rows = store.get_agent_memory(user_id)
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r.get("kind", "?")] = by_kind.get(r.get("kind", "?"), 0) + 1
    return {
        "total": len(rows),
        "embedded": sum(1 for r in rows if r.get("embedding")),
        "embeddingsEnabled": embeddings.is_enabled(),
        "byKind": by_kind,
    }
