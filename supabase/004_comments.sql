-- Buck Book: a comment thread on each photo, so the crew can talk disputes out.
-- Paste into the Supabase SQL Editor and run once, after 003_votes.sql.

create table if not exists public.comments (
  id bigint generated always as identity primary key,
  card_id text not null references public.cards(id) on delete cascade,
  author uuid not null default auth.uid(),
  author_name text,
  body text not null check (char_length(trim(body)) between 1 and 500),
  at timestamptz not null default now()
);
create index if not exists comments_card on public.comments (card_id, at);

-- Stamp the signed-in member as author; nobody can post as someone else.
create or replace function public.stamp_comment()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if auth.uid() is not null then
    new.author := auth.uid();
    new.author_name := (select name from public.crew where user_id = auth.uid());
    new.at := now();
  end if;
  return new;
end;
$$;

drop trigger if exists comments_stamp on public.comments;
create trigger comments_stamp before insert on public.comments
  for each row execute function public.stamp_comment();

alter table public.comments enable row level security;

drop policy if exists "crew read comments" on public.comments;
create policy "crew read comments" on public.comments for select to authenticated using (public.is_crew());
drop policy if exists "crew post comments" on public.comments;
create policy "crew post comments" on public.comments for insert to authenticated
  with check (public.is_crew() and author = auth.uid());
drop policy if exists "crew delete own comments" on public.comments;
create policy "crew delete own comments" on public.comments for delete to authenticated
  using (public.is_crew() and author = auth.uid());

do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'comments') then
    alter publication supabase_realtime add table public.comments;
  end if;
end $$;
