-- M1.3 — Defense-in-depth RLS policies for tables missing them.
-- The application-layer repository wrapper (supabase_store.repo()) is the
-- primary guardrail, but these RLS policies are the backup. The service-role
-- key bypasses RLS, so these are effective only when end-user JWT mode is
-- used; documented as a known exception per PLAN.md M1.3.

-- Stripe Connections (created ad-hoc, no prior migration)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'stripe_connections'
    ) THEN
        ALTER TABLE public.stripe_connections ENABLE ROW LEVEL SECURITY;

        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE tablename = 'stripe_connections' AND policyname = 'Users see own stripe connection'
        ) THEN
            CREATE POLICY "Users see own stripe connection"
            ON public.stripe_connections
            FOR ALL
            USING (auth.uid() = user_id)
            WITH CHECK (auth.uid() = user_id);
        END IF;
    END IF;
END $$;