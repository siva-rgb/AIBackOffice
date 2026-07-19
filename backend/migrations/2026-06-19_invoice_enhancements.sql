-- Migration: Invoice enhancements (invoice_artifact)
-- New columns on invoices, users, clients for professional PDF + real email delivery.
-- All columns are nullable — backward-compatible with existing data.
-- Run once in the Supabase SQL editor before using KORA_DATA_BACKEND=supabase.

-- ── Invoice table additions ──────────────────────────────────────────────────

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS invoice_date DATE;
-- Backfill:
-- UPDATE invoices SET invoice_date = created_at::date WHERE invoice_date IS NULL;

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_terms TEXT;
-- "Net 14", "Net 30", "Due on receipt", etc.

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_terms_days INTEGER;

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS client_address TEXT;

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS client_tax_id TEXT;

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS po_number TEXT;

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS pdf_path TEXT;

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS email_message_id TEXT;

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS amount_paid NUMERIC(12,2) DEFAULT 0;

-- ── User additions (sender address on invoices) ──────────────────────────────

ALTER TABLE users ADD COLUMN IF NOT EXISTS business_address TEXT;

ALTER TABLE users ADD COLUMN IF NOT EXISTS tax_id TEXT;

ALTER TABLE users ADD COLUMN IF NOT EXISTS invoice_footer TEXT;

-- ── Client table additions ────────────────────────────────────────────────────

ALTER TABLE clients ADD COLUMN IF NOT EXISTS billing_address TEXT;

ALTER TABLE clients ADD COLUMN IF NOT EXISTS tax_id TEXT;

-- ── agent_logs agent_type CHECK — extend for email delivery ─────────────────
-- email_service.py logs 'email_delivery' (invoice send) and 'morning_digest'.
-- Run only if agent_logs has the strict CHECK constraint.

ALTER TABLE agent_logs DROP CONSTRAINT IF EXISTS agent_logs_agent_type_check;
ALTER TABLE agent_logs ADD CONSTRAINT agent_logs_agent_type_check
    CHECK (agent_type IN (
        'bookkeeper','invoice_follow_up','contract_generator','cashflow_forecaster',
        'alert_generator','cross_module','supervisor','chat','butler','butler_gmail',
        'butler_drive','butler_calendar','meeting_agent','gmail_agent','calendar_agent',
        'playbook','email_delivery','morning_digest'
    ));
