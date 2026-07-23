-- Migration: client_view_cache (M3 — PM agent fan-out)
-- The agent-composed one-pager per client. Four role-scoped analysts run in
-- parallel, a DETERMINISTIC code merge assembles their prose around
-- ground-truth numbers, and the result is cached here so a page load costs
-- ZERO LLM calls (invariant client_view_refresh_is_cached).
--
-- Design notes:
--  * Keyed by (user_id, client_id) — one current view per client. A refresh
--    upserts; GET reads. No history kept (the ledger is the source of truth;
--    this is a derived, disposable cache).
--  * `view` holds the composed sections + headline metrics; `token_cost` holds
--    the measured fan-out spend so the budget gate is observable in prod.
--  * ON DELETE CASCADE on both FKs: a cached view is meaningless once its
--    client (or user) is gone.
--
-- Run against Supabase before using the client view in KORA_DATA_BACKEND=supabase.

CREATE TABLE IF NOT EXISTS client_view_cache (
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    client_id    UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    view         JSONB NOT NULL DEFAULT '{}'::jsonb,
    token_cost   JSONB NOT NULL DEFAULT '{}'::jsonb,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, client_id)
);

CREATE INDEX IF NOT EXISTS idx_client_view_user ON client_view_cache (user_id);

ALTER TABLE client_view_cache ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users access own client views"
    ON client_view_cache FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
