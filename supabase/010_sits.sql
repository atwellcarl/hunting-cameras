-- Buck Book: sits (hunt notes). Paste into the Supabase SQL Editor and run once, after 009_pass_and_drop.sql.
--
-- A sit is one time in one tree: set and down times entered by the hunter (or a planned down time),
-- the wind the hunter felt, a GPS position averaged on the phone, and a timeline of events
-- (deer seen, wind changes). The weather service's hour-by-hour values are kept beside the
-- hunter's in sit_weather and never overwrite them.
--
-- Admins and users see every sit; viewers see none. Only the hunter (or an admin) can change one.
-- Positions live only here, never in the repo. Weather is looked up at each property's town, which
-- is set by hand (see the end of this file) so the repo doesn't say where the properties are.

-- ---------- weather town per property ----------
create table if not exists public.properties (
  name text primary key check (name in ('Stoddard', 'North Ridge')),
  weather_label text,              -- the town the weather comes from
  weather_lat double precision,
  weather_lon double precision
);
insert into public.properties (name) values ('Stoddard'), ('North Ridge') on conflict (name) do nothing;

-- ---------- sits ----------
-- ids are made on the phone, so a sit written without signal can be sent more than once without duplicating.
create table if not exists public.sits (
  id uuid primary key,
  hunter uuid not null default auth.uid(),
  hunter_name text,
  property text not null check (property in ('Stoddard', 'North Ridge')),
  spot text check (char_length(spot) <= 60),                  -- optional label, e.g. "Pole plot"
  lat double precision,
  lon double precision,
  gps_accuracy_m real,                                        -- the phone's own estimate, after averaging
  set_at timestamptz not null,
  planned_down_at timestamptz,
  down_at timestamptz,
  down_source text check (down_source in ('entered', 'planned', 'last_event', 'auto')),
  wind_dir text check (wind_dir in ('N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW','variable')),
  notes text check (char_length(notes) <= 2000),
  sunrise timestamptz,                                        -- filled with the weather
  sunset timestamptz,
  weather_at timestamptz,                                     -- when the weather was fetched
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists sits_property_set on public.sits (property, set_at desc);

-- One row per thing seen or felt during a sit.
create table if not exists public.sit_events (
  id uuid primary key,
  sit_id uuid not null references public.sits(id) on delete cascade,
  at timestamptz,                                             -- optional: "3 doe south to north" has no time
  kind text not null check (kind in ('doe', 'fawn', 'buck', 'turkey', 'predator', 'other', 'wind')),
  count integer check (count between 1 and 50),
  buck_id text references public.bucks(id) on delete set null,   -- a named buck from the book
  buck_note text check (char_length(buck_note) <= 60),           -- or a description: "spike", "small 6"
  from_dir text check (from_dir in ('N','NE','E','SE','S','SW','W','NW')),
  to_dir text check (to_dir in ('N','NE','E','SE','S','SW','W','NW')),
  distance_yd integer check (distance_yd between 0 and 1000),
  wind_dir text check (wind_dir in ('N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW','variable')),  -- kind = 'wind'
  note text check (char_length(note) <= 500),
  created_at timestamptz not null default now()
);
create index if not exists sit_events_sit on public.sit_events (sit_id, at);
create index if not exists sit_events_buck on public.sit_events (buck_id) where buck_id is not null;

-- The weather service's hour-by-hour values at the property's town, for the hours of the sit.
create table if not exists public.sit_weather (
  sit_id uuid not null references public.sits(id) on delete cascade,
  hour timestamptz not null,
  temp_f real,
  wind_from_deg real,
  wind_mph real,
  gust_mph real,
  pressure_hpa real,
  cloud_pct real,
  primary key (sit_id, hour)
);

-- ---------- who wrote it ----------
create or replace function public.stamp_sit()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if auth.uid() is not null then
    if tg_op = 'INSERT' then
      new.hunter := auth.uid();
      new.hunter_name := (select name from public.crew where user_id = auth.uid());
    else
      new.hunter := old.hunter;                 -- an admin's fix keeps the hunter
      new.hunter_name := old.hunter_name;
    end if;
  end if;
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists sits_stamp on public.sits;
create trigger sits_stamp before insert or update on public.sits
  for each row execute function public.stamp_sit();

-- The hunter of a sit, or an admin, may change it and its events and weather.
create or replace function public.owns_sit(sit uuid)
returns boolean
language sql stable security definer set search_path = ''
as $$
  select public.can_edit() and (public.is_admin() or exists (select 1 from public.sits where id = sit and hunter = auth.uid()));
$$;

-- ---------- access: admins and users only ----------
alter table public.properties enable row level security;
alter table public.sits enable row level security;
alter table public.sit_events enable row level security;
alter table public.sit_weather enable row level security;

drop policy if exists "crew read properties" on public.properties;
create policy "crew read properties" on public.properties for select to authenticated using (public.can_edit());

drop policy if exists "crew read sits" on public.sits;
create policy "crew read sits" on public.sits for select to authenticated using (public.can_edit());
drop policy if exists "hunter adds sit" on public.sits;
create policy "hunter adds sit" on public.sits for insert to authenticated with check (public.can_edit());
drop policy if exists "hunter changes sit" on public.sits;
create policy "hunter changes sit" on public.sits for update to authenticated
  using (public.owns_sit(id)) with check (public.owns_sit(id));
drop policy if exists "hunter deletes sit" on public.sits;
create policy "hunter deletes sit" on public.sits for delete to authenticated using (public.owns_sit(id));

drop policy if exists "crew read sit events" on public.sit_events;
create policy "crew read sit events" on public.sit_events for select to authenticated using (public.can_edit());
drop policy if exists "hunter writes sit events" on public.sit_events;
create policy "hunter writes sit events" on public.sit_events for all to authenticated
  using (public.owns_sit(sit_id)) with check (public.owns_sit(sit_id));

drop policy if exists "crew read sit weather" on public.sit_weather;
create policy "crew read sit weather" on public.sit_weather for select to authenticated using (public.can_edit());
drop policy if exists "hunter writes sit weather" on public.sit_weather;
create policy "hunter writes sit weather" on public.sit_weather for all to authenticated
  using (public.owns_sit(sit_id)) with check (public.owns_sit(sit_id));

do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'sits') then
    alter publication supabase_realtime add table public.sits;
  end if;
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'sit_events') then
    alter publication supabase_realtime add table public.sit_events;
  end if;
end $$;

-- ---------- after running this file ----------
-- Set each property's weather town in the Table Editor (properties table) or with an UPDATE,
-- run separately so the towns don't end up in the repo.
select name, weather_label, weather_lat, weather_lon from public.properties;
