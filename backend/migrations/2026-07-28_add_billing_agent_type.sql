-- Migration: Add 'billing' to agent_logs.agent_type CHECK constraint
-- stripe_billing.py, stripe_connect.py, stripe_sync.py log agent_type='billing'.
-- The latest CHECK (2026-06-19_invoice_enhancements.sql) omitted it — INSERTs 500 on Supabase.
-- Idempotent: DROP IF EXISTS + ADD per existing migration pattern.

ALTER TABLE agent_logs DROP CONSTRAINT IF EXISTS agent_logs_agent_type_check;
ALTER TABLE agent_logs ADD CONSTRAINT agent_logs_agent_type_check
    CHECK (agent_type IN (
        'bookkeeper','invoice_follow_up','contract_generator','cashflow_forecaster',
        'alert_generator','cross_module','supervisor','chat','butler','butler_gmail',
        'butler_drive','butler_calendar','meeting_agent','gmail_agent','calendar_agent',
        'playbook','email_delivery','morning_digest','billing'
    ));
