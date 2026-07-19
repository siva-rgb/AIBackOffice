# Google Butler — Definitive Database Schema

This is the SINGLE source of truth for all Google Butler tables and column additions.
Apply migrations in exact order listed. All new columns are nullable (backward compatible).

Prerequisites: the Butler core tables (clients, engagements, quick_captures, proposals,
retainers, client_notes) from `kora-butler-skill/references/schema.md` must exist first.

---

## Migration 1: google_connections

```sql
CREATE TABLE google_connections (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE UNIQUE,

  -- Encrypted tokens (Fernet-encrypted, base64 strings)
  access_token_enc  TEXT NOT NULL,
  refresh_token_enc TEXT,

  -- User identity from Google
  google_email      TEXT NOT NULL,
  scopes_granted    TEXT[],
  token_expiry      TIMESTAMPTZ,

  -- Drive integration
  kora_folder_id    TEXT,           -- Google Drive folder ID for the "Kora" folder

  -- Consent tracking (GDPR)
  consent_given_at  TIMESTAMPTZ,
  consent_version   TEXT,           -- e.g. "2026-06-01"

  -- Status
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

CREATE INDEX idx_google_connections_user ON google_connections(user_id);
```

---

## Migration 2: email_intel_cache

```sql
CREATE TABLE email_intel_cache (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id               UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id             UUID REFERENCES clients(id) ON DELETE CASCADE,
  client_name           TEXT NOT NULL,

  -- Thread metadata
  thread_count          INTEGER DEFAULT 0,
  last_message_id       TEXT,

  -- AI-extracted intelligence
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

  -- Cache control
  processed_at          TIMESTAMPTZ,
  expires_at            TIMESTAMPTZ,

  UNIQUE (user_id, client_id)
);

ALTER TABLE email_intel_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_email_cache" ON email_intel_cache
  USING (user_id = auth.uid());

CREATE INDEX idx_email_cache_user ON email_intel_cache(user_id, action_needed);
```

---

## Migration 3: drive_doc_cache

```sql
CREATE TABLE drive_doc_cache (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  drive_file_id     TEXT NOT NULL,
  file_name         TEXT,
  mime_type         TEXT,
  doc_type          TEXT,          -- contract|invoice|receipt|transcript|brief|other
  drive_modified_time TEXT,
  processed_at      TIMESTAMPTZ,
  meeting_id        UUID REFERENCES meetings(id) ON DELETE SET NULL,

  UNIQUE (user_id, drive_file_id)
);

ALTER TABLE drive_doc_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_drive_cache" ON drive_doc_cache
  USING (user_id = auth.uid());
```

---

## Migration 4: meetings table

```sql
CREATE TABLE meetings (
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

CREATE INDEX idx_meetings_client ON meetings(client_id, meeting_date DESC);
CREATE INDEX idx_meetings_user_date ON meetings(user_id, meeting_date DESC);
CREATE INDEX idx_meetings_pending ON meetings(user_id, parse_status)
  WHERE parse_status = 'pending';
```

---

## Migration 5: meeting_action_items

```sql
CREATE TABLE meeting_action_items (
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

CREATE INDEX idx_action_items_meeting ON meeting_action_items(meeting_id);
CREATE INDEX idx_action_items_open ON meeting_action_items(user_id, status)
  WHERE status = 'open';
CREATE INDEX idx_action_items_client ON meeting_action_items(client_id)
  WHERE status = 'open';
```

---

## Migration 6: column additions to existing tables

```sql
-- Users table: Google connection status for quick lookups
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS google_connected BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS google_email TEXT;

-- Client notes: link notes created from meetings
ALTER TABLE client_notes
  ADD COLUMN IF NOT EXISTS meeting_id UUID REFERENCES meetings(id) ON DELETE SET NULL;

-- Extend manager_tasks kind CHECK
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

-- Extend agent_logs agent_type CHECK
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
```

---

## Schema relationships (complete)

```
users
  ├── google_connections (1:1)
  ├── clients (1:many)
  │     ├── email_intel_cache (1:1 per client)
  │     ├── meetings (1:many)
  │     │     ├── meeting_action_items (1:many)
  │     │     └── → client_notes (created from meeting)
  │     └── → drive_doc_cache (via client match)
  ├── drive_doc_cache (1:many)
  └── meetings (1:many)
```
