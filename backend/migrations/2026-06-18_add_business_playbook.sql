-- Migration: Add business_playbook table for Agent Intelligence (Playbook feature)
-- Run this against your Supabase project before enabling KORA_DATA_BACKEND=supabase

-- 1. Create the main table
CREATE TABLE IF NOT EXISTS business_playbook (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    category    TEXT NOT NULL CHECK (category IN (
                    'correction', 'user_preference', 'client_intelligence',
                    'business_pattern', 'business_rule', 'extracted_fact'
                )),
    client_id   UUID REFERENCES clients(id) ON DELETE SET NULL,
    key         TEXT NOT NULL,
    value       JSONB NOT NULL DEFAULT '{}',
    summary     TEXT,
    confidence  NUMERIC(4,3) NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    source      TEXT NOT NULL DEFAULT 'observation' CHECK (source IN (
                    'onboarding', 'observation', 'correction', 'extraction', 'pattern_detection'
                )),
    observation_count  INTEGER NOT NULL DEFAULT 1,
    first_observed_at  TIMESTAMPTZ,
    last_observed_at   TIMESTAMPTZ,
    expires_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Unique constraint: one entry per (user, category, key, client)
ALTER TABLE business_playbook
    ADD CONSTRAINT business_playbook_unique_entry
    UNIQUE (user_id, category, key, client_id);

-- 3. Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_playbook_user_category
    ON business_playbook (user_id, category);

CREATE INDEX IF NOT EXISTS idx_playbook_user_confidence
    ON business_playbook (user_id, confidence DESC);

CREATE INDEX IF NOT EXISTS idx_playbook_user_client
    ON business_playbook (user_id, client_id)
    WHERE client_id IS NOT NULL;

-- 4. Row-level security: users can only see their own entries
ALTER TABLE business_playbook ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users access own playbook entries"
    ON business_playbook
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- 5. Extend agent_logs agent_type CHECK to include 'playbook'
-- (Only run if your agent_logs table has a strict CHECK constraint on agent_type.
--  Skip this step if it's just a TEXT column.)
ALTER TABLE agent_logs DROP CONSTRAINT IF EXISTS agent_logs_agent_type_check;
ALTER TABLE agent_logs ADD CONSTRAINT agent_logs_agent_type_check
    CHECK (agent_type IN (
        'bookkeeper','invoice_follow_up','contract_generator','cashflow_forecaster',
        'alert_generator','cross_module','supervisor','chat','butler','butler_gmail',
        'butler_drive','butler_calendar','meeting_agent','gmail_agent','calendar_agent',
        'playbook'
    ));
