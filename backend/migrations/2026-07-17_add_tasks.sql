-- Migration: Task / project ledger (tasks)
-- The canonical record of client work. KORA OWNS this table; external PM tools
-- (Notion first) mirror it via external_ref — so the agents always read/write a
-- single source of truth and sync can never fight over ownership.
--
-- Why it exists: previously "tasks" were scattered across manager_tasks (the
-- approval queue), meeting_action_items and quick captures, and `engagements`
-- carried only a coarse status label — so nothing guaranteed a commitment made
-- in an email or meeting was actually tracked to completion.
--
-- Run against your Supabase project before using the task ledger in
-- KORA_DATA_BACKEND=supabase. (Mock mode needs no migration.)

CREATE TABLE IF NOT EXISTS tasks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    client_id     UUID REFERENCES clients(id) ON DELETE SET NULL,
    engagement_id UUID REFERENCES engagements(id) ON DELETE SET NULL,
    title         TEXT NOT NULL,
    description_md TEXT,
    status        TEXT NOT NULL DEFAULT 'todo',      -- todo|in_progress|blocked|done|cancelled
    priority      TEXT NOT NULL DEFAULT 'medium',    -- low|medium|high|urgent
    due_date      DATE,
    owner         TEXT,                              -- "me" | "client" | person
    source        TEXT NOT NULL DEFAULT 'manual',    -- manual|meeting|email|contract|agent|notion
    source_ref    TEXT,                              -- idempotency key for auto-captured tasks
    external_ref  TEXT,                              -- Notion page id (mirror)
    external_url  TEXT,
    synced_at     TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Auto-capture idempotency: one task per originating record, so re-running a
-- meeting/email sync updates in place instead of duplicating.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_source_ref
    ON tasks (user_id, source_ref)
    WHERE source_ref IS NOT NULL;

-- Sync idempotency: one task per mirrored external page.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_external_ref
    ON tasks (user_id, external_ref)
    WHERE external_ref IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_user_status  ON tasks (user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_user_client  ON tasks (user_id, client_id) WHERE client_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_user_due     ON tasks (user_id, due_date)  WHERE due_date IS NOT NULL;

ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users access own tasks"
    ON tasks FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
