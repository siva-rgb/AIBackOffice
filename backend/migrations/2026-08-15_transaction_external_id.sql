-- Dedupe imported payments by their source id, not by their shape.
--
-- transactions carried UNIQUE(user_id, date, description, amount). For CSV
-- imports that is the right protection: re-uploading the same statement must
-- not double the books.
--
-- For Stripe it silently loses money. Two genuine payments from the same client,
-- on the same day, for the same amount collapse into ONE row — and that is not
-- an exotic case, it is a client settling two equal invoices at once, or two
-- monthly retainers of the same value. The second payment simply never appears,
-- understating revenue with no error anywhere.
--
-- The fix keeps both rules and applies each where it belongs:
--   * rows WITHOUT an external id (CSV, manual, bank) keep the old shape rule;
--   * rows WITH one dedupe on that id, so identical-looking Stripe payments are
--     stored separately and re-syncing still cannot duplicate them.
--
-- A plain UNIQUE constraint cannot be conditional, so both become partial
-- unique indexes.

ALTER TABLE public.transactions
  ADD COLUMN IF NOT EXISTS external_id TEXT;

COMMENT ON COLUMN public.transactions.external_id IS
  'Source-system id (e.g. Stripe balance transaction txn_…). Unique per user when present.';

-- Drop the unconditional constraint. Named by Postgres from the table and
-- columns when the table was created; IF EXISTS keeps this migration safe to
-- re-run and safe on a database where it was already removed.
ALTER TABLE public.transactions
  DROP CONSTRAINT IF EXISTS transactions_user_id_date_description_amount_key;

-- CSV / manual / bank rows: unchanged protection.
CREATE UNIQUE INDEX IF NOT EXISTS transactions_shape_unique
  ON public.transactions (user_id, date, description, amount)
  WHERE external_id IS NULL;

-- Stripe and any future connector: one row per source record.
CREATE UNIQUE INDEX IF NOT EXISTS transactions_external_id_unique
  ON public.transactions (user_id, external_id)
  WHERE external_id IS NOT NULL;

-- Lookups by source id (the sync checks these on every run).
CREATE INDEX IF NOT EXISTS transactions_external_id_idx
  ON public.transactions (user_id, external_id)
  WHERE external_id IS NOT NULL;
