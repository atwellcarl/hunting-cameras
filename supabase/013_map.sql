-- Buck Book: the map. Paste into the Supabase SQL Editor and run once, after 012_sit_event_species.sql.
--
-- Everything here is a location, so it lives only in the database, readable by the crew, never in the repo.
--   properties     gets the box each property's map covers (its parcels plus a margin), set by map_data.py.
--   camera_spots   where each camera has stood: one row per position, from the GPS on its photos
--                  (map_data.py), or placed by hand on the map for cameras that send no GPS.
--   parcels        Wisconsin statewide parcel lines around each property (public record), and which are ours.
--   spots          anything the crew marks on the map: stands, scrapes, rubs, bedding, crossings, notes.
--
-- Everyone signed in can see the map, viewers too. Everyone, viewers included, can add spots and change
-- or delete their own; admins can change anyone's. Admins decide which parcels are ours. Admins and users
-- can place a camera that sends no GPS. Sits stay admins-and-users only (010_sits.sql).

-- ---------- the area each property's map covers ----------
alter table public.properties add column if not exists map_west double precision;
alter table public.properties add column if not exists map_south double precision;
alter table public.properties add column if not exists map_east double precision;
alter table public.properties add column if not exists map_north double precision;

-- ---------- cameras ----------
create table if not exists public.camera_spots (
  id text primary key,                         -- '<reveal camera id>:<first photo date>' or 'placed:<uuid>'
  camera text not null,                        -- the name the photos use (cards.camera), e.g. '#2'
  reveal_name text,                            -- what Reveal calls it now, if different
  property text check (property in ('Stoddard', 'North Ridge')),
  lat double precision,                        -- null until placed, for cameras that send no GPS
  lon double precision,
  first_at timestamptz,                        -- first and last photo taken here
  last_at timestamptz,
  photos integer,
  source text not null default 'photos' check (source in ('photos', 'placed')),
  placed_by uuid,
  placed_by_name text,
  updated_at timestamptz not null default now()
);
create index if not exists camera_spots_camera on public.camera_spots (camera, last_at desc);

-- ---------- parcels ----------
create table if not exists public.parcels (
  id text primary key,                         -- the state's parcel id (STATEID)
  property text not null check (property in ('Stoddard', 'North Ridge')),   -- whose map it's drawn on
  ours boolean not null default false,
  owner text,
  owner2 text,
  acres real,
  geom jsonb not null,                         -- GeoJSON Polygon or MultiPolygon, WGS84
  updated_at timestamptz not null default now()
);
create index if not exists parcels_property on public.parcels (property);

-- ---------- spots ----------
-- ids are made on the phone, so a spot added without signal can be sent more than once without duplicating.
create table if not exists public.spots (
  id uuid primary key,
  property text not null check (property in ('Stoddard', 'North Ridge')),
  kind text not null check (kind in ('stand', 'saddle', 'scrape', 'rub', 'bedding', 'crossing', 'food', 'water', 'parking', 'other')),
  label text check (char_length(label) <= 40),
  notes text check (char_length(notes) <= 500),
  lat double precision not null,
  lon double precision not null,
  created_by uuid default auth.uid(),
  created_by_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists spots_property on public.spots (property);

-- Who added a spot (or placed a camera) is stamped here, so nobody can sign someone else's name.
create or replace function public.stamp_spot()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if auth.uid() is not null then
    if tg_op = 'INSERT' then
      new.created_by := auth.uid();
      new.created_by_name := (select name from public.crew where user_id = auth.uid());
    else
      new.created_by := old.created_by;          -- an admin's fix keeps who added it
      new.created_by_name := old.created_by_name;
    end if;
  end if;
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists spots_stamp on public.spots;
create trigger spots_stamp before insert or update on public.spots
  for each row execute function public.stamp_spot();

create or replace function public.stamp_camera_spot()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if auth.uid() is not null then                 -- placed from the app (map_data.py uses the secret key)
    new.source := 'placed';
    new.placed_by := auth.uid();
    new.placed_by_name := (select name from public.crew where user_id = auth.uid());
  end if;
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists camera_spots_stamp on public.camera_spots;
create trigger camera_spots_stamp before insert or update on public.camera_spots
  for each row execute function public.stamp_camera_spot();

-- ---------- access ----------
alter table public.camera_spots enable row level security;
alter table public.parcels enable row level security;
alter table public.spots enable row level security;

-- Viewers see the map too, so the property boxes are readable by all crew now (the weather towns with them).
drop policy if exists "crew read properties" on public.properties;
create policy "crew read properties" on public.properties for select to authenticated using (public.is_crew());

drop policy if exists "crew read camera spots" on public.camera_spots;
create policy "crew read camera spots" on public.camera_spots for select to authenticated using (public.is_crew());
drop policy if exists "members place cameras" on public.camera_spots;
create policy "members place cameras" on public.camera_spots for insert to authenticated
  with check (public.can_edit() and id like 'placed:%');
drop policy if exists "members move placed cameras" on public.camera_spots;
create policy "members move placed cameras" on public.camera_spots for update to authenticated
  using (public.can_edit() and source = 'placed') with check (public.can_edit() and id like 'placed:%');
drop policy if exists "members remove placed cameras" on public.camera_spots;
create policy "members remove placed cameras" on public.camera_spots for delete to authenticated
  using (public.can_edit() and source = 'placed');

drop policy if exists "crew read parcels" on public.parcels;
create policy "crew read parcels" on public.parcels for select to authenticated using (public.is_crew());
drop policy if exists "admins mark parcels" on public.parcels;
create policy "admins mark parcels" on public.parcels for update to authenticated
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists "crew read spots" on public.spots;
create policy "crew read spots" on public.spots for select to authenticated using (public.is_crew());
drop policy if exists "crew add spots" on public.spots;
create policy "crew add spots" on public.spots for insert to authenticated with check (public.is_crew());
drop policy if exists "owner changes spot" on public.spots;
create policy "owner changes spot" on public.spots for update to authenticated
  using (public.is_crew() and (created_by = auth.uid() or public.is_admin()))
  with check (public.is_crew() and (created_by = auth.uid() or public.is_admin()));
drop policy if exists "owner deletes spot" on public.spots;
create policy "owner deletes spot" on public.spots for delete to authenticated
  using (public.is_crew() and (created_by = auth.uid() or public.is_admin()));

do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'spots') then
    alter publication supabase_realtime add table public.spots;
  end if;
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'camera_spots') then
    alter publication supabase_realtime add table public.camera_spots;
  end if;
end $$;
