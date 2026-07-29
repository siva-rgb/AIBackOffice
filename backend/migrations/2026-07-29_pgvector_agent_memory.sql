-- Migration: pgvector ANN for agent_memory
-- (added 2026-07-29 by M10 — Memory System → pgvector)
--
-- Adds an indexed `embedding_vec vector(N)` column alongside the existing
-- JSONB `embedding` column. The JSONB column is retained: it is the canonical
-- write target (the `embedding` parameter in upsert_agent_memory), it keeps
-- mock-mode parity (no extension needed), and existing rows already have
-- JSONB vectors populated. The new column is the ANN-indexed one; recall
-- switches over to it via `AGENT_MEMORY_VECTOR_BACKEND=pgvector`.
--
-- Index choice: HNSW. Per-user memory is small (100s–1000s rows); HNSW has no
-- training step, supports incremental inserts without rebuild, and matches
-- IVFFLAT on recall at this scale. vector_cosine_ops matches the cosine
-- similarity used by memory_recall._cosine().
--
-- The match_agent_memory RPC is SECURITY DEFINER + auth.uid() filtering so it
-- composes correctly with the existing RLS policy on agent_memory; the
-- caller's JWT is still authoritative.
--
-- Dimension: 1536 (text-embedding-3-small / ada-002). To swap models with a
-- different dimensionality, alter the column type and re-backfill:
--   ALTER TABLE agent_memory ALTER COLUMN embedding_vec TYPE vector(<new_dim>);
--   python -m scripts.backfill_agent_memory_vectors --reset
-- (Re-issuing dimension is recorded as FU-M10-dim-change-migration.)
--
-- Run against your Supabase project before flipping
-- AGENT_MEMORY_VECTOR_BACKEND=pgvector. (Mock mode needs no migration.)

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE agent_memory
    ADD COLUMN IF NOT EXISTS embedding_vec vector(1536);

-- HNSW index. m=16, ef_construction=64 are pgvector's documented defaults and
-- a sane starting point for the per-user scale; operators can tune at the
-- session level (`SET hnsw.ef_search = 100;`) without re-indexing.
CREATE INDEX IF NOT EXISTS idx_agent_memory_embedding_vec_hnsw
    ON agent_memory
    USING hnsw (embedding_vec vector_cosine_ops);

-- match_agent_memory: ANN over a single tenant's rows, with optional
-- client_id + kind narrowing. Returned as TABLE for composability (Supabase
-- RPC selects on TABLE-shaped functions cleanly).
--
-- The function checks auth.uid() = user_id explicitly so it is safe to mark
-- SECURITY DEFINER (otherwise an attacker with a malicious JWT could call it
-- with any user_id). The check is inside the function body, not just the
-- outer RLS policy, because SECURITY DEFINER bypasses RLS for the function's
-- own reads — RLS alone is not enough here.
CREATE OR REPLACE FUNCTION public.match_agent_memory(
    p_user_id       UUID,
    p_query_embedding vector(1536),
    p_match_threshold float DEFAULT 0.0,
    p_match_count     int   DEFAULT 20,
    p_filter_client   UUID  DEFAULT NULL,
    p_filter_kinds    TEXT[] DEFAULT NULL
)
RETURNS TABLE (
    id           UUID,
    kind         TEXT,
    client_id    UUID,
    ref_type     TEXT,
    ref_id       TEXT,
    content      TEXT,
    salience     NUMERIC,
    source       TEXT,
    metadata     JSONB,
    created_at   TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ,
    similarity   float
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_auth uuid := auth.uid();
BEGIN
    IF v_auth IS NULL OR v_auth <> p_user_id THEN
        -- Silent empty result for cross-tenant probes; do not leak the existence
        -- of another tenant's memory to a forged user_id argument.
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        am.id,
        am.kind,
        am.client_id,
        am.ref_type,
        am.ref_id,
        am.content,
        am.salience,
        am.source,
        am.metadata,
        am.created_at,
        am.updated_at,
        (1.0 - (am.embedding_vec <=> p_query_embedding))::float AS similarity
    FROM agent_memory am
    WHERE am.user_id = p_user_id
      AND am.embedding_vec IS NOT NULL
      AND (p_filter_client IS NULL OR am.client_id = p_filter_client)
      AND (p_filter_kinds  IS NULL OR am.kind = ANY(p_filter_kinds))
      AND (1.0 - (am.embedding_vec <=> p_query_embedding)) >= p_match_threshold
    ORDER BY am.embedding_vec <=> p_query_embedding
    LIMIT GREATEST(p_match_count, 1);
END;
$$;

COMMENT ON FUNCTION public.match_agent_memory IS
    'pgvector ANN over a tenant-scoped slice of agent_memory. SECURITY DEFINER '
    'with an explicit auth.uid() check inside the body — do not weaken to a '
    'plain `SECURITY INVOKER` + RLS-only path.';
