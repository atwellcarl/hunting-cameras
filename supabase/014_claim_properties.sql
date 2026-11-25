-- Buck Book: anyone on the crew (admins and users, not guests) can add a property by picking its parcels
-- on the map, and change which parcels are in it later. Paste into the Supabase SQL Editor and run once,
-- after 013_map.sql.
--
-- Until now the two properties were written into every table ('Stoddard', 'North Ridge'). Sits, spots,
-- parcels and camera positions now point at the properties table instead, so a new property can have
-- them too. Photos and bucks stay Stoddard and North Ridge: they come from the cameras there.
-- A property's parcels are rows in parcels with ours = true. A parcel can belong to more than one
-- property's map (one's ground is another's neighbor), so its key is now (property, id).

-- ---------- drop every check that lists the two properties ----------
-- (on properties, sits, spots, camera_spots and parcels; photos and bucks keep theirs)
do $$
declare r record;
begin
  for r in select c.conrelid::regclass as tbl, c.conname from pg_constraint c
            where c.contype = 'c' and pg_get_constraintdef(c.oid) like '%North Ridge%'
              and c.conrelid in ('public.properties'::regclass, 'public.sits'::regclass, 'public.spots'::regclass,
                                 'public.camera_spots'::regclass, 'public.parcels'::regclass)
  loop
    execute format('alter table %s drop constraint %I', r.tbl, r.conname);
  end loop;
end $$;

-- ---------- properties ----------
alter table public.properties drop constraint if exists properties_name_check;
alter table public.properties add constraint properties_name_check
  check (name = btrim(name) and char_length(name) between 1 and 30);
alter table public.properties add column if not exists created_by uuid;
alter table public.properties add column if not exists created_by_name text;
alter table public.properties add column if not exists created_at timestamptz not null default now();
alter table public.properties add column if not exists parcels_at timestamptz;   -- when its parcels last changed: phones refetch parcels when this moves

-- Who added a property is stamped here, so nobody can sign someone else's name.
create or replace function public.stamp_property()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    if auth.uid() is not null then
      new.created_by := auth.uid();
      new.created_by_name := (select name from public.crew where user_id = auth.uid());
    end if;
    new.created_at := now();
  else
    new.name := old.name;                          -- no renames from the app (everything points at the name)
    new.created_by := old.created_by;
    new.created_by_name := old.created_by_name;
    new.created_at := old.created_at;
  end if;
  return new;
end;
$$;
drop trigger if exists properties_stamp on public.properties;
create trigger properties_stamp before insert or update on public.properties
  for each row execute function public.stamp_property();

-- ---------- everything that names a property points at the table ----------
alter table public.sits drop constraint if exists sits_property_fkey;
alter table public.sits add constraint sits_property_fkey foreign key (property) references public.properties (name);

alter table public.spots drop constraint if exists spots_property_fkey;
alter table public.spots add constraint spots_property_fkey foreign key (property) references public.properties (name);

alter table public.camera_spots drop constraint if exists camera_spots_property_fkey;
alter table public.camera_spots add constraint camera_spots_property_fkey foreign key (property) references public.properties (name);

alter table public.parcels drop constraint if exists parcels_property_fkey;
alter table public.parcels add constraint parcels_property_fkey foreign key (property) references public.properties (name);
alter table public.parcels drop constraint if exists parcels_pkey;
alter table public.parcels add primary key (property, id);

-- After this, the only property names allowed anywhere above are the rows of properties. Check:
--   select name, created_by_name from public.properties;

-- ---------- who can do what ----------
-- Admins and users add properties. Whoever added one (or an admin) can change it: its parcels, its map
-- box, its weather spot. Stoddard and North Ridge were added by no one, so they stay admins-only.
create or replace function public.can_change_property(p text)
returns boolean
language sql stable security definer set search_path = ''
as $$
  select public.is_admin() or exists (select 1 from public.properties where name = p and created_by = auth.uid());
$$;

drop policy if exists "members add properties" on public.properties;
create policy "members add properties" on public.properties for insert to authenticated
  with check (public.can_edit());
drop policy if exists "owner changes property" on public.properties;
create policy "owner changes property" on public.properties for update to authenticated
  using (public.can_edit() and public.can_change_property(name))
  with check (public.can_edit() and public.can_change_property(name));

drop policy if exists "owner adds parcels" on public.parcels;
create policy "owner adds parcels" on public.parcels for insert to authenticated
  with check (public.can_edit() and public.can_change_property(property));
drop policy if exists "owner changes parcels" on public.parcels;
create policy "owner changes parcels" on public.parcels for update to authenticated
  using (public.can_edit() and public.can_change_property(property))
  with check (public.can_edit() and public.can_change_property(property));
