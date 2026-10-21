-- Buck Book: one sighting can hold several animals ("2 doe, 1 fawn and Tall Eight").
-- Paste into the Supabase SQL Editor and run once, after 011_sit_gps_time.sql.
--
-- sit_events is now what a group did together: when, which way it came and went, how far, a note,
-- and optionally when it ended and how (unnoticed, busted, winded, heard, spooked, shot, other).
-- Its kind is 'deer', 'animal' (any other animal) or 'wind' (a wind change, with wind_dir).
-- sit_event_members lists who was in it: a doe count, a fawn count, each buck (named or described),
-- or another animal by species ("raccoon" ×2). Nothing had been logged when this ran, so the old
-- per-event count/buck columns are simply replaced.

alter table public.sit_events drop column if exists count;
alter table public.sit_events drop column if exists buck_id;
alter table public.sit_events drop column if exists buck_note;
alter table public.sit_events drop constraint if exists sit_events_kind_check;
delete from public.sit_events where kind not in ('deer', 'animal', 'wind');   -- none expected
alter table public.sit_events add constraint sit_events_kind_check check (kind in ('deer', 'animal', 'wind'));

-- How a sighting ended, both optional: when it was over, and how (did they know you were there?).
alter table public.sit_events add column if not exists ended_at timestamptz;
alter table public.sit_events add column if not exists ended_how text
  check (ended_how in ('unnoticed', 'busted', 'winded', 'heard', 'spooked', 'shot', 'other'));

create table if not exists public.sit_event_members (
  id uuid primary key,                                         -- made on the phone, like events
  event_id uuid not null references public.sit_events(id) on delete cascade,
  kind text not null check (kind in ('doe', 'fawn', 'buck', 'animal')),
  species text check (char_length(species) <= 40),             -- for kind = 'animal': turkey, coyote, raccoon…
  count integer not null default 1 check (count between 1 and 50),
  buck_id text references public.bucks(id) on delete set null,  -- for a buck: a named buck from the book
  buck_note text check (char_length(buck_note) <= 60)           -- or a description: "spike", "small 6"
);
create index if not exists sit_event_members_event on public.sit_event_members (event_id);
create index if not exists sit_event_members_buck on public.sit_event_members (buck_id) where buck_id is not null;

alter table public.sit_event_members enable row level security;
drop policy if exists "crew read sit event members" on public.sit_event_members;
create policy "crew read sit event members" on public.sit_event_members for select to authenticated using (public.can_edit());
drop policy if exists "hunter writes sit event members" on public.sit_event_members;
create policy "hunter writes sit event members" on public.sit_event_members for all to authenticated
  using (public.owns_sit((select sit_id from public.sit_events where id = event_id)))
  with check (public.owns_sit((select sit_id from public.sit_events where id = event_id)));

do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'sit_event_members') then
    alter publication supabase_realtime add table public.sit_event_members;
  end if;
end $$;
