-- Buck Book: swipe left is now "pass" (not worth naming), and passed photos get dropped.
-- Paste into the Supabase SQL Editor and run once, after 008_member_types.sql.
--
-- A photo is ready to drop when nobody has called it a keeper (verdict 'buck') and either
--   * two members passed on it (verdict 'not'), or
--   * one member passed on it at least 14 days ago.
-- The Mac's `supabase_sync prune` deletes the photo files for those and marks the row dropped.
-- The row stays so uploads and Hit List imports don't bring the photo back, and its camera and
-- time stay in the record. Originals are still on the Mac if a photo ever needs restoring.

alter table public.cards add column if not exists dropped_at timestamptz;
alter table public.cards alter column crop_path drop not null;   -- emptied once the file is deleted
alter table public.cards alter column frame_path drop not null;

create or replace view public.card_drop
with (security_invoker = true) as
select card_id,
       count(*) filter (where verdict = 'not') as passes,
       count(*) filter (where verdict = 'buck') as keepers,
       min(at) filter (where verdict = 'not') as first_pass_at,
       count(*) filter (where verdict = 'buck') = 0
         and (count(*) filter (where verdict = 'not') >= 2
              or min(at) filter (where verdict = 'not') <= now() - interval '14 days') as droppable
from public.votes
group by card_id;

-- Check: how many photos would be dropped right now.
select count(*) as ready_to_drop from public.card_drop where droppable;
