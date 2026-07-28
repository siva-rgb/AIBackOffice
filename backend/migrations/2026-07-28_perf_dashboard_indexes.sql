-- M8.1 — Indexes for dashboard / list query patterns.
-- Matches supabase_store list_* order/filter paths and /api/overview aggregation.

-- Transactions: list_transactions ORDER BY date DESC
CREATE INDEX IF NOT EXISTS idx_transactions_user_date
  ON public.transactions (user_id, date DESC);

-- Invoices: list_invoices ORDER BY created_at DESC; status filters on overview
CREATE INDEX IF NOT EXISTS idx_invoices_user_created
  ON public.invoices (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_invoices_user_status
  ON public.invoices (user_id, status);

-- Agent logs: dashboard recentActivity ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_agent_logs_user_created
  ON public.agent_logs (user_id, created_at DESC);

-- Alerts: unread filter on overview
CREATE INDEX IF NOT EXISTS idx_alerts_user_unread
  ON public.alerts (user_id, read, created_at DESC);
