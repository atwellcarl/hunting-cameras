-- Buck Book: "Can't ID him": a buck, but the photo is too rough to say which one.
-- Paste into the Supabase SQL Editor and run once, after 005_buck_editing.sql.

alter table public.votes
  add column if not exists cant_id boolean not null default false;

-- Same consensus as before, plus how many members said "can't ID" on each photo.
-- A buck photo with no named buck and at least one "can't ID" is filed as Unidentified;
-- with no named buck and no "can't ID" it waits in the Name-them queue.
create or replace view public.card_consensus
with (security_invoker = true) as
with tally as (
  select card_id,
         count(*) as votes,
         count(*) filter (where verdict = 'buck') as buck_votes,
         count(*) filter (where verdict = 'not') as not_votes,
         count(*) filter (where verdict = 'buck' and cant_id) as cant_id_votes
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
       end as status,
       t.cant_id_votes
from tally t
left join ranked r on r.card_id = t.card_id and r.rk = 1;
