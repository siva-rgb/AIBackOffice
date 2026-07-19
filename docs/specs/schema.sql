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
