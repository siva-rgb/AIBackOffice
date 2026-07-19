-- Google Butler schema migrations (email_skill/schema.md)
-- Apply in order. Prerequisites: Butler core tables must exist first
-- (clients, engagements, quick_captures, proposals, retainers, client_notes).

-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 1: google_connections
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS google_connections (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE UNIQUE,
  access_token_enc  TEXT NOT NULL,
  refresh_token_enc TEXT,
  google_email      TEXT NOT NULL,
  scopes_granted    TEXT[],
  token_expiry      TIMESTAMPTZ,
  kora_folder_id    TEXT,
  consent_given_at  TIMESTAMPTZ,
  consent_version   TEXT,
  connected         BOOLEAN NOT NULL DEFAULT TRUE,
  last_used_at      TIMESTAMPTZ,
  last_error        TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE google_connections ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_connections" ON google_connections
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE INDEX IF NOT EXISTS idx_google_connections_user ON google_connections(user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 2: email_intel_cache
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS email_intel_cache (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id               UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id             UUID REFERENCES clients(id) ON DELETE CASCADE,
  client_name           TEXT NOT NULL,
  thread_count          INTEGER DEFAULT 0,
  last_message_id       TEXT,
  last_contact_days     INTEGER,
  last_contact_direction TEXT CHECK (last_contact_direction IN
                          ('from_client','from_me','unknown')),
  sentiment             TEXT CHECK (sentiment IN
                          ('positive','neutral','cautious','strained')),
  relationship_health   TEXT CHECK (relationship_health IN
                          ('strong','healthy','needs_attention','at_risk','unknown')),
  summary               TEXT,
  action_needed         BOOLEAN DEFAULT FALSE,
  action_description    TEXT,
  commitments_pending   JSONB DEFAULT '[]'::jsonb,
  financial_mentions    JSONB DEFAULT '[]'::jsonb,
  open_questions        JSONB DEFAULT '[]'::jsonb,
  processed_at          TIMESTAMPTZ,
  expires_at            TIMESTAMPTZ,
  UNIQUE (user_id, client_id)
);

ALTER TABLE email_intel_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_email_cache" ON email_intel_cache
  USING (user_id = auth.uid());

CREATE INDEX IF NOT EXISTS idx_email_cache_user ON email_intel_cache(user_id, action_needed);

-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 4: meetings (must precede drive_doc_cache which references it)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meetings (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id         UUID REFERENCES clients(id) ON DELETE SET NULL,
  engagement_id     UUID REFERENCES engagements(id) ON DELETE SET NULL,
  title             TEXT NOT NULL,
  meeting_type      TEXT NOT NULL DEFAULT 'call'
    CHECK (meeting_type IN ('call','video','in_person','async')),
  meeting_date      TIMESTAMPTZ NOT NULL,
  duration_minutes  INTEGER,
  attendees         JSONB,
  google_event_id   TEXT,
  meet_link         TEXT,
  source            TEXT NOT NULL DEFAULT 'manual'
    CHECK (source IN ('transcript_upload','quick_capture','calendar_import',
                      'drive_transcript','manual')),
  raw_transcript    TEXT,
  raw_notes         TEXT,
  parse_status      TEXT NOT NULL DEFAULT 'pending'
    CHECK (parse_status IN ('pending','parsed','failed','partial')),
  summary           TEXT,
  decisions         JSONB,
  commitments       JSONB,
  risks_flagged     JSONB,
  next_steps        JSONB,
  sentiment         TEXT,
  ai_confidence     NUMERIC(3,2),
  followup_email_sent   BOOLEAN DEFAULT FALSE,
  followup_queued_at    TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_meetings" ON meetings
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE INDEX IF NOT EXISTS idx_meetings_client ON meetings(client_id, meeting_date DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_user_date ON meetings(user_id, meeting_date DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_pending ON meetings(user_id, parse_status)
  WHERE parse_status = 'pending';

-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 3: drive_doc_cache (after meetings)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS drive_doc_cache (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  drive_file_id     TEXT NOT NULL,
  file_name         TEXT,
  mime_type         TEXT,
  doc_type          TEXT,
  drive_modified_time TEXT,
  processed_at      TIMESTAMPTZ,
  meeting_id        UUID REFERENCES meetings(id) ON DELETE SET NULL,
  UNIQUE (user_id, drive_file_id)
);

ALTER TABLE drive_doc_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_drive_cache" ON drive_doc_cache
  USING (user_id = auth.uid());

-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 5: meeting_action_items
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meeting_action_items (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  meeting_id    UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  client_id     UUID REFERENCES clients(id) ON DELETE SET NULL,
  description   TEXT NOT NULL,
  owner         TEXT NOT NULL DEFAULT 'me'
    CHECK (owner IN ('me','client','both','third_party')),
  due_date      DATE,
  priority      TEXT DEFAULT 'medium'
    CHECK (priority IN ('high','medium','low')),
  status        TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','in_progress','done','cancelled')),
  completed_at  TIMESTAMPTZ,
  manager_task_id UUID,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE meeting_action_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_action_items" ON meeting_action_items
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE INDEX IF NOT EXISTS idx_action_items_meeting ON meeting_action_items(meeting_id);
CREATE INDEX IF NOT EXISTS idx_action_items_open ON meeting_action_items(user_id, status)
  WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_action_items_client ON meeting_action_items(client_id)
  WHERE status = 'open';

-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 6: column additions to existing tables
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS google_connected BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS google_email TEXT;

ALTER TABLE client_notes
  ADD COLUMN IF NOT EXISTS meeting_id UUID REFERENCES meetings(id) ON DELETE SET NULL;

-- Extend manager_tasks.kind CHECK to include Google Butler action kinds.
ALTER TABLE manager_tasks
  DROP CONSTRAINT IF EXISTS manager_tasks_kind_check;
ALTER TABLE manager_tasks
  ADD CONSTRAINT manager_tasks_kind_check
  CHECK (kind IN (
    'send_followup','send_demand','send_contract','writeoff_invoice',
    'review_contract','propose_write_off','send_proposal',
    'send_email_gmail',
    'create_calendar_event',
    'send_meeting_followup'
  ));

-- Extend agent_logs.agent_type CHECK for Google Butler agents.
ALTER TABLE agent_logs
  DROP CONSTRAINT IF EXISTS agent_logs_agent_type_check;
ALTER TABLE agent_logs
  ADD CONSTRAINT agent_logs_agent_type_check
  CHECK (agent_type IN (
    'bookkeeper','invoice_follow_up','contract_generator',
    'cashflow_forecaster','alert_generator','cross_module',
    'supervisor','chat','butler',
    'butler_gmail','butler_drive','butler_calendar',
    'meeting_agent','gmail_agent','calendar_agent'
  ));
