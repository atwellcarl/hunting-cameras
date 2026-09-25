# Working on Buck Book

Read `README.md` first for architecture, commands, and the data model. This file is the working rules.

## Hard rules

- **Never trigger a camera.** Reveal scripts are read-only: one Cognito login, then GETs. Never call `photo-request`, `video-request`, HD requests, or `POST /cameras/{id}`. The Reveal login is shared by several people, so poll gently (`PAUSE` in `reveal_poc.py`).
- **This repo is public.** Never commit `.env`, anything under `data/`, `FINDINGS.md`, GPS coordinates, SIM/ICCID numbers, passwords, or crew members' names. `web/config.js` holds only the publishable key, which is meant to be public.
- **Size check before every upload.** Run `supabase_sync push` without `--yes` first and show the user the size against the 1 GB free tier. Upload only after they approve.
- **Deletes need a backup and a yes.** Back up to `data/backups/` before deleting or rewriting production rows, and confirm with the user first. Check who created something before clearing it; other crew members' work is not ours to delete.

## How the user works

- Locations in **MGRS** (e.g. `15T AB 12345 67890`, 10-digit = 1 m), not lat/lon. Use the `mgrs` package in `.venv`.
- Properties are **Stoddard** and **North Ridge**; bucks never cross between them.
- The user applies SQL migrations in the Supabase SQL Editor and pushes git themselves. Write migrations as new numbered files in `supabase/`; don't edit applied ones. Remind them to run the SQL *before* pushing a page that depends on it.
- Qwen runs heat and drain the laptop. Start or stop it when asked; `tag_deer.py` resumes where it left off, so stopping loses nothing.

## Testing changes to the app

Test against production with **temporary** data, then remove it:

1. Create throwaway crew with the admin API and `crew_admin.email_for` (names like "Test A"). Get a session token with the password grant; never type a password into a page.
2. Use temporary cards with ids `zz-uitest-*` copied from real ones, and bucks named `ZZ …`, so no real vote is touched.
3. Serve `web/` with `python -m http.server 8790` and drive it in the browser pane. Put the session in a git-ignored `web/_test_session.json` and apply it with `sb.auth.setSession`.
4. Clean up: delete the `zz-uitest-*` cards (votes and comments cascade), the `ZZ` bucks, and the test users; remove the session file. Confirm production is back to its real counts.

Check page syntax by extracting the last `<script>` block and running `node --check`.

## Gotchas already hit

- Class-name collisions in the single-file page: the header once used `.top`, which squeezed the swipe card's photo to 89 px. Check new class names aren't already taken.
- The zoom viewer (`z-index` 40) sits above sheets (20). Close it before opening a sheet from it.
- Supabase `sb_secret_` keys go in the `apikey` header only, not `Authorization: Bearer`.
- Vote authorship is stamped by trigger; only a member's own edits re-stamp (merges keep the original voter).
- Placeholder login emails use `@buckbook.invalid` (Supabase accepts it; it can never receive mail). Keep the Python and JS name-to-email mappings identical.
