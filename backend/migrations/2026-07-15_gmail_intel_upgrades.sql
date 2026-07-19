-- Gmail intel upgrades (2026-07-15)
-- Feature 1: multi-contact + domain matching — additional client addresses.
-- Feature 4: Gmail real-time push (watch) state per connection.

alter table clients
  add column if not exists contact_emails text[] default '{}';

alter table google_connections
  add column if not exists watch_history_id text,
  add column if not exists watch_expiration timestamptz;
