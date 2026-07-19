-- Migration: link Drive documents to Butler clients.
-- Part of "Butler as the communication hub" — Drive was the only comms surface
-- with no client association. Adds a nullable client_id to the drive cache so the
-- per-client Drive tab can filter to one client's files. Populated best-effort
-- during sync (services/drive_intel._resolve_client_id): file-name match, else
-- the document body's client name/email.

ALTER TABLE drive_doc_cache
    ADD COLUMN IF NOT EXISTS client_id UUID REFERENCES clients(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_drive_doc_cache_user_client
    ON drive_doc_cache (user_id, client_id)
    WHERE client_id IS NOT NULL;
