-- Buck Book: member types, and merging two bucks by agreement (or by an admin).
-- Paste into the Supabase SQL Editor and run once, after 007_properties.sql.
--
-- crew.user_type: admin (everything, plus merge straight away), user (the default: vote,
-- comment, name and edit bucks, propose merges), viewer (read-only). Set from the Mac:
-- crew_admin type "Name" admin|user|viewer.
--
-- Anyone can propose merging two bucks and which name to keep. It happens once the member
-- who named each buck (bucks.by_user) has agreed; if one member named both, their yes is enough.
-- Either of them can say "not the same buck", which closes the proposal.
-- Admins merge straight away, to clean up.

-- ---------- member types ----------
alter table public.crew add column if not exists user_type text not null default 'user'
  check (user_type in ('admin', 'user', 'viewer'));
-- Members can only read the crew table (no insert/update policy), so nobody can change their own type.

create or replace function public.is_admin()
returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (select 1 from public.crew where user_id = auth.uid() and user_type = 'admin');
$$;

-- Admins and users can change things; viewers only look.
create or replace function public.can_edit()
returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (select 1 from public.crew where user_id = auth.uid() and user_type in ('admin', 'user'));
$$;

-- ---------- viewers are read-only ----------
drop policy if exists "crew add bucks" on public.bucks;
create policy "crew add bucks" on public.bucks for insert to authenticated with check (public.can_edit());
drop policy if exists "crew rename bucks" on public.bucks;
create policy "crew rename bucks" on public.bucks for update to authenticated using (public.can_edit()) with check (public.can_edit());
drop policy if exists "crew delete bucks" on public.bucks;
create policy "crew delete bucks" on public.bucks for delete to authenticated using (public.can_edit());

drop policy if exists "crew cast own vote" on public.votes;
create policy "crew cast own vote" on public.votes for insert to authenticated
  with check (public.can_edit() and voter = auth.uid());
drop policy if exists "crew change own vote" on public.votes;
create policy "crew change own vote" on public.votes for update to authenticated
  using (public.can_edit() and voter = auth.uid()) with check (public.can_edit());
drop policy if exists "crew withdraw own vote" on public.votes;
create policy "crew withdraw own vote" on public.votes for delete to authenticated
  using (public.can_edit() and voter = auth.uid());

drop policy if exists "crew post comments" on public.comments;
create policy "crew post comments" on public.comments for insert to authenticated
  with check (public.can_edit() and author = auth.uid());
drop policy if exists "crew delete own comments" on public.comments;
create policy "crew delete own comments" on public.comments for delete to authenticated
  using (public.can_edit() and author = auth.uid());

create or replace function public.delete_buck(buck text)
returns integer
language plpgsql security definer set search_path = ''
as $$
declare unnamed integer;
begin
  if not public.can_edit() then raise exception 'Viewers can''t change the book'; end if;
  update public.votes set buck_id = null, confidence = null where buck_id = buck;
  get diagnostics unnamed = row_count;
  delete from public.bucks where id = buck;
  return unnamed;
end;
$$;

-- ---------- proposals ----------
-- One row per pair of bucks (buck_a < buck_b). yes = members who agreed to keep keep_id.
create table if not exists public.merge_proposals (
  buck_a text not null references public.bucks(id) on delete cascade,
  buck_b text not null references public.bucks(id) on delete cascade,
  keep_id text not null,
  status text not null default 'open' check (status in ('open', 'rejected')),
  proposed_by uuid,
  proposed_by_name text,
  yes uuid[] not null default '{}',
  rejected_by_name text,
  at timestamptz not null default now(),
  primary key (buck_a, buck_b),
  check (buck_a < buck_b),
  check (keep_id in (buck_a, buck_b))
);
alter table public.merge_proposals enable row level security;
drop policy if exists "crew read merge proposals" on public.merge_proposals;
create policy "crew read merge proposals" on public.merge_proposals for select to authenticated using (public.is_crew());
-- No write policies: members change proposals only through vote_merge() below.

do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'merge_proposals') then
    alter publication supabase_realtime add table public.merge_proposals;
  end if;
end $$;

-- ---------- the merge itself (internal) ----------
create or replace function public.do_merge(from_id text, into_id text)
returns integer
language plpgsql security definer set search_path = ''
as $$
declare moved integer;
begin
  if from_id = into_id then raise exception 'Pick a different buck to merge into'; end if;
  if not exists (select 1 from public.bucks where id = into_id) then raise exception 'That buck is gone'; end if;
  if (select property from public.bucks where id = from_id) is distinct from
     (select property from public.bucks where id = into_id) then
    raise exception 'Those bucks are on different properties';
  end if;
  update public.votes set buck_id = into_id where buck_id = from_id;
  get diagnostics moved = row_count;
  update public.bucks b set cover = coalesce(b.cover, (select cover from public.bucks where id = from_id)) where b.id = into_id;
  delete from public.bucks where id = from_id;   -- its proposals go with it
  return moved;
end;
$$;
revoke execute on function public.do_merge(text, text) from public, anon, authenticated;

-- Admins: merge now.
create or replace function public.merge_bucks(from_id text, into_id text)
returns integer
language plpgsql security definer set search_path = ''
as $$
begin
  if not public.is_admin() then raise exception 'Only an admin can merge straight away. Propose it instead.'; end if;
  return public.do_merge(from_id, into_id);
end;
$$;

-- Everyone: propose, agree, or say no. Returns 'merged', 'waiting' or 'rejected'.
create or replace function public.vote_merge(buck1 text, buck2 text, keep text, agree boolean)
returns text
language plpgsql security definer set search_path = ''
as $$
declare
  a text := least(buck1, buck2);
  b text := greatest(buck1, buck2);
  me uuid := auth.uid();
  my_name text := (select name from public.crew where user_id = auth.uid());
  author_a uuid := (select by_user from public.bucks where id = least(buck1, buck2));
  author_b uuid := (select by_user from public.bucks where id = greatest(buck1, buck2));
  p public.merge_proposals;
begin
  if not public.can_edit() then raise exception 'Viewers can''t change the book'; end if;
  if a = b then raise exception 'Pick two different bucks'; end if;
  if (select count(*) from public.bucks where id in (a, b)) < 2 then raise exception 'That buck is gone'; end if;
  if keep is null or keep not in (a, b) then raise exception 'Keep one of the two names'; end if;
  if (select property from public.bucks where id = a) is distinct from (select property from public.bucks where id = b) then
    raise exception 'Those bucks are on different properties';
  end if;

  if not agree then
    if me is distinct from author_a and me is distinct from author_b and not public.is_admin() then
      raise exception 'Only the members who named these bucks can call them different';
    end if;
    insert into public.merge_proposals (buck_a, buck_b, keep_id, status, rejected_by_name, at)
      values (a, b, keep, 'rejected', my_name, now())
      on conflict (buck_a, buck_b) do update set status = 'rejected', rejected_by_name = my_name, yes = '{}', at = now();
    return 'rejected';
  end if;

  select * into p from public.merge_proposals where buck_a = a and buck_b = b;
  if not found or p.status = 'rejected' or p.keep_id <> keep then
    -- A new proposal, or a different name to keep: start the agreement over.
    insert into public.merge_proposals (buck_a, buck_b, keep_id, status, proposed_by, proposed_by_name, yes, rejected_by_name, at)
      values (a, b, keep, 'open', me, my_name, array[me], null, now())
      on conflict (buck_a, buck_b) do update set keep_id = excluded.keep_id, status = 'open', proposed_by = excluded.proposed_by,
        proposed_by_name = excluded.proposed_by_name, yes = excluded.yes, rejected_by_name = null, at = now()
      returning * into p;
  elsif not (me = any(p.yes)) then
    update public.merge_proposals set yes = array_append(yes, me) where buck_a = a and buck_b = b returning * into p;
  end if;

  if author_a is not null and author_b is not null and author_a = any(p.yes) and author_b = any(p.yes) then
    perform public.do_merge(case when keep = a then b else a end, keep);
    return 'merged';
  end if;
  return 'waiting';
end;
$$;
revoke execute on function public.vote_merge(text, text, text, boolean) from public, anon;
grant execute on function public.vote_merge(text, text, text, boolean) to authenticated;
