-- Buck Book on Supabase: tables, access rules, photo bucket, live updates.
-- Paste into the Supabase SQL Editor and run once. Safe to re-run.
--
-- Access model: every table and photo is readable/writable only by crew. Crew
-- accounts are created by the owner with buckbook/crew_admin.py (a login plus a
-- public.crew row); sign-ups are turned off in the dashboard.

-- ---------- tables ----------
create table if not exists public.crew (
  user_id uuid primary key references auth.users(id) on delete cascade,
  name text not null check (char_length(trim(name)) between 1 and 30),
  joined_at timestamptz not null default now()
);

create table if not exists public.cards (
  id text primary key,
  camera text not null,
  property text,
  taken_at timestamp not null,          -- local camera time
  daylight boolean,
  temp_f real,
  wind text,
  moon text,
  pressure real,
  burst integer,
  crop_path text not null,              -- object path in the photos bucket
  frame_path text not null,
  created_at timestamptz not null default now()
);
create index if not exists cards_camera_taken on public.cards (camera, taken_at);

create table if not exists public.bucks (
  id text primary key,
  name text not null check (char_length(trim(name)) between 1 and 40),
  cover text references public.cards(id) on delete set null,
  by_user uuid,
  by_name text,
  at timestamptz not null default now()
);

create table if not exists public.labels (
  card_id text primary key references public.cards(id) on delete cascade,
  verdict text not null check (verdict in ('buck', 'not', 'unsure')),
  buck_id text references public.bucks(id),   -- blocks deleting a buck that still has photos
  points integer check (points between 0 and 40),
  confidence integer check (confidence between 1 and 5),
  by_user uuid,
  by_name text,                                -- leaderboard groups by name across devices
  at timestamptz not null default now()
);

-- ---------- helpers ----------
create or replace function public.is_crew()
returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (select 1 from public.crew where user_id = auth.uid());
$$;

-- Stamp who/when on client writes. Writes made with the secret key (auth.uid() is null,
-- e.g. the uploader importing old labels) keep the values they send.
create or replace function public.stamp_author()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if auth.uid() is not null then
    new.by_user := auth.uid();
    new.by_name := (select name from public.crew where user_id = auth.uid());
    new.at := now();
  end if;
  return new;
end;
$$;

drop trigger if exists labels_stamp on public.labels;
create trigger labels_stamp before insert or update on public.labels
  for each row execute function public.stamp_author();

-- Buck creator is set once; renames keep the original author.
create or replace function public.stamp_buck()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if auth.uid() is not null then
    if tg_op = 'INSERT' then
      new.by_user := auth.uid();
      new.by_name := (select name from public.crew where user_id = auth.uid());
      new.at := now();
    else
      new.by_user := old.by_user;
      new.by_name := old.by_name;
      new.at := old.at;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists bucks_stamp on public.bucks;
create trigger bucks_stamp before insert or update on public.bucks
  for each row execute function public.stamp_buck();

-- ---------- row level security ----------
alter table public.crew enable row level security;
alter table public.cards enable row level security;
alter table public.bucks enable row level security;
alter table public.labels enable row level security;

drop policy if exists "crew read crew" on public.crew;
create policy "crew read crew" on public.crew for select to authenticated using (public.is_crew());

drop policy if exists "crew read cards" on public.cards;
create policy "crew read cards" on public.cards for select to authenticated using (public.is_crew());

drop policy if exists "crew read bucks" on public.bucks;
create policy "crew read bucks" on public.bucks for select to authenticated using (public.is_crew());
drop policy if exists "crew add bucks" on public.bucks;
create policy "crew add bucks" on public.bucks for insert to authenticated with check (public.is_crew());
drop policy if exists "crew rename bucks" on public.bucks;
create policy "crew rename bucks" on public.bucks for update to authenticated using (public.is_crew()) with check (public.is_crew());
drop policy if exists "crew delete bucks" on public.bucks;
create policy "crew delete bucks" on public.bucks for delete to authenticated using (public.is_crew());

drop policy if exists "crew read labels" on public.labels;
create policy "crew read labels" on public.labels for select to authenticated using (public.is_crew());
drop policy if exists "crew add labels" on public.labels;
create policy "crew add labels" on public.labels for insert to authenticated with check (public.is_crew());
drop policy if exists "crew change labels" on public.labels;
create policy "crew change labels" on public.labels for update to authenticated using (public.is_crew()) with check (public.is_crew());
drop policy if exists "crew delete labels" on public.labels;
create policy "crew delete labels" on public.labels for delete to authenticated using (public.is_crew());

-- ---------- photos bucket (private) ----------
insert into storage.buckets (id, name, public)
values ('photos', 'photos', false)
on conflict (id) do update set public = false;

drop policy if exists "crew read photos" on storage.objects;
create policy "crew read photos" on storage.objects for select to authenticated
  using (bucket_id = 'photos' and public.is_crew());

-- ---------- live updates ----------
do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'labels') then
    alter publication supabase_realtime add table public.labels;
  end if;
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'bucks') then
    alter publication supabase_realtime add table public.bucks;
  end if;
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'crew') then
    alter publication supabase_realtime add table public.crew;
  end if;
end $$;
