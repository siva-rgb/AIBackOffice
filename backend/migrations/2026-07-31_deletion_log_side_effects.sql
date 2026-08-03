-- M9 follow-up — persist the per-side-effect outcome map on the deletion audit.
--
-- The GDPR erasure endpoint runs several best-effort steps (Google token
-- revoke, Stripe cancel, GCS wipe, auth-identity delete). Recording their
-- outcomes makes the audit row actually able to prove WHAT happened, not just
-- that a request came in. Values are status strings only (e.g. "revoked",
-- "not_applicable: no subscription", "failed: TimeoutError") — NO PII, keeping
-- deletion_log's no-PII contract intact.
--
-- Backward-compatible: `record_deletion` writes this column when present and
-- silently falls back to the old row shape if the migration hasn't been applied.

ALTER TABLE public.deletion_log
  ADD COLUMN IF NOT EXISTS side_effects JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.deletion_log.side_effects IS
  'Per-step erasure outcomes (status strings only, no PII): '
  'google_revoke, stripe_cancel, gcs_delete, auth_delete, deletion_log.';
