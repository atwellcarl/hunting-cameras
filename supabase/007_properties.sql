-- Buck Book: every photo and every buck belongs to one property (Stoddard or North Ridge).
-- Paste into the Supabase SQL Editor and run once, after 006_cant_id.sql.
-- The properties are ~9 miles apart, so a buck is never shared between them.

-- ---------- photos: real property names ----------
update public.cards set property = 'Stoddard' where property = 'Property A';
update public.cards set property = 'North Ridge' where property = 'Property B';
alter table public.cards drop constraint if exists cards_property_check;
alter table public.cards add constraint cards_property_check check (property in ('Stoddard', 'North Ridge'));

-- ---------- bucks: each belongs to a property ----------
alter table public.bucks add column if not exists property text;

-- Backfill from the photos members have tagged him in (most common property), else his cover photo.
update public.bucks b set property = coalesce(
  (select c.property
     from public.votes v join public.cards c on c.id = v.card_id
    where v.buck_id = b.id
    group by c.property order by count(*) desc limit 1),
  (select c.property from public.cards c where c.id = b.cover))
where b.property is null;

alter table public.bucks drop constraint if exists bucks_property_check;
alter table public.bucks add constraint bucks_property_check check (property in ('Stoddard', 'North Ridge'));
create index if not exists bucks_property on public.bucks (property);

-- ---------- keep votes inside one property ----------
create or replace function public.check_vote_property()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if new.buck_id is not null and
     (select property from public.bucks where id = new.buck_id) is distinct from
     (select property from public.cards where id = new.card_id) then
    raise exception 'That buck is from the other property';
  end if;
  return new;
end;
$$;

drop trigger if exists votes_same_property on public.votes;
create trigger votes_same_property before insert or update of buck_id on public.votes
  for each row execute function public.check_vote_property();

-- Merges stay inside one property too.
create or replace function public.merge_bucks(from_id text, into_id text)
returns integer
language plpgsql security definer set search_path = ''
as $$
declare moved integer;
begin
  if not public.is_crew() then raise exception 'Crew only'; end if;
  if from_id = into_id then raise exception 'Pick a different buck to merge into'; end if;
  if not exists (select 1 from public.bucks where id = into_id) then raise exception 'That buck is gone'; end if;
  if (select property from public.bucks where id = from_id) is distinct from
     (select property from public.bucks where id = into_id) then
    raise exception 'Those bucks are on different properties';
  end if;
  update public.votes set buck_id = into_id where buck_id = from_id;
  get diagnostics moved = row_count;
  update public.bucks b set cover = coalesce(b.cover, (select cover from public.bucks where id = from_id)) where b.id = into_id;
  delete from public.bucks where id = from_id;
  return moved;
end;
$$;

-- ---------- check ----------
-- Every buck should now have a property; this lists any that don't (expect no rows).
select id, name from public.bucks where property is null;
