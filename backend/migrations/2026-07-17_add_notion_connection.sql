-- Migration: Notion connection (task ledger mirror)
-- Per-user link to a Notion workspace. KORA's `tasks` table stays CANONICAL;
-- Notion mirrors it. `tasks_db_id` is the KORA-provisioned Tasks database — we
-- create it with our own schema so a user renaming a property can't silently
-- break sync.
--
-- access_token is stored ENCRYPTED (services/token_encryption.py), same as the
-- Google OAuth tokens.
--
-- Run against your Supabase project before connecting Notion in
-- KORA_DATA_BACKEND=supabase. (Mock mode needs no migration.)

CREATE TABLE IF NOT EXISTS notion_connections (
    user_id        UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    access_token   TEXT,              -- Fernet-encrypted
    workspace_id   TEXT,
    workspace_name TEXT,
    bot_id         TEXT,
    tasks_db_id    TEXT,              -- the KORA-provisioned Tasks database
    connected      BOOLEAN NOT NULL DEFAULT FALSE,
    last_sync_at   TIMESTAMPTZ,
    last_error     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE notion_connections ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users access own notion connection"
    ON notion_connections FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
