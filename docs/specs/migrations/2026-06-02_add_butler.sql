-- ============================================================================
-- Butler / AI business partner (manager_skill/SKILL.md)
-- Additive: new tables + users.butler_memory + agent_logs CHECK extension.
-- Existing invoices/contracts/transactions are NOT modified — the Butler links
-- clients to those records by case-insensitive client_name match in the service
-- layer, so this migration is fully backward compatible and touches no hot table.
-- Run in Supabase SQL editor. Idempotent-ish (IF NOT EXISTS where possible).
-- ============================================================================

-- 1. clients --------------------------------------------------------------
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
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.clients ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_clients" ON public.clients FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_clients_user ON public.clients(user_id, status);
CREATE INDEX IF NOT EXISTS idx_clients_health ON public.clients(user_id, health_score);

-- 2. engagements ----------------------------------------------------------
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
  proposal_id       UUID,   -- FK added after proposals exists (below)
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.engagements ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_engagements" ON public.engagements FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_engagements_client ON public.engagements(client_id);
CREATE INDEX IF NOT EXISTS idx_engagements_status ON public.engagements(user_id, status);

-- 3. quick_captures -------------------------------------------------------
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

-- 4. proposals ------------------------------------------------------------
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

-- now wire the deferred proposal FK on engagements
ALTER TABLE public.engagements
  ADD CONSTRAINT engagements_proposal_fk FOREIGN KEY (proposal_id)
  REFERENCES public.proposals(id) ON DELETE SET NULL;

-- 5. retainers ------------------------------------------------------------
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

-- 6. client_notes ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.client_notes (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  client_id         UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  engagement_id     UUID REFERENCES public.engagements(id) ON DELETE SET NULL,
  quick_capture_id  UUID REFERENCES public.quick_captures(id) ON DELETE SET NULL,
  note_type         TEXT NOT NULL DEFAULT 'general'
                    CHECK (note_type IN ('meeting','call','email','decision','blocker','update','general')),
  content_md        TEXT NOT NULL,
  is_ai_generated   BOOLEAN DEFAULT FALSE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.client_notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_notes" ON public.client_notes FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE INDEX IF NOT EXISTS idx_notes_client ON public.client_notes(client_id, created_at DESC);

-- 7. users.butler_memory (rolling briefing continuity) --------------------
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS butler_memory JSONB DEFAULT '{}'::jsonb;

-- 8. agent_logs: allow agent_type = 'butler' ------------------------------
ALTER TABLE public.agent_logs DROP CONSTRAINT IF EXISTS agent_logs_agent_type_check;
ALTER TABLE public.agent_logs
  ADD CONSTRAINT agent_logs_agent_type_check
  CHECK (agent_type IN (
    'bookkeeper','invoice_follow_up','contract_generator',
    'cashflow_forecaster','alert_generator','cross_module','chat','butler'
  ));
