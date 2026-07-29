-- M9 — GDPR/CCPA compliance infrastructure.
--
-- (1) deletion_log: append-only audit table proving a deletion request was
--     honored. Intentionally carries NO PII and NO user_id FK — the request id
--     is a random UUID so even correlation with timing windows is bounded.
--     RLS disabled because there is no tenant to scope to: writes happen via
--     the service-role key, and no read path exists for this table from the
--     app surface.
--
-- (2) users.consent_version + users.consent_given_at: capture the policy
--     version the user agreed to and when. Defaults are NULL until the user
--     finishes onboarding or hits POST /api/account/consent.

-- ── (1) deletion_log ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.deletion_log (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  deleted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reason       TEXT NOT NULL DEFAULT 'user_request',
  -- Aggregated counts so the audit row is self-describing. No row data.
  tables_cleared      JSONB NOT NULL DEFAULT '{}'::jsonb,
  files_deleted_count INTEGER NOT NULL DEFAULT 0,
  user_request_id     UUID NOT NULL DEFAULT uuid_generate_v4()
);

COMMENT ON TABLE public.deletion_log IS
  'Append-only GDPR/CCPA audit. No PII, no user_id FK. '
  'See .genesis/checkpoints/M9.md.';

-- ── (2) users.consent_* ─────────────────────────────────────────────────────
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS consent_version   TEXT,
  ADD COLUMN IF NOT EXISTS consent_given_at  TIMESTAMPTZ;

COMMENT ON COLUMN public.users.consent_version  IS 'Policy version the user agreed to (e.g. 2026-06-01).';
COMMENT ON COLUMN public.users.consent_given_at IS 'Timestamp of the most recent consent capture.';
