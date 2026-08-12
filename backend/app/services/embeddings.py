"""Text embeddings for semantic memory recall.

Two backends, chosen by the *shape of the model name* rather than another flag:

  * `gemini-embedding-001`         → Vertex AI, via ADC (no API key)
  * `azure.text-embedding-3-small` → the OpenAI-compatible gateway in `llm.py`

The gateway namespaces its models with a provider prefix (`azure.`,
`vertex_ai.`), so a bare name means "call Vertex directly". That keeps the
choice in one setting operators already have to get right.

Vectors are only comparable to other vectors from the *same* model, so changing
`EMBEDDING_MODEL` invalidates every stored embedding: recall silently degrades
to lexical-only until `POST /api/memory/reindex` has re-embedded every row.

`EMBEDDING_DIM` is passed to Vertex as `output_dimensionality`, so
`gemini-embedding-001` (natively 3072) is asked for 1536 to match the existing
`vector(1536)` column — no migration required. Truncated Gemini vectors are not
re-normalised by the API, which is fine here because both ranking paths use true
cosine (`_cosine` divides by magnitudes; pgvector uses `vector_cosine_ops`).

Every call is best-effort: if embeddings aren't configured, or the model isn't
available, `embed*` return None and callers degrade to lexical-only recall.
Never raises.

An in-process cache keyed on the content hash avoids re-embedding identical text
within a run (observers re-emit the same summary; reindex re-scans rows).
"""

from __future__ import annotations

import hashlib

from ..config import settings
from . import llm, vertex_llm

_cache: dict[str, list[float]] = {}
_CACHE_MAX = 4096
_MAX_INPUT_CHARS = 8000  # keep well under typical 8k-token embedding limits

# Vertex accepts at least 50 instances per request (verified against
# gemini-embedding-001); chunk below that so a large reindex can't trip a limit.
_VERTEX_BATCH = 25


def _use_vertex() -> bool:
    """A bare model name means Vertex; a provider-prefixed one means the gateway."""
    return bool(settings.EMBEDDING_MODEL) and "." not in settings.EMBEDDING_MODEL


def is_enabled() -> bool:
    """True when a model is set and its backend can actually serve a request."""
    if not settings.EMBEDDING_MODEL:
        return False
    return vertex_llm.is_configured() if _use_vertex() else llm.is_configured()


def backend_name() -> str:
    """For /health and diagnostics."""
    return "vertex" if _use_vertex() else "gateway"


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


# ── backends ────────────────────────────────────────────────────────────────


def _embed_vertex(texts: list[str]) -> list[list[float] | None]:
    from vertexai.language_models import TextEmbeddingModel

    vertex_llm._init()
    model = TextEmbeddingModel.from_pretrained(settings.EMBEDDING_MODEL)

    out: list[list[float] | None] = []
    for start in range(0, len(texts), _VERTEX_BATCH):
        chunk = texts[start : start + _VERTEX_BATCH]
        results = model.get_embeddings(chunk, output_dimensionality=settings.EMBEDDING_DIM)
        out.extend(list(r.values) for r in results)
        if len(out) < start + len(chunk):  # short response — pad so indexes stay aligned
            out.extend([None] * (start + len(chunk) - len(out)))
    return out


def _embed_gateway(texts: list[str]) -> list[list[float] | None]:
    resp = llm._get_client().embeddings.create(model=settings.EMBEDDING_MODEL, input=texts)
    # Be robust to out-of-order responses — map back by .index.
    data = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
    out: list[list[float] | None] = [None] * len(texts)
    for position, item in enumerate(data):
        if position < len(texts):
            out[position] = list(item.embedding)
    return out


def _embed_many(texts: list[str]) -> list[list[float] | None]:
    """Embed a list, returning None per item on failure. Never raises."""
    if not texts:
        return []
    try:
        return (_embed_vertex if _use_vertex() else _embed_gateway)(texts)
    except Exception as exc:
        print(f"[embeddings] {backend_name()} embed failed ({settings.EMBEDDING_MODEL}): {exc}")
        return [None] * len(texts)


# ── public API ──────────────────────────────────────────────────────────────


def embed(text: str) -> list[float] | None:
    """Embed one string. Returns None (never raises) when disabled or on error."""
    text = (text or "").strip()
    if not text or not is_enabled():
        return None
    key = _key(text)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    vec = _embed_many([text[:_MAX_INPUT_CHARS]])[0]
    if vec and len(_cache) < _CACHE_MAX:
        _cache[key] = vec
    return vec


def embed_batch(texts: list[str]) -> list[list[float] | None]:
    """Embed many strings, one request per chunk for the cache-misses. Order of
    the returned vectors matches `texts`. Missing/failed items come back as None."""
    cleaned = [(t or "").strip() for t in texts]
    out: list[list[float] | None] = [None] * len(texts)
    if not any(cleaned) or not is_enabled():
        return out

    misses: list[int] = []
    for i, text in enumerate(cleaned):
        if not text:
            continue
        cached = _cache.get(_key(text))
        if cached is not None:
            out[i] = cached
        else:
            misses.append(i)

    if misses:
        vectors = _embed_many([cleaned[i][:_MAX_INPUT_CHARS] for i in misses])
        for position, i in enumerate(misses):
            vec = vectors[position] if position < len(vectors) else None
            out[i] = vec
            if vec and len(_cache) < _CACHE_MAX:
                _cache[_key(cleaned[i])] = vec
    return out
