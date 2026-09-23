-- Switch Buck Book from a shared crew passcode to individual accounts.
-- Paste into the Supabase SQL Editor and run once, after schema.sql.
--
-- Crew accounts are now created by the owner with buckbook/crew_admin.py, which
-- creates the login and the matching public.crew row. Nobody can add themselves.

drop function if exists public.join_crew(text, text);
drop function if exists public.set_crew_passcode(text);
drop table if exists private.settings;
drop schema if exists private;
