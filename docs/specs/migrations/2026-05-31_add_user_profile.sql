-- Business Profile (2026-05-31)
-- Adds a flexible JSONB column on users to hold the owner + business profile
-- (business type, industry, offerings, payment prefs, financial goals, brand tone).
-- Run once in the Supabase SQL Editor for an existing project.

alter table public.users
  add column if not exists profile jsonb not null default '{}'::jsonb;
