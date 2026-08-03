-- M8 (R1) — durable background-import job state.
--
-- CSV import runs as a background task; the frontend polls its status. The
-- status lived in a per-process in-memory dict, so under >1 worker the poll
-- could hit a worker that never ran the job → a permanent 404 for an import
-- that actually succeeded, and all state was lost on restart. Persisting the
-- job makes status shared across workers and durable across restarts.
--
-- Rows carry no PII (status + aggregate counts). ON DELETE CASCADE from
-- auth.users cleans them up when an account is erased (GDPR).

CREATE TABLE IF NOT EXISTS public.import_jobs (
  id          TEXT PRIMARY KEY,
  user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  status      TEXT NOT NULL DEFAULT 'pending',   -- pending | processing | done | error
  result      JSONB NOT NULL DEFAULT '{}'::jsonb, -- inserted/duplicatesSkipped/… on success
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_import_jobs_user
  ON public.import_jobs (user_id, created_at DESC);

-- Defense-in-depth (the app already filters by user_id via the repo() wrapper).
ALTER TABLE public.import_jobs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'import_jobs'
      AND policyname = 'Users see own import jobs'
  ) THEN
    CREATE POLICY "Users see own import jobs" ON public.import_jobs
      FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
  END IF;
END $$;
