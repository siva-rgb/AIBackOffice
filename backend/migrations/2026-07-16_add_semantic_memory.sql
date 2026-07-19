-- Migration: Semantic / hybrid agent memory (agent_memory)
-- A durable, embeddable memory index the agents query when they need PAST
-- context for planning/decisions — complementing the structured Playbook and
-- graph (which answer by exact key/name). recall() ranks rows by MEANING:
-- semantic similarity (embeddings) + lexical overlap + salience + recency.
--
-- Design: embeddings are stored as JSONB (list[float]); the app loads a user's
-- candidate rows and scores in Python — same "small per-user memory" assumption
-- as kg_nodes/kg_edges. No pgvector extension required. If a user's memory grows
-- large, add `CREATE EXTENSION vector`, an `embedding vector(N)` column, an
-- ivfflat/hnsw index and a `match_agent_memory` RPC — the service interface
-- (remember/recall) stays identical.
--
-- Run against your Supabase project before using recall in KORA_DATA_BACKEND=supabase.
-- (Mock mode needs no migration.)

CREATE TABLE IF NOT EXISTS agent_memory (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,          -- playbook|graph_fact|email_intel|meeting|note|decision|action
    client_id   UUID REFERENCES clients(id) ON DELETE SET NULL,
    ref_type    TEXT,                   -- source table/record type (provenance)
    ref_id      TEXT,                   -- source record id → idempotent upsert
    content     TEXT NOT NULL,          -- the recallable summary/fact text
    embedding   JSONB,                  -- list[float]; NULL until embedded (lexical recall still works)
    salience    NUMERIC(4,3) NOT NULL DEFAULT 0.5 CHECK (salience >= 0 AND salience <= 1),
    source      TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotency: one row per (user, kind, ref_id) so re-ingest/reindex updates in place.
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_memory_ref
    ON agent_memory (user_id, kind, ref_id)
    WHERE ref_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_memory_user_kind
    ON agent_memory (user_id, kind);
CREATE INDEX IF NOT EXISTS idx_agent_memory_user_client
    ON agent_memory (user_id, client_id)
    WHERE client_id IS NOT NULL;

-- Row-level security: users only see their own memory.
ALTER TABLE agent_memory ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users access own agent memory"
    ON agent_memory FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
