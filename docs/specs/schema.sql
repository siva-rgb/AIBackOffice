-- Kora — Full Database Schema
-- Run via: supabase db push  OR  psql $DATABASE_URL < schema.sql
-- Supabase already provides: auth.users table

-- =============================================
-- EXTENSIONS
-- =============================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- for fuzzy text search

-- =============================================
-- USERS (extends Supabase auth.users)
-- =============================================
CREATE TABLE public.users (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  full_name TEXT,
  business_name TEXT,
  country TEXT DEFAULT 'US',
  timezone TEXT DEFAULT 'America/New_York',
  currency TEXT DEFAULT 'USD',
  stripe_customer_id TEXT UNIQUE,
  stripe_subscription_id TEXT,
  plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'starter', 'pro')),
  plan_expires_at TIMESTAMPTZ,
  onboarding_completed BOOLEAN DEFAULT FALSE,
  profile JSONB NOT NULL DEFAULT '{}'::jsonb,  -- business profile (owner + business info, goals, prefs)
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- RLS: users can only see their own row
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own profile" ON public.users
  FOR SELECT USING (auth.uid() = id);
CREATE POLICY "Users can update own profile" ON public.users
  FOR UPDATE USING (auth.uid() = id);

-- Auto-create user row on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.users (id, email, full_name)
  VALUES (NEW.id, NEW.email, NEW.raw_user_meta_data->>'full_name');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- =============================================
-- TRANSACTIONS (bookkeeping)
-- =============================================
CREATE TABLE public.transactions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  description TEXT NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  type TEXT NOT NULL CHECK (type IN ('income', 'expense')),
  category TEXT,
  subcategory TEXT,
  tax_deductible BOOLEAN DEFAULT FALSE,
  source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('csv', 'bank', 'manual', 'stripe')),
  ai_categorized BOOLEAN DEFAULT FALSE,
  ai_confidence DECIMAL(3,2),
  raw_text TEXT,
  notes TEXT,
  report_id UUID, -- populated after report generation
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, date, description, amount) -- dedup constraint
);

ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own transactions" ON public.transactions
  FOR ALL USING (auth.uid() = user_id);

CREATE INDEX idx_transactions_user_date ON public.transactions(user_id, date DESC);
CREATE INDEX idx_transactions_category ON public.transactions(user_id, category);
CREATE INDEX idx_transactions_type ON public.transactions(user_id, type);

-- =============================================
-- REPORTS (P&L, summaries)
-- =============================================
CREATE TABLE public.reports (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  type TEXT NOT NULL DEFAULT 'monthly' CHECK (type IN ('monthly', 'quarterly', 'annual', 'custom')),
  total_income DECIMAL(12,2) NOT NULL DEFAULT 0,
  total_expenses DECIMAL(12,2) NOT NULL DEFAULT 0,
  net_profit DECIMAL(12,2) GENERATED ALWAYS AS (total_income - total_expenses) STORED,
  profit_margin DECIMAL(5,2),
  income_by_category JSONB DEFAULT '{}',
  expense_by_category JSONB DEFAULT '{}',
  pdf_url TEXT,
  status TEXT NOT NULL DEFAULT 'generating' CHECK (status IN ('generating', 'ready', 'error')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own reports" ON public.reports
  FOR ALL USING (auth.uid() = user_id);

-- =============================================
-- INVOICES
-- =============================================
CREATE TABLE public.invoices (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  invoice_number TEXT NOT NULL,
  client_name TEXT NOT NULL,
  client_email TEXT NOT NULL,
  line_items JSONB NOT NULL DEFAULT '[]',
  subtotal DECIMAL(12,2) NOT NULL DEFAULT 0,
  tax_rate DECIMAL(5,2) NOT NULL DEFAULT 0,
  tax_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  total DECIMAL(12,2) NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'USD',
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'sent', 'viewed', 'paid', 'overdue', 'cancelled')),
  due_date DATE NOT NULL,
  notes TEXT,
  payment_link TEXT,
  contract_id UUID, -- FK to contracts (set after linking)
  sent_at TIMESTAMPTZ,
  viewed_at TIMESTAMPTZ,
  paid_at TIMESTAMPTZ,
  follow_up_count INTEGER NOT NULL DEFAULT 0,
  last_follow_up_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, invoice_number)
);

ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own invoices" ON public.invoices
  FOR ALL USING (auth.uid() = user_id);

CREATE INDEX idx_invoices_user_status ON public.invoices(user_id, status);
CREATE INDEX idx_invoices_due_date ON public.invoices(due_date) WHERE status IN ('sent', 'overdue');

-- Auto-generate invoice numbers
CREATE OR REPLACE FUNCTION public.generate_invoice_number(p_user_id UUID)
RETURNS TEXT AS $$
DECLARE
  v_count INTEGER;
  v_year TEXT;
BEGIN
  v_year := TO_CHAR(NOW(), 'YYYY');
  SELECT COUNT(*) + 1 INTO v_count
  FROM public.invoices
  WHERE user_id = p_user_id
    AND EXTRACT(YEAR FROM created_at) = EXTRACT(YEAR FROM NOW());
  RETURN 'INV-' || v_year || '-' || LPAD(v_count::TEXT, 3, '0');
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- CONTRACTS
-- =============================================
CREATE TABLE public.contracts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  type TEXT NOT NULL
    CHECK (type IN ('nda', 'freelance_agreement', 'service_contract', 'refund_policy', 'ip_transfer')),
  title TEXT,
  client_name TEXT NOT NULL,
  client_email TEXT,
  jurisdiction TEXT NOT NULL DEFAULT 'US',
  terms JSONB NOT NULL DEFAULT '{}', -- structured inputs from wizard
  content_md TEXT, -- full generated contract markdown
  section_explanations JSONB DEFAULT '{}', -- plain-English per-section explanations
  pdf_url TEXT,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'sent', 'signed', 'expired', 'cancelled')),
  signed_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.contracts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own contracts" ON public.contracts
  FOR ALL USING (auth.uid() = user_id);

-- Add FK from invoices to contracts
ALTER TABLE public.invoices
  ADD CONSTRAINT fk_invoices_contract
  FOREIGN KEY (contract_id) REFERENCES public.contracts(id) ON DELETE SET NULL;

-- =============================================
-- AGENT_LOGS (critical for hackathon judging)
-- =============================================
CREATE TABLE public.agent_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  agent_type TEXT NOT NULL
    CHECK (agent_type IN (
      'bookkeeper', 'invoice_follow_up', 'contract_generator',
      'cashflow_forecaster', 'alert_generator', 'cross_module', 'chat'
    )),
  action TEXT NOT NULL, -- human-readable description
  input JSONB,          -- prompt/context sent to AI
  output JSONB,         -- structured AI response
  model_used TEXT NOT NULL DEFAULT 'gemini-1.5-pro',
  tokens_used INTEGER,
  latency_ms INTEGER,
  status TEXT NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'error', 'partial')),
  error_message TEXT,
  triggered_by TEXT NOT NULL DEFAULT 'user'
    CHECK (triggered_by IN ('user', 'scheduler', 'cross_module', 'webhook')),
  source_record_type TEXT, -- 'invoice', 'contract', 'transaction', etc.
  source_record_id UUID,   -- ID of the record that triggered this action
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.agent_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own agent logs" ON public.agent_logs
  FOR SELECT USING (auth.uid() = user_id);
-- Service role can insert from workers
CREATE POLICY "Service role can insert logs" ON public.agent_logs
  FOR INSERT WITH CHECK (TRUE);

CREATE INDEX idx_agent_logs_user ON public.agent_logs(user_id, created_at DESC);
CREATE INDEX idx_agent_logs_type ON public.agent_logs(agent_type, created_at DESC);
CREATE INDEX idx_agent_logs_triggered_by ON public.agent_logs(triggered_by);

-- =============================================
-- ALERTS
-- =============================================
CREATE TABLE public.alerts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info', 'warning', 'critical')),
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  action_label TEXT,
  action_url TEXT,
  read BOOLEAN NOT NULL DEFAULT FALSE,
  read_at TIMESTAMPTZ,
  dismissed BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.alerts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own alerts" ON public.alerts
  FOR ALL USING (auth.uid() = user_id);

CREATE INDEX idx_alerts_user_unread ON public.alerts(user_id, read, created_at DESC);

-- =============================================
-- CASHFLOW_FORECASTS
-- =============================================
CREATE TABLE public.cashflow_forecasts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  horizon_days INTEGER NOT NULL DEFAULT 90,
  current_balance DECIMAL(12,2),
  forecast_data JSONB NOT NULL DEFAULT '[]', -- array of ForecastPoint
  key_risks JSONB DEFAULT '[]',
  recommended_actions JSONB DEFAULT '[]',
  confidence_score DECIMAL(3,2),
  assumptions JSONB DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.cashflow_forecasts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own forecasts" ON public.cashflow_forecasts
  FOR ALL USING (auth.uid() = user_id);

-- Keep only last 7 forecasts per user (auto-cleanup)
CREATE OR REPLACE FUNCTION cleanup_old_forecasts()
RETURNS TRIGGER AS $$
BEGIN
  DELETE FROM public.cashflow_forecasts
  WHERE user_id = NEW.user_id
    AND id NOT IN (
      SELECT id FROM public.cashflow_forecasts
      WHERE user_id = NEW.user_id
      ORDER BY created_at DESC
      LIMIT 7
    );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_cleanup_forecasts
  AFTER INSERT ON public.cashflow_forecasts
  FOR EACH ROW EXECUTE FUNCTION cleanup_old_forecasts();

-- =============================================
-- UPDATED_AT triggers
-- =============================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON public.users
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_transactions_updated_at BEFORE UPDATE ON public.transactions
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_invoices_updated_at BEFORE UPDATE ON public.invoices
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_contracts_updated_at BEFORE UPDATE ON public.contracts
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================
-- CROSS-MODULE TRIGGER: contract signed → create invoices
-- (Webhook-based: use Supabase webhook → Cloud Run endpoint)
-- =============================================
-- Set up in Supabase Dashboard:
-- Table: contracts, Event: UPDATE, Filter: status=signed
-- HTTP POST to: https://[cloud-run-url]/api/cross-module/contract-signed
-- Include: { record: { id, user_id, terms, type } }

-- =============================================
-- USEFUL VIEWS
-- =============================================

-- Agent log summary by type (for dashboard)
CREATE VIEW public.agent_log_summary AS
SELECT
  user_id,
  agent_type,
  COUNT(*) AS total_actions,
  COUNT(*) FILTER (WHERE status = 'success') AS successful,
  COUNT(*) FILTER (WHERE triggered_by = 'scheduler') AS scheduler_triggered,
  COUNT(*) FILTER (WHERE triggered_by = 'cross_module') AS cross_module_triggered,
  AVG(latency_ms) AS avg_latency_ms,
  MAX(created_at) AS last_action_at
FROM public.agent_logs
GROUP BY user_id, agent_type;

-- Invoice aging report
CREATE VIEW public.invoice_aging AS
SELECT
  user_id,
  status,
  COUNT(*) AS count,
  SUM(total) AS total_amount,
  AVG(CURRENT_DATE - due_date) FILTER (WHERE status IN ('sent','overdue')) AS avg_days_overdue
FROM public.invoices
WHERE status NOT IN ('cancelled', 'draft')
GROUP BY user_id, status;

-- =============================================
-- SEED DATA (development only)
-- Comment out for production
-- =============================================
-- INSERT INTO ... (add test data as needed during development)

-- =============================================
-- MANAGER TASKS (supervisor human-in-the-loop approval queue)
-- =============================================
CREATE TABLE IF NOT EXISTS public.manager_tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                  -- send_followup | send_demand | review_contract | ...
  title TEXT NOT NULL,
  rationale TEXT,
  severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warning','critical')),
  status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','approved','dismissed','done','failed')),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_record_type TEXT,
  source_record_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);
ALTER TABLE public.manager_tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own manager_tasks" ON public.manager_tasks
  FOR ALL USING (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_manager_tasks_user_status
  ON public.manager_tasks (user_id, status);

-- =============================================
-- BUTLER / CLIENT MANAGEMENT
-- (added 2026-06-02 by docs/specs/migrations/2026-06-02_add_butler.sql)
-- =============================================
CREATE TABLE IF NOT EXISTS public.clients (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  name              TEXT NOT NULL,
  email             TEXT,
  phone             TEXT,
  company           TEXT,
  industry          TEXT,
  client_type       TEXT NOT NULL DEFAULT 'individual'
                    CHECK (client_type IN ('individual','company','agency','marketplace')),
  status            TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','inactive','prospect','churned')),
  what_we_do        TEXT,
  notes_md          TEXT,
  timezone          TEXT,
  currency          TEXT DEFAULT 'USD',
  health_score      INTEGER DEFAULT 100 CHECK (health_score BETWEEN 0 AND 100),
  health_label      TEXT DEFAULT 'on_track'
                    CHECK (health_label IN ('on_track','at_risk','needs_attention','critical')),
  health_updated_at TIMESTAMPTZ,
  last_activity_at  TIMESTAMPTZ,
  billing_address   TEXT,           -- added 2026-06-19 by 2026-06-19_invoice_enhancements.sql
  tax_id            TEXT,           -- added 2026-06-19 by 2026-06-19_invoice_enhancements.sql
  contact_emails    TEXT[] DEFAULT '{}',  -- added 2026-07-15 by 2026-07-15_gmail_intel_upgrades.sql
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.clients ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_clients" ON public.clients FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_clients_user ON public.clients(user_id, status);
CREATE INDEX IF NOT EXISTS idx_clients_health ON public.clients(user_id, health_score);

CREATE TABLE IF NOT EXISTS public.engagements (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  client_id         UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  title             TEXT NOT NULL,
  description_md    TEXT,
  engagement_type   TEXT NOT NULL DEFAULT 'project'
                    CHECK (engagement_type IN ('project','retainer','one_off','ongoing')),
  status            TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('planning','active','on_track','at_risk','paused','done','cancelled')),
  start_date        DATE,
  target_end_date   DATE,
  budget            NUMERIC(12,2),
  budget_currency   TEXT DEFAULT 'USD',
  value_delivered   NUMERIC(12,2) DEFAULT 0,
  contract_id       UUID REFERENCES public.contracts(id) ON DELETE SET NULL,
  proposal_id       UUID,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.engagements ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_engagements" ON public.engagements FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_engagements_client ON public.engagements(client_id);
CREATE INDEX IF NOT EXISTS idx_engagements_status ON public.engagements(user_id, status);

CREATE TABLE IF NOT EXISTS public.quick_captures (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  raw_text          TEXT NOT NULL,
  source            TEXT NOT NULL DEFAULT 'web' CHECK (source IN ('web','mobile','email','sms')),
  parse_status      TEXT NOT NULL DEFAULT 'pending' CHECK (parse_status IN ('pending','parsed','failed','partial')),
  parsed_intent     TEXT,
  parsed_entities   JSONB DEFAULT '{}'::jsonb,
  ai_confidence     NUMERIC(3,2),
  actions_taken     JSONB DEFAULT '[]'::jsonb,
  requires_review   BOOLEAN DEFAULT FALSE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  parsed_at         TIMESTAMPTZ
);
ALTER TABLE public.quick_captures ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_captures" ON public.quick_captures FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_captures_review ON public.quick_captures(user_id, requires_review);

CREATE TABLE IF NOT EXISTS public.proposals (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  client_id         UUID REFERENCES public.clients(id) ON DELETE SET NULL,
  title             TEXT NOT NULL,
  proposal_number   TEXT,
  scope_md          TEXT,
  deliverables_md   TEXT,
  timeline_md       TEXT,
  content_md        TEXT,
  section_explanations JSONB DEFAULT '{}'::jsonb,
  total_amount      NUMERIC(12,2) DEFAULT 0,
  currency          TEXT DEFAULT 'USD',
  pricing_type      TEXT DEFAULT 'fixed' CHECK (pricing_type IN ('fixed','hourly','retainer','milestone')),
  payment_terms     TEXT,
  status            TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','viewed','accepted','declined','expired')),
  valid_until       DATE,
  sent_at           TIMESTAMPTZ,
  accepted_at       TIMESTAMPTZ,
  contract_id       UUID REFERENCES public.contracts(id) ON DELETE SET NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.proposals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_proposals" ON public.proposals FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_proposals_user ON public.proposals(user_id, status);

ALTER TABLE public.engagements
  ADD CONSTRAINT IF NOT EXISTS engagements_proposal_fk FOREIGN KEY (proposal_id)
  REFERENCES public.proposals(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS public.retainers (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  client_id         UUID REFERENCES public.clients(id) ON DELETE SET NULL,
  title             TEXT NOT NULL,
  amount            NUMERIC(12,2) NOT NULL,
  currency          TEXT DEFAULT 'USD',
  billing_cycle     TEXT NOT NULL DEFAULT 'monthly' CHECK (billing_cycle IN ('weekly','monthly','quarterly','annual')),
  start_date        DATE NOT NULL,
  end_date          DATE,
  next_invoice_date DATE,
  renewal_date      DATE,
  status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','cancelled')),
  auto_invoice      BOOLEAN DEFAULT TRUE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.retainers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_retainers" ON public.retainers FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_retainers_user ON public.retainers(user_id, status);

CREATE TABLE IF NOT EXISTS public.client_notes (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  client_id         UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  engagement_id     UUID REFERENCES public.engagements(id) ON DELETE SET NULL,
  quick_capture_id  UUID REFERENCES public.quick_captures(id) ON DELETE SET NULL,
  meeting_id        UUID,  -- FK added after meetings table (see google butler migration)
  note_type         TEXT NOT NULL DEFAULT 'general'
                    CHECK (note_type IN ('meeting','call','email','decision','blocker','update','general')),
  content_md        TEXT NOT NULL,
  is_ai_generated   BOOLEAN DEFAULT FALSE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.client_notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_notes" ON public.client_notes FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_notes_client ON public.client_notes(client_id, created_at DESC);

-- =============================================
-- GOOGLE BUTLER INTEGRATION
-- (added 2026-06-10 by backend/migrations/2026-06-10_add_google_butler.sql)
-- =============================================
CREATE TABLE IF NOT EXISTS public.google_connections (
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
  watch_history_id  TEXT,           -- added 2026-07-15 by 2026-07-15_gmail_intel_upgrades.sql
  watch_expiration  TIMESTAMPTZ,    -- added 2026-07-15 by 2026-07-15_gmail_intel_upgrades.sql
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.google_connections ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_connections" ON public.google_connections
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE INDEX IF NOT EXISTS idx_google_connections_user ON public.google_connections(user_id);

CREATE TABLE IF NOT EXISTS public.email_intel_cache (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id               UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id             UUID REFERENCES public.clients(id) ON DELETE CASCADE,
  client_name           TEXT NOT NULL,
  thread_count          INTEGER DEFAULT 0,
  last_message_id       TEXT,
  last_contact_days     INTEGER,
  last_contact_direction TEXT CHECK (last_contact_direction IN ('from_client','from_me','unknown')),
  sentiment             TEXT CHECK (sentiment IN ('positive','neutral','cautious','strained')),
  relationship_health   TEXT CHECK (relationship_health IN ('strong','healthy','needs_attention','at_risk','unknown')),
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
ALTER TABLE public.email_intel_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_email_cache" ON public.email_intel_cache USING (user_id = auth.uid());
CREATE INDEX IF NOT EXISTS idx_email_cache_user ON public.email_intel_cache(user_id, action_needed);

CREATE TABLE IF NOT EXISTS public.meetings (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id         UUID REFERENCES public.clients(id) ON DELETE SET NULL,
  engagement_id     UUID REFERENCES public.engagements(id) ON DELETE SET NULL,
  title             TEXT NOT NULL,
  meeting_type      TEXT NOT NULL DEFAULT 'call'
    CHECK (meeting_type IN ('call','video','in_person','async')),
  meeting_date      TIMESTAMPTZ NOT NULL,
  duration_minutes  INTEGER,
  attendees         JSONB,
  google_event_id   TEXT,
  meet_link         TEXT,
  source            TEXT NOT NULL DEFAULT 'manual'
    CHECK (source IN ('transcript_upload','quick_capture','calendar_import','drive_transcript','manual')),
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
ALTER TABLE public.meetings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_meetings" ON public.meetings
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE INDEX IF NOT EXISTS idx_meetings_client ON public.meetings(client_id, meeting_date DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_user_date ON public.meetings(user_id, meeting_date DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_pending ON public.meetings(user_id, parse_status)
  WHERE parse_status = 'pending';

ALTER TABLE public.client_notes
  ADD CONSTRAINT IF NOT EXISTS client_notes_meeting_fk
  FOREIGN KEY (meeting_id) REFERENCES public.meetings(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS public.drive_doc_cache (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  drive_file_id     TEXT NOT NULL,
  file_name         TEXT,
  mime_type         TEXT,
  doc_type          TEXT,
  drive_modified_time TEXT,
  processed_at      TIMESTAMPTZ,
  meeting_id        UUID REFERENCES public.meetings(id) ON DELETE SET NULL,
  client_id         UUID REFERENCES public.clients(id) ON DELETE SET NULL,  -- added 2026-07-16 by 2026-07-16_drive_client_link.sql
  UNIQUE (user_id, drive_file_id)
);
ALTER TABLE public.drive_doc_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_drive_cache" ON public.drive_doc_cache USING (user_id = auth.uid());
CREATE INDEX IF NOT EXISTS idx_drive_doc_cache_user_client
  ON public.drive_doc_cache (user_id, client_id) WHERE client_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.meeting_action_items (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  meeting_id    UUID NOT NULL REFERENCES public.meetings(id) ON DELETE CASCADE,
  client_id     UUID REFERENCES public.clients(id) ON DELETE SET NULL,
  description   TEXT NOT NULL,
  owner         TEXT NOT NULL DEFAULT 'me' CHECK (owner IN ('me','client','both','third_party')),
  due_date      DATE,
  priority      TEXT DEFAULT 'medium' CHECK (priority IN ('high','medium','low')),
  status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','done','cancelled')),
  completed_at  TIMESTAMPTZ,
  manager_task_id UUID,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.meeting_action_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_action_items" ON public.meeting_action_items
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE INDEX IF NOT EXISTS idx_action_items_meeting ON public.meeting_action_items(meeting_id);
CREATE INDEX IF NOT EXISTS idx_action_items_open ON public.meeting_action_items(user_id, status) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_action_items_client ON public.meeting_action_items(client_id) WHERE status = 'open';

-- =============================================
-- BUSINESS PLAYBOOK
-- (added 2026-06-18 by backend/migrations/2026-06-18_add_business_playbook.sql)
-- =============================================
CREATE TABLE IF NOT EXISTS public.business_playbook (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    category    TEXT NOT NULL CHECK (category IN (
                    'correction', 'user_preference', 'client_intelligence',
                    'business_pattern', 'business_rule', 'extracted_fact'
                )),
    client_id   UUID REFERENCES public.clients(id) ON DELETE SET NULL,
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
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, category, key, client_id)
);
CREATE INDEX IF NOT EXISTS idx_playbook_user_category ON public.business_playbook (user_id, category);
CREATE INDEX IF NOT EXISTS idx_playbook_user_confidence ON public.business_playbook (user_id, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_playbook_user_client ON public.business_playbook (user_id, client_id) WHERE client_id IS NOT NULL;
ALTER TABLE public.business_playbook ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own playbook entries" ON public.business_playbook
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- =============================================
-- GRAPH MEMORY
-- (added 2026-07-16 by backend/migrations/2026-07-16_add_graph_memory.sql)
-- =============================================
CREATE TABLE IF NOT EXISTS public.kg_nodes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    node_type   TEXT NOT NULL,
    entity_id   TEXT,
    label       TEXT NOT NULL,
    props       JSONB NOT NULL DEFAULT '{}',
    salience    NUMERIC(4,3) NOT NULL DEFAULT 0.5 CHECK (salience >= 0 AND salience <= 1),
    first_seen  TIMESTAMPTZ,
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_nodes_entity ON public.kg_nodes (user_id, node_type, entity_id) WHERE entity_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_kg_nodes_concept ON public.kg_nodes (user_id, node_type, label) WHERE entity_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_kg_nodes_user_type ON public.kg_nodes (user_id, node_type);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_user_salience ON public.kg_nodes (user_id, salience DESC);
ALTER TABLE public.kg_nodes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own kg nodes" ON public.kg_nodes
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE TABLE IF NOT EXISTS public.kg_edges (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    src_id      UUID NOT NULL REFERENCES public.kg_nodes(id) ON DELETE CASCADE,
    dst_id      UUID NOT NULL REFERENCES public.kg_nodes(id) ON DELETE CASCADE,
    rel         TEXT NOT NULL,
    weight      NUMERIC NOT NULL DEFAULT 1,
    props       JSONB NOT NULL DEFAULT '{}',
    first_seen  TIMESTAMPTZ,
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, src_id, dst_id, rel)
);
CREATE INDEX IF NOT EXISTS idx_kg_edges_user_src ON public.kg_edges (user_id, src_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_user_dst ON public.kg_edges (user_id, dst_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_user_rel ON public.kg_edges (user_id, rel);
ALTER TABLE public.kg_edges ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own kg edges" ON public.kg_edges
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- =============================================
-- SEMANTIC AGENT MEMORY
-- (added 2026-07-16 by backend/migrations/2026-07-16_add_semantic_memory.sql)
-- =============================================
CREATE TABLE IF NOT EXISTS public.agent_memory (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    client_id   UUID REFERENCES public.clients(id) ON DELETE SET NULL,
    ref_type    TEXT,
    ref_id      TEXT,
    content     TEXT NOT NULL,
    embedding   JSONB,
    salience    NUMERIC(4,3) NOT NULL DEFAULT 0.5 CHECK (salience >= 0 AND salience <= 1),
    source      TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_memory_ref ON public.agent_memory (user_id, kind, ref_id) WHERE ref_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_memory_user_kind ON public.agent_memory (user_id, kind);
CREATE INDEX IF NOT EXISTS idx_agent_memory_user_client ON public.agent_memory (user_id, client_id) WHERE client_id IS NOT NULL;
ALTER TABLE public.agent_memory ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own agent memory" ON public.agent_memory
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- =============================================
-- NOTION CONNECTION
-- (added 2026-07-17 by backend/migrations/2026-07-17_add_notion_connection.sql)
-- =============================================
CREATE TABLE IF NOT EXISTS public.notion_connections (
    user_id        UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    access_token   TEXT,
    workspace_id   TEXT,
    workspace_name TEXT,
    bot_id         TEXT,
    tasks_db_id    TEXT,
    connected      BOOLEAN NOT NULL DEFAULT FALSE,
    last_sync_at   TIMESTAMPTZ,
    last_error     TEXT,
    ingest_page_ids JSONB NOT NULL DEFAULT '[]'::jsonb,  -- added 2026-07-24 by 2026-07-24_notion_ingest.sql
    last_ingest_at  TIMESTAMPTZ,                         -- added 2026-07-24 by 2026-07-24_notion_ingest.sql
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.notion_connections ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own notion connection" ON public.notion_connections
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- =============================================
-- TASK LEDGER
-- (added 2026-07-17 by backend/migrations/2026-07-17_add_tasks.sql)
-- =============================================
CREATE TABLE IF NOT EXISTS public.tasks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    client_id     UUID REFERENCES public.clients(id) ON DELETE SET NULL,
    engagement_id UUID REFERENCES public.engagements(id) ON DELETE SET NULL,
    title         TEXT NOT NULL,
    description_md TEXT,
    status        TEXT NOT NULL DEFAULT 'todo',
    priority      TEXT NOT NULL DEFAULT 'medium',
    due_date      DATE,
    owner         TEXT,
    source        TEXT NOT NULL DEFAULT 'manual',
    source_ref    TEXT,
    external_ref  TEXT,
    external_url  TEXT,
    synced_at     TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_source_ref ON public.tasks (user_id, source_ref) WHERE source_ref IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_external_ref ON public.tasks (user_id, external_ref) WHERE external_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON public.tasks (user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_user_client ON public.tasks (user_id, client_id) WHERE client_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_user_due ON public.tasks (user_id, due_date) WHERE due_date IS NOT NULL;
ALTER TABLE public.tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own tasks" ON public.tasks
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- =============================================
-- CLIENT VIEW CACHE (PM agent)
-- (added 2026-07-23 by backend/migrations/2026-07-23_add_client_view_cache.sql)
-- =============================================
CREATE TABLE IF NOT EXISTS public.client_view_cache (
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    client_id    UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    view         JSONB NOT NULL DEFAULT '{}'::jsonb,
    token_cost   JSONB NOT NULL DEFAULT '{}'::jsonb,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, client_id)
);
CREATE INDEX IF NOT EXISTS idx_client_view_user ON public.client_view_cache (user_id);
ALTER TABLE public.client_view_cache ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own client views" ON public.client_view_cache
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- =============================================
-- STORY LAYER (ADR-0001)
-- (added 2026-07-23 by backend/migrations/2026-07-23_add_stories.sql)
-- =============================================
CREATE TABLE IF NOT EXISTS public.stories (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    task_id        UUID NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,
    client_id      UUID REFERENCES public.clients(id) ON DELETE SET NULL,
    engagement_id  UUID REFERENCES public.engagements(id) ON DELETE SET NULL,
    title          TEXT NOT NULL,
    description_md TEXT,
    status         TEXT NOT NULL DEFAULT 'todo',
    progress_pct   SMALLINT NOT NULL DEFAULT 0 CHECK (progress_pct >= 0 AND progress_pct <= 100),
    observations   JSONB NOT NULL DEFAULT '[]'::jsonb,
    completed_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_stories_user_task ON public.stories (user_id, task_id);
CREATE INDEX IF NOT EXISTS idx_stories_user_client ON public.stories (user_id, client_id) WHERE client_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stories_user_status ON public.stories (user_id, status);
ALTER TABLE public.stories ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own stories" ON public.stories
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- =============================================
-- COLUMN ADDITIONS ON V1 TABLES (from migration ALTERs)
-- =============================================
-- users: butler + google + invoice sender fields
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS butler_memory JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS google_connected BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS google_email TEXT,
  ADD COLUMN IF NOT EXISTS business_address TEXT,
  ADD COLUMN IF NOT EXISTS tax_id TEXT,
  ADD COLUMN IF NOT EXISTS invoice_footer TEXT;

-- invoices: professional PDF + email delivery fields
ALTER TABLE public.invoices
  ADD COLUMN IF NOT EXISTS invoice_date DATE,
  ADD COLUMN IF NOT EXISTS payment_terms TEXT,
  ADD COLUMN IF NOT EXISTS payment_terms_days INTEGER,
  ADD COLUMN IF NOT EXISTS client_address TEXT,
  ADD COLUMN IF NOT EXISTS client_tax_id TEXT,
  ADD COLUMN IF NOT EXISTS po_number TEXT,
  ADD COLUMN IF NOT EXISTS pdf_path TEXT,
  ADD COLUMN IF NOT EXISTS email_message_id TEXT,
  ADD COLUMN IF NOT EXISTS amount_paid NUMERIC(12,2) DEFAULT 0;

-- manager_tasks: extended kind CHECK (Google Butler action kinds)
ALTER TABLE public.manager_tasks DROP CONSTRAINT IF EXISTS manager_tasks_kind_check;
ALTER TABLE public.manager_tasks ADD CONSTRAINT manager_tasks_kind_check
  CHECK (kind IN (
    'send_followup','send_demand','send_contract','writeoff_invoice',
    'review_contract','propose_write_off','send_proposal',
    'send_email_gmail','create_calendar_event','send_meeting_followup'
  ));

-- agent_logs: authoritative agent_type CHECK (includes billing per 2026-07-28 migration)
ALTER TABLE public.agent_logs DROP CONSTRAINT IF EXISTS agent_logs_agent_type_check;
ALTER TABLE public.agent_logs ADD CONSTRAINT agent_logs_agent_type_check
  CHECK (agent_type IN (
    'bookkeeper','invoice_follow_up','contract_generator','cashflow_forecaster',
    'alert_generator','cross_module','supervisor','chat','butler','butler_gmail',
    'butler_drive','butler_calendar','meeting_agent','gmail_agent','calendar_agent',
    'playbook','email_delivery','morning_digest','billing'
  ));
