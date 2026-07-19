-- Migration: Agent Graph Memory (kg_nodes + kg_edges)
-- Part 2 of the Business Profile v2 + Graph Memory feature.
-- A per-user knowledge graph the agents traverse for entities and their
-- relationships (client↔invoice↔contract↔meeting↔fact). Source of truth is
-- Postgres; the app materializes it from existing rows (idempotent sync) and
-- ingests learned facts. No graph DB / no new infra — plain adjacency tables,
-- same dual-backend + RLS conventions as business_playbook.
--
-- Run against your Supabase project before using the graph features in
-- KORA_DATA_BACKEND=supabase.

-- 1. Nodes ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kg_nodes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    node_type   TEXT NOT NULL,          -- business|owner|client|engagement|invoice|contract|meeting|proposal|retainer|offering|persona|fact|preference|goal
    entity_id   TEXT,                   -- source-row id for entity nodes; NULL for abstract nodes (fact/preference/goal/persona/offering)
    label       TEXT NOT NULL,
    props       JSONB NOT NULL DEFAULT '{}',
    salience    NUMERIC(4,3) NOT NULL DEFAULT 0.5 CHECK (salience >= 0 AND salience <= 1),
    first_seen  TIMESTAMPTZ,
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Identity: one node per entity (by entity_id), one node per concept (by label).
-- Two partial unique indexes so the two node styles never collide.
CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_nodes_entity
    ON kg_nodes (user_id, node_type, entity_id)
    WHERE entity_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_nodes_concept
    ON kg_nodes (user_id, node_type, label)
    WHERE entity_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_kg_nodes_user_type   ON kg_nodes (user_id, node_type);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_user_salience ON kg_nodes (user_id, salience DESC);

-- 2. Edges ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kg_edges (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    src_id      UUID NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    dst_id      UUID NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    rel         TEXT NOT NULL,          -- OWNS|WORKS_ON|HAS_ENGAGEMENT|ISSUED|PAID|SIGNED|MET_ABOUT|PROPOSED|RETAINS|OFFERS|INTERESTED_IN|HAS_PERSONA|PREFERS|PURSUES_GOAL|MENTIONS|RELATED_TO
    weight      NUMERIC NOT NULL DEFAULT 1,
    props       JSONB NOT NULL DEFAULT '{}',
    first_seen  TIMESTAMPTZ,
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE kg_edges
    ADD CONSTRAINT kg_edges_unique_edge UNIQUE (user_id, src_id, dst_id, rel);

CREATE INDEX IF NOT EXISTS idx_kg_edges_user_src ON kg_edges (user_id, src_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_user_dst ON kg_edges (user_id, dst_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_user_rel ON kg_edges (user_id, rel);

-- 3. Row-level security: users only see their own graph ---------------------
ALTER TABLE kg_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE kg_edges ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users access own kg nodes"
    ON kg_nodes FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users access own kg edges"
    ON kg_edges FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
