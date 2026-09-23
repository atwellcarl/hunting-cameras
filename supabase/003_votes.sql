-- Buck Book: one vote per crew member per photo, with consensus and rater agreement.
-- Paste into the Supabase SQL Editor and run once, after 002_accounts.sql.
--
-- Replaces the single-answer `labels` table (kept as labels_v1 for reference).
-- Every member's call is stored; nobody overwrites anyone else.

-- ---------- votes ----------
create table if not exists public.votes (
  card_id text not null references public.cards(id) on delete cascade,
  voter uuid not null default auth.uid(),
  voter_name text,
  verdict text not null check (verdict in ('buck', 'not')),
  buck_id text references public.bucks(id),     -- null = a buck, but not named
  points integer check (points between 0 and 40),
  confidence integer check (confidence between 1 and 5),  -- how sure this is that named buck
  at timestamptz not null default now(),
  primary key (card_id, voter)
);
create index if not exists votes_buck on public.votes (buck_id);

-- Client writes are always stamped as the signed-in member; they can't vote as someone else.
create or replace function public.stamp_voter()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if auth.uid() is not null then
    new.voter := auth.uid();
    new.voter_name := (select name from public.crew where user_id = auth.uid());
    new.at := now();
  end if;
  return new;
end;
$$;

drop trigger if exists votes_stamp on public.votes;
create trigger votes_stamp before insert or update on public.votes
  for each row execute function public.stamp_voter();

alter table public.votes enable row level security;

drop policy if exists "crew read votes" on public.votes;
create policy "crew read votes" on public.votes for select to authenticated using (public.is_crew());
drop policy if exists "crew cast own vote" on public.votes;
create policy "crew cast own vote" on public.votes for insert to authenticated
  with check (public.is_crew() and voter = auth.uid());   -- voter is stamped by the trigger first
drop policy if exists "crew change own vote" on public.votes;
create policy "crew change own vote" on public.votes for update to authenticated
  using (public.is_crew() and voter = auth.uid()) with check (public.is_crew());
drop policy if exists "crew withdraw own vote" on public.votes;
create policy "crew withdraw own vote" on public.votes for delete to authenticated
  using (public.is_crew() and voter = auth.uid());

do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'votes') then
    alter publication supabase_realtime add table public.votes;
  end if;
end $$;

-- ---------- move existing labels into votes ----------
-- Each label becomes a vote by the crew member it was credited to. 'unsure' labels
-- are dropped (that option no longer exists), so those photos return to the deck.
insert into public.votes (card_id, voter, voter_name, verdict, buck_id, points, confidence, at)
select l.card_id, c.user_id, c.name, l.verdict, l.buck_id, l.points, l.confidence, l.at
from public.labels l
join public.crew c on lower(c.name) = lower(l.by_name)
where l.verdict in ('buck', 'not')
on conflict (card_id, voter) do nothing;

alter table if exists public.labels rename to labels_v1;

-- ---------- consensus per photo ----------
-- Buck-or-not is a head count. Which buck is weighted by confidence (1-5, unrated = 3).
-- status: single (1 vote) | agreed | leaning (dissent, but >= 2/3 on top) | disputed.
create or replace view public.card_consensus
with (security_invoker = true) as
with tally as (
  select card_id,
         count(*) as votes,
         count(*) filter (where verdict = 'buck') as buck_votes,
         count(*) filter (where verdict = 'not') as not_votes
  from public.votes group by card_id
),
ids as (
  select card_id, buck_id,
         sum(coalesce(confidence, 3))::numeric as weight,
         count(*) as backers
  from public.votes
  where verdict = 'buck' and buck_id is not null
  group by card_id, buck_id
),
ranked as (
  select ids.*,
         row_number() over (partition by card_id order by weight desc, backers desc, buck_id) as rk,
         sum(weight) over (partition by card_id) as total_weight,
         count(*) over (partition by card_id) as options
  from ids
)
select t.card_id,
       t.votes, t.buck_votes, t.not_votes,
       case when t.buck_votes > t.not_votes then 'buck'
            when t.not_votes > t.buck_votes then 'not'
            else 'tied' end as verdict,
       round(greatest(t.buck_votes, t.not_votes)::numeric / t.votes, 2) as verdict_share,
       r.buck_id as top_buck,
       round(r.weight / nullif(r.total_weight, 0), 2) as top_share,
       coalesce(r.options, 0) as id_options,
       case
         when t.votes = 1 then 'single'
         when greatest(t.buck_votes, t.not_votes)::numeric / t.votes < 0.67 then 'disputed'
         when t.buck_votes > t.not_votes and r.options > 1 and r.weight / r.total_weight < 0.67 then 'disputed'
         when t.buck_votes > 0 and t.not_votes > 0 then 'leaning'
         when r.options > 1 then 'leaning'
         else 'agreed'
       end as status
from tally t
left join ranked r on r.card_id = t.card_id and r.rk = 1;

-- ---------- how often each pair of members agree ----------
-- Two votes agree when the verdict matches and, if both named a buck, it's the same buck.
-- An unnamed buck vote agrees with any buck vote on identity (it only took a side on buck-or-not).
create or replace view public.rater_pairs
with (security_invoker = true) as
select a.voter_name as member, b.voter_name as other,
       count(*) as shared,
       count(*) filter (where a.verdict = b.verdict
                          and (a.verdict = 'not' or a.buck_id is null or b.buck_id is null
                               or a.buck_id = b.buck_id)) as agreed
from public.votes a
join public.votes b on a.card_id = b.card_id and a.voter <> b.voter
group by a.voter_name, b.voter_name;

-- Each member's overall record: votes cast, and agreement with everyone else on shared photos.
create or replace view public.rater_scores
with (security_invoker = true) as
with cast_votes as (
  select voter_name as member, count(*) as votes from public.votes group by voter_name
),
pairs as (
  select member, sum(shared) as shared, sum(agreed) as agreed from public.rater_pairs group by member
)
select c.member, c.votes,
       coalesce(p.shared, 0) as shared,
       coalesce(p.agreed, 0) as agreed,
       round(p.agreed::numeric / nullif(p.shared, 0), 2) as agreement
from cast_votes c
left join pairs p on p.member = c.member;
