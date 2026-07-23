-- Migration: Story layer (ADR-0001)
-- The unit of work under a Task that carries PROGRESS and QUALITATIVE status.
-- This is the level that makes the Client > Project > Task > Story hierarchy
-- self-filling: the agent writes observations from real evidence (email,
-- meeting, Drive), each one carrying a pointer back to that evidence.
--
-- Design notes:
--  * `observations` is JSONB, not a side table. Per-user volume is small (the
--    same assumption kg_nodes / agent_memory already make), the agent-refresh
--    merge stays in one place, and each entry still carries its own id so it is
--    individually addressable.
--  * client_id / engagement_id are DENORMALIZED from the parent task so the
--    roll-up (M2) and per-client views can scope without a join.
--  * ON DELETE CASCADE on task_id: a story is meaningless without its task.
--
-- Run against your Supabase project before using stories in
-- KORA_DATA_BACKEND=supabase. (Mock mode needs no migration.)

CREATE TABLE IF NOT EXISTS stories (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    task_id        UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    client_id      UUID REFERENCES clients(id) ON DELETE SET NULL,
    engagement_id  UUID REFERENCES engagements(id) ON DELETE SET NULL,
    title          TEXT NOT NULL,
    description_md TEXT,
    status         TEXT NOT NULL DEFAULT 'todo',   -- todo|in_progress|blocked|done|cancelled
    progress_pct   SMALLINT NOT NULL DEFAULT 0 CHECK (progress_pct >= 0 AND progress_pct <= 100),

    -- [{id, kind, text, source, source_ref, observed_at, user_edited}]
    -- kind ∈ blocker | going_well | not_going_well
    -- ADR-0001: an entry without source_ref is refused by the application layer.
    observations   JSONB NOT NULL DEFAULT '[]'::jsonb,

    completed_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stories_user_task   ON stories (user_id, task_id);
CREATE INDEX IF NOT EXISTS idx_stories_user_client ON stories (user_id, client_id) WHERE client_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stories_user_status ON stories (user_id, status);

ALTER TABLE stories ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users access own stories"
    ON stories FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
