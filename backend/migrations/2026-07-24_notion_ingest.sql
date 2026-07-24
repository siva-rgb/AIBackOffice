-- Migration: Notion read-only intelligence source (M9)
-- Notion changes from a two-way task MIRROR to a read-only INTELLIGENCE source:
-- the user picks pages, Kora reads them and embeds the content into agent_memory
-- (kind='notion'). Kora never writes back.
--
-- `ingest_page_ids` holds the user's chosen page/database ids to read. The old
-- `tasks_db_id` column is now unused (the write side is removed) — left in place
-- so this migration is additive and non-destructive; a later cleanup can drop it.

ALTER TABLE notion_connections
    ADD COLUMN IF NOT EXISTS ingest_page_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS last_ingest_at  TIMESTAMPTZ;
