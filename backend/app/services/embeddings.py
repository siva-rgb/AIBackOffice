"""Text embeddings for semantic memory recall.

Thin wrapper over the existing OpenAI-compatible gateway (see `llm.py`). Every
call is best-effort: if embeddings aren't configured, or the gateway doesn't
expose the embedding model, `embed*` return None and callers degrade to
lexical-only recall. Never raises.

An in-process cache keyed on the content hash avoids re-embedding identical text
within a run (observers re-emit the same summary; reindex re-scans rows).
"""
from __future__ import annotations

import hashlib

from ..config import settings
from . import llm

_cache: dict[str, list[float]] = {}
_CACHE_MAX = 4096
_MAX_INPUT_CHARS = 8000  # keep well under typical 8k-token embedding limits


def is_enabled() -> bool:
    """True when the gateway is configured and an embedding model is set."""
    return bool(llm.is_configured() and settings.EMBEDDING_MODEL)


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def embed(text: str) -> list[float] | None:
    """Embed one string. Returns None (never raises) when disabled or on error."""
    text = (text or "").strip()
    if not text or not is_enabled():
        return None
    k = _key(text)
    cached = _cache.get(k)
    if cached is not None:
        return cached
    try:
        resp = llm._get_client().embeddings.create(
            model=settings.EMBEDDING_MODEL, input=text[:_MAX_INPUT_CHARS]
        )
        vec = list(resp.data[0].embedding)
    except Exception as exc:
        print(f"[embeddings] embed failed ({settings.EMBEDDING_MODEL}): {exc}")
        return None
    if len(_cache) < _CACHE_MAX:
        _cache[k] = vec
    return vec


def embed_batch(texts: list[str]) -> list[list[float] | None]:
    """Embed many strings, one gateway request for the cache-misses. Order of the
    returned vectors matches `texts`. Missing/failed items come back as None."""
    cleaned = [(t or "").strip() for t in texts]
    out: list[list[float] | None] = [None] * len(texts)
    if not any(cleaned) or not is_enabled():
        return out

    misses: list[int] = []
    for i, t in enumerate(cleaned):
        if not t:
            continue
        cached = _cache.get(_key(t))
        if cached is not None:
            out[i] = cached
        else:
            misses.append(i)

    if misses:
        try:
            resp = llm._get_client().embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=[cleaned[i][:_MAX_INPUT_CHARS] for i in misses],
            )
            # Be robust to out-of-order responses — map back by .index.
            data = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
            for pos, item in enumerate(data):
                if pos >= len(misses):
                    break
                i = misses[pos]
                vec = list(item.embedding)
                out[i] = vec
                if len(_cache) < _CACHE_MAX:
                    _cache[_key(cleaned[i])] = vec
        except Exception as exc:
            print(f"[embeddings] batch embed failed ({settings.EMBEDDING_MODEL}): {exc}")
    return out
