# Butler — Database Schema Reference

All migrations run via `supabase db push` or directly in the Supabase SQL editor.
Apply in the order listed — each depends on the previous.

---

## Migration 1: clients table

```sql
-- Run first. clients is referenced by all other new tables.
CREATE TABLE clients (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

  -- Identity
  name            TEXT NOT NULL,
  email           TEXT,
  phone           TEXT,
  company         TEXT,
  industry        TEXT,

  -- Classification
  client_type     TEXT NOT NULL DEFAULT 'individual'
                  CHECK (client_type IN ('individual','company','agency','marketplace')),
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','inactive','prospect','churned')),

  -- Context for the butler agent
  what_we_do      TEXT,          -- one sentence: "we build their Shopify store"
  notes_md        TEXT,          -- freeform additional context
  timezone        TEXT,
  currency        TEXT DEFAULT 'USD',

  -- Health (computed by butler agent, never trust client input)
  health_score    INTEGER DEFAULT 100 CHECK (health_score BETWEEN 0 AND 100),
  health_label    TEXT DEFAULT 'on_track'
                  CHECK (health_label IN ('on_track','at_risk','needs_attention','critical')),
  health_updated_at TIMESTAMPTZ,

  -- Timestamps
  last_activity_at  TIMESTAMPTZ,   -- updated whenever any note, invoice, or engagement changes
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS: users see only their own clients
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_clients" ON clients
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- Indexes
CREATE INDEX idx_clients_user_id ON clients(user_id);
CREATE INDEX idx_clients_status ON clients(user_id, status);
CREATE INDEX idx_clients_health ON clients(user_id, health_score);
```

---

## Migration 2: engagements table

```sql
-- Lightweight "what work is happening" context. NOT a task manager.
-- One record per active piece of work per client.
CREATE TABLE engagements (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id       UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,

  -- What this engagement is
  title           TEXT NOT NULL,           -- "Website redesign", "Monthly SEO retainer"
  description_md  TEXT,                   -- one paragraph max, plain English
  engagement_type TEXT NOT NULL DEFAULT 'project'
                  CHECK (engagement_type IN ('project','retainer','one_off','ongoing')),

  -- Status (deliberately simple — no subtasks)
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('planning','active','on_track','at_risk','paused','done','cancelled')),

  -- Timeline and money
  start_date      DATE,
  target_end_date DATE,
  budget          NUMERIC(12,2),
  budget_currency TEXT DEFAULT 'USD',
  value_delivered NUMERIC(12,2) DEFAULT 0, -- invoiced so far against this engagement

  -- Cross-module links (all nullable — backward compatible)
  contract_id     UUID REFERENCES contracts(id) ON DELETE SET NULL,
  proposal_id     UUID,           -- FK added after proposals table exists (migration 4)

  -- Timestamps
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE engagements ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_engagements" ON engagements
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE INDEX idx_engagements_client ON engagements(client_id);
CREATE INDEX idx_engagements_status ON engagements(user_id, status);
```

---

## Migration 3: quick_captures table

```sql
-- Raw freeform notes before and after AI parsing.
-- Never delete raw_text — it is the source of truth if parsing fails.
CREATE TABLE quick_captures (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

  -- Input
  raw_text        TEXT NOT NULL,           -- exactly what the user typed/said
  source          TEXT NOT NULL DEFAULT 'web'
                  CHECK (source IN ('web','mobile','email','sms')),

  -- AI parsing output
  parse_status    TEXT NOT NULL DEFAULT 'pending'
                  CHECK (parse_status IN ('pending','parsed','failed','partial')),
  parsed_intent   TEXT,          -- 'client_update' | 'new_client' | 'engagement_update' |
                                 -- 'note' | 'financial' | 'proposal' | 'unknown'
  parsed_entities JSONB,         -- extracted: {client_name, amount, date, action, ...}
  ai_confidence   NUMERIC(3,2),  -- 0.0-1.0

  -- What the AI actually did with this note
  actions_taken   JSONB,         -- [{type: 'updated_engagement', id: '...', field: 'status'}, ...]
  requires_review BOOLEAN DEFAULT FALSE,   -- true when AI confidence < 0.7

  -- Timestamps
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  parsed_at       TIMESTAMPTZ
);

ALTER TABLE quick_captures ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_captures" ON quick_captures
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE INDEX idx_captures_user_pending ON quick_captures(user_id, parse_status)
  WHERE parse_status IN ('pending', 'failed', 'partial');
CREATE INDEX idx_captures_review ON quick_captures(user_id, requires_review)
  WHERE requires_review = TRUE;
```

---

## Migration 4: proposals table

```sql
-- Pre-contract documents. Feeds contract_generator when accepted.
CREATE TABLE proposals (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id       UUID REFERENCES clients(id) ON DELETE SET NULL,

  -- Identity
  title           TEXT NOT NULL,
  proposal_number TEXT,          -- e.g. "PROP-2026-001"

  -- Content (AI-generated from user inputs)
  scope_md        TEXT,          -- what you're proposing to do
  deliverables_md TEXT,          -- specific outputs
  timeline_md     TEXT,          -- timeline and milestones
  content_md      TEXT,          -- full generated proposal markdown

  -- Pricing
  total_amount    NUMERIC(12,2),
  currency        TEXT DEFAULT 'USD',
  pricing_type    TEXT DEFAULT 'fixed'
                  CHECK (pricing_type IN ('fixed','hourly','retainer','milestone')),
  payment_terms   TEXT,          -- e.g. "50% upfront, 50% on completion"

  -- Status lifecycle
  status          TEXT NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft','sent','viewed','accepted','declined','expired')),
  valid_until     DATE,
  sent_at         TIMESTAMPTZ,
  viewed_at       TIMESTAMPTZ,
  accepted_at     TIMESTAMPTZ,
  declined_at     TIMESTAMPTZ,

  -- Storage
  pdf_url         TEXT,

  -- Cross-module: when accepted, generates a contract
  contract_id     UUID REFERENCES contracts(id) ON DELETE SET NULL,

  -- Timestamps
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE proposals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_proposals" ON proposals
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE INDEX idx_proposals_client ON proposals(client_id);
CREATE INDEX idx_proposals_status ON proposals(user_id, status);

-- Now add the proposal FK back to engagements (deferred because proposals didn't exist yet)
ALTER TABLE engagements ADD COLUMN proposal_id UUID REFERENCES proposals(id) ON DELETE SET NULL;
```

---

## Migration 5: retainers table

```sql
-- Recurring income records. Feeds cashflow_agent with reliable monthly baseline.
CREATE TABLE retainers (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id       UUID REFERENCES clients(id) ON DELETE SET NULL,

  -- What this retainer is
  title           TEXT NOT NULL,           -- "Monthly SEO for Acme Corp"
  amount          NUMERIC(12,2) NOT NULL,
  currency        TEXT DEFAULT 'USD',
  billing_cycle   TEXT NOT NULL DEFAULT 'monthly'
                  CHECK (billing_cycle IN ('weekly','monthly','quarterly','annual')),

  -- Schedule
  start_date      DATE NOT NULL,
  end_date        DATE,                    -- null = ongoing
  next_invoice_date DATE,                 -- computed, updated after each invoice
  renewal_date    DATE,                   -- when to review/renew

  -- Status
  status          TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','paused','cancelled')),

  -- Cross-module: each billing cycle creates an invoice
  auto_invoice    BOOLEAN DEFAULT TRUE,   -- butler auto-creates invoice on billing date

  -- Timestamps
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE retainers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_retainers" ON retainers
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE INDEX idx_retainers_user_active ON retainers(user_id, status)
  WHERE status = 'active';
CREATE INDEX idx_retainers_next_invoice ON retainers(next_invoice_date)
  WHERE status = 'active' AND auto_invoice = TRUE;
```

---

## Migration 6: column additions to existing tables

```sql
-- Add client_id to invoices (nullable, backward compatible)
ALTER TABLE invoices
  ADD COLUMN client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
  ADD COLUMN proposal_id UUID REFERENCES proposals(id) ON DELETE SET NULL,
  ADD COLUMN retainer_id UUID REFERENCES retainers(id) ON DELETE SET NULL;

-- Add client_id to contracts (nullable, backward compatible)
ALTER TABLE contracts
  ADD COLUMN client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
  ADD COLUMN proposal_id UUID REFERENCES proposals(id) ON DELETE SET NULL;

-- Add client_id and retainer_id to transactions
ALTER TABLE transactions
  ADD COLUMN client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
  ADD COLUMN retainer_id UUID REFERENCES retainers(id) ON DELETE SET NULL;

-- Add butler_memory to users (rolling summary for briefing continuity)
ALTER TABLE users
  ADD COLUMN butler_memory JSONB DEFAULT '{}'::jsonb;
-- butler_memory shape: {
--   last_briefing_at: ISO timestamp,
--   last_briefing_summary: "2 sentences",
--   client_count: int,
--   active_engagement_count: int,
--   rolling_insights: ["string", ...] -- last 5 notable observations
-- }

-- Extend agent_logs agent_type CHECK to include 'butler'
-- (If CHECK constraint exists, drop and recreate; if not, skip)
-- Check your schema first: \d agent_logs
-- Then:
ALTER TABLE agent_logs
  DROP CONSTRAINT IF EXISTS agent_logs_agent_type_check;
ALTER TABLE agent_logs
  ADD CONSTRAINT agent_logs_agent_type_check
  CHECK (agent_type IN (
    'bookkeeper','invoice_follow_up','contract_generator',
    'cashflow_forecaster','alert_generator','cross_module',
    'supervisor','chat','butler'
  ));
```

---

## Migration 7: client_notes table

```sql
-- Communication history, meeting notes, blockers, decisions — all in one log.
CREATE TABLE client_notes (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id       UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  engagement_id   UUID REFERENCES engagements(id) ON DELETE SET NULL,
  quick_capture_id UUID REFERENCES quick_captures(id) ON DELETE SET NULL,

  -- Content
  note_type       TEXT NOT NULL DEFAULT 'general'
                  CHECK (note_type IN ('meeting','call','email','decision','blocker','update','general')),
  content_md      TEXT NOT NULL,
  is_ai_generated BOOLEAN DEFAULT FALSE,  -- true if butler wrote this from a quick_capture

  -- Timestamps
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE client_notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_notes" ON client_notes
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE INDEX idx_notes_client ON client_notes(client_id, created_at DESC);
CREATE INDEX idx_notes_engagement ON client_notes(engagement_id);
```

---

## Data relationship summary

```
users
  ├── clients (1:many)
  │     ├── engagements (1:many)
  │     │     └── → contracts (FK)
  │     │     └── → proposals (FK)
  │     ├── client_notes (1:many)
  │     ├── proposals (1:many) → contracts (FK when accepted)
  │     └── retainers (1:many)
  ├── quick_captures (1:many) → client_notes (created from capture)
  ├── invoices (existing) + client_id FK + proposal_id FK + retainer_id FK
  ├── contracts (existing) + client_id FK + proposal_id FK
  └── transactions (existing) + client_id FK + retainer_id FK
```

---

## Backfill strategy (for existing users)

When migrations run on an existing database, existing invoices/contracts have no client_id.
Run this once after migration 6 to auto-create clients from existing invoice client_name values:

```sql
-- Auto-create client records from existing unique invoice client names
-- Only run ONCE on first deployment. Does not overwrite existing clients.
INSERT INTO clients (user_id, name, email, what_we_do, status)
SELECT DISTINCT ON (user_id, lower(client_name))
  user_id,
  client_name AS name,
  client_email AS email,
  'Imported from invoice history' AS what_we_do,
  'active' AS status
FROM invoices
WHERE client_name IS NOT NULL
  AND client_name <> ''
  AND NOT EXISTS (
    SELECT 1 FROM clients c
    WHERE c.user_id = invoices.user_id
      AND lower(c.name) = lower(invoices.client_name)
  )
ON CONFLICT DO NOTHING;

-- Then link existing invoices to their auto-created clients
UPDATE invoices i
SET client_id = c.id
FROM clients c
WHERE i.user_id = c.user_id
  AND lower(i.client_name) = lower(c.name)
  AND i.client_id IS NULL;

-- Same for contracts
UPDATE contracts ct
SET client_id = c.id
FROM clients c
WHERE ct.user_id = c.user_id
  AND lower(ct.client_name) = lower(c.name)
  AND ct.client_id IS NULL;
```
