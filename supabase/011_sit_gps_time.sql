-- Buck Book: record when a sit's GPS fix was taken.
-- Paste into the Supabase SQL Editor and run once, after 010_sits.sql.

alter table public.sits add column if not exists gps_at timestamptz;   -- when the phone finished averaging the fix
