-- Supervisor approval queue (2026-05-31)
-- Human-in-the-loop tasks the supervisor proposes for the owner to Approve/Dismiss.
-- Run once in the Supabase SQL Editor for an existing project.

create table if not exists public.manager_tasks (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references public.users(id) on delete cascade,
  kind text not null,
  title text not null,
  rationale text,
  severity text not null default 'info' check (severity in ('info','warning','critical')),
  status text not null default 'proposed' check (status in ('proposed','approved','dismissed','done','failed')),
  payload jsonb not null default '{}'::jsonb,
  source_record_type text,
  source_record_id uuid,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

alter table public.manager_tasks enable row level security;

do $$ begin
  create policy "Users see own manager_tasks" on public.manager_tasks
    for all using (auth.uid() = user_id);
exception when duplicate_object then null; end $$;

create index if not exists idx_manager_tasks_user_status
  on public.manager_tasks (user_id, status);
