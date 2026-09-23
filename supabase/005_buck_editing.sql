-- Buck Book: edit bucks after the fact, and move photos between bucks.
-- Paste into the Supabase SQL Editor and run once, after 004_comments.sql.

-- ---------- buck attributes ----------
alter table public.bucks
  add column if not exists age_class text check (age_class in ('1.5', '2.5', '3.5', '4.5+')),
  add column if not exists status text not null default 'active' check (status in ('active', 'harvested', 'missing')),
  add column if not exists notes text check (char_length(notes) <= 500),
  add column if not exists updated_by_name text,
  add column if not exists updated_at timestamptz;

-- Creator is set once; edits record who last changed the buck and when.
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
      new.updated_by_name := (select name from public.crew where user_id = auth.uid());
      new.updated_at := now();
    end if;
  end if;
  return new;
end;
$$;

-- ---------- keep vote authorship through merges ----------
-- Only a member's own edits re-stamp their vote. When a merge (below) repoints someone
-- else's vote to a different buck, it stays credited to the person who cast it.
create or replace function public.stamp_voter()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if auth.uid() is null then
    return new;
  end if;
  if tg_op = 'UPDATE' and old.voter <> auth.uid() then
    new.voter := old.voter;
    new.voter_name := old.voter_name;
    new.at := old.at;
  else
    new.voter := auth.uid();
    new.voter_name := (select name from public.crew where user_id = auth.uid());
    new.at := now();
  end if;
  return new;
end;
$$;

-- ---------- merge two bucks that turn out to be the same deer ----------
-- Every vote naming `from_id` now names `into_id`; then `from_id` is removed.
create or replace function public.merge_bucks(from_id text, into_id text)
returns integer
language plpgsql security definer set search_path = ''
as $$
declare moved integer;
begin
  if not public.is_crew() then raise exception 'Crew only'; end if;
  if from_id = into_id then raise exception 'Pick a different buck to merge into'; end if;
  if not exists (select 1 from public.bucks where id = into_id) then raise exception 'That buck is gone'; end if;
  update public.votes set buck_id = into_id where buck_id = from_id;
  get diagnostics moved = row_count;
  update public.bucks b set cover = coalesce(b.cover, (select cover from public.bucks where id = from_id)) where b.id = into_id;
  delete from public.bucks where id = from_id;
  return moved;
end;
$$;
revoke execute on function public.merge_bucks(text, text) from public, anon;
grant execute on function public.merge_bucks(text, text) to authenticated;

-- ---------- delete a buck ----------
-- His photos stay as buck votes, just unnamed, so the crew can re-name them.
create or replace function public.delete_buck(buck text)
returns integer
language plpgsql security definer set search_path = ''
as $$
declare unnamed integer;
begin
  if not public.is_crew() then raise exception 'Crew only'; end if;
  update public.votes set buck_id = null, confidence = null where buck_id = buck;
  get diagnostics unnamed = row_count;
  delete from public.bucks where id = buck;
  return unnamed;
end;
$$;
revoke execute on function public.delete_buck(text) from public, anon;
grant execute on function public.delete_buck(text) to authenticated;

-- ---------- retire the pre-votes labels table ----------
-- Emptied and backed up on 2026-09-23 (data/backups/pre-clear-bucks-*.json).
drop table if exists public.labels_v1;
