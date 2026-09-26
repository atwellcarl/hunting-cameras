# Buck Book

Trail-camera photos from Tactacam Reveal cell cams, sorted by a hunting crew into individual whitetail bucks.

A pipeline on a Mac pulls this season's photos from Reveal, finds the deer with local AI, and uploads the likely bucks to **Buck Book**, a phone-first web app. Crew members swipe each photo (buck or not), say which buck it is, and settle disagreements together. Everything is organized by property (**Stoddard** and **North Ridge**), and the app always works inside one of them.

## How it fits together

```
Tactacam Reveal (cloud)
   │  reveal_pull.py        read-only: photo records + standard-res images
   ▼
data/photos/<camera>/       on the Mac, git-ignored
   │  SpeciesNet            finds animals, labels species (deer / not)
   │  tag_deer.py           local Qwen vision model via Ollama: buck / doe / fawn
   ▼
data/tags/
   │  buckbook.import_deck  buck photos -> local staging deck (SQLite) + crops
   │  buckbook.supabase_sync push   size check, then upload
   ▼
Supabase (free tier)        Postgres + private photo storage + auth + realtime
   ▲
   │  web/  (GitHub Pages)  the Buck Book app, crew sign in with name + password
```

- **Nothing ever talks to a camera.** The Reveal scripts only read from Reveal's servers (one login, then GETs). They never request photos, videos, or HD, and never change settings, so they don't use cell data, plan photos, or battery.
- **AI suggests, people decide.** SpeciesNet and Qwen only decide which photos are worth a human's look. Every buck call and every name in the app comes from the crew. Qwen can't count antler points reliably at this resolution, so point counts are human-only.

## Repo layout

| Path | What it is |
|---|---|
| `reveal_poc.py` | Reveal login + API helpers (and a small read-only camera check) |
| `reveal_pull.py` | Pull photo records and images per camera, resumable |
| `tag_deer.py` | Crop each deer and ask the local Qwen model buck/doe/fawn; resumable JSONL output |
| `buckbook/import_deck.py` | Turn tagged bucks into cards in the local staging deck; recomputes bursts |
| `buckbook/supabase_sync.py` | `push` (with size check), `backup` |
| `buckbook/crew_admin.py` | Create / reset / remove crew accounts |
| `buckbook/db.py` | Local staging database (SQLite) |
| `supabase/*.sql` | Database schema and migrations, applied in order in the Supabase SQL Editor |
| `web/` | The Buck Book app (`index.html`) and its public Supabase config (`config.js`) |
| `.github/workflows/` | Publish `web/` to GitHub Pages; ping Supabase every 3 days so the free project doesn't pause |
| `buckbook/server.py`, `buckbook/static/`, `apps/`, `build_buck_deck.py`, `buckbook/import_artifact.py` | Earlier versions (local FastAPI server, first prototype). Not used by the live app. |

Git-ignored on purpose: `.env` (secrets), `data/` (photos, records with GPS and SIM numbers, databases, backups), and `FINDINGS.md` (private project notes with locations).

## Setup (Mac)

1. **Python env** (Python 3.11, via [uv](https://github.com/astral-sh/uv)):
   ```bash
   uv venv .venv --python 3.11
   ```
   ```bash
   uv pip install --python .venv/bin/python speciesnet mgrs fastapi uvicorn
   ```
2. **Ollama** with a vision model. The pipeline uses `qwen3.8:27b-mlx` (set in `tag_deer.py`). Ollama must be running while `tag_deer.py` runs, and nothing else needs it.
3. **`.env`** in the repo root:
   ```
   EMAIL = <Reveal login email>
   PASSWORD = <Reveal login password>
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
   SUPABASE_SECRET_KEY=sb_secret_...
   ```
   The secret key bypasses all database rules. It stays in `.env` and is only used by the Mac scripts.
4. **Supabase**: run `supabase/schema.sql`, then `002`–`008` in order in the SQL Editor. In Authentication settings, turn **off** "Allow new users to sign up" and "Allow anonymous sign-ins". Crew accounts are created with `crew_admin.py`.
5. **GitHub Pages**: Settings → Pages → Source: GitHub Actions. Pushing `web/` publishes the app.

## Everyday commands

Run from the repo root.

Pull this season's photos from every camera (records and images; re-runs only fetch what's new):
```bash
python3 reveal_pull.py all all --since=2026-08-01
```

Find deer with SpeciesNet, one camera folder at a time (fast, minutes):
```bash
.venv/bin/python -m speciesnet.scripts.run_model --folders data/photos/cam2/images --predictions_json data/tags/cam2_speciesnet.json --country USA --admin1_region WI
```

Buck/doe tagging with Qwen (slow, ~4 s per deer, heavy on battery; resumes where it stopped):
```bash
.venv/bin/python tag_deer.py data/tags/cam2_speciesnet.json data/tags/cam2_deer.jsonl
```

Import a camera's bucks into the staging deck (folder, camera name, property):
```bash
.venv/bin/python -m buckbook.import_deck cam2 "#2" "Stoddard"
```

Upload new cards. It always shows the size against the free 1 GB and asks first; `--skip` holds cameras back:
```bash
.venv/bin/python -m buckbook.supabase_sync push --skip="North Valley 300,Poll plot"
```

Back up crew, bucks, votes and consensus to `data/backups/`:
```bash
.venv/bin/python -m buckbook.supabase_sync backup
```

Crew accounts (prints a password to hand over privately):
```bash
.venv/bin/python -m buckbook.crew_admin add "Their Name"
```
```bash
.venv/bin/python -m buckbook.crew_admin list
```
`reset "Name"` issues a new password; `remove "Name"` deletes the account (their votes stay).

Member types: `user` is the default (vote, comment, name bucks, propose merges). `viewer` is read-only. `admin` can also merge bucks straight away; everyone else proposes a merge, and it goes through once the members who named both bucks agree.
```bash
.venv/bin/python -m buckbook.crew_admin type "Their Name" viewer
```
To add a read-only member, run `add "Their Name"` first, then `type "Their Name" viewer`.

### Camera folders and properties

| Camera (Reveal name) | Folder | Property |
|---|---|---|
| #1 | `cam1` | Stoddard |
| #2 | `cam2` | Stoddard |
| #8 | `cam8` | Stoddard |
| East valley food plot | `east-valley-food-plot` | Stoddard |
| North Valley 300 | `north-valley-300` | Stoddard |
| Poll plot | `poll-plot` | Stoddard |
| South pine opening water whole | `south-pine-opening-water-whole` | Stoddard |
| #3 – #6 (northridge) | `cam3` – `cam6` | North Ridge |

`barn food plot` and `East Valley Plot` are ignored (no photos this season). #2 and #8 share bursts (`SHARED_BURSTS` in `import_deck.py`).

## The data model

- **cards**: one per buck detection: camera, property, time, weather from Reveal, burst, and paths to the close-up (WebP) and full frame in the private `photos` bucket.
- **votes**: one per crew member per photo: buck or not, which buck (or "can't ID"), points, and 1–5 confidence. Nobody overwrites anyone else; the database stamps who voted.
- **bucks**: name, property, cover photo, age class, status (active / harvested / missing), notes.
- **crew**: who may sign in. **comments**: a thread per photo for talking disputes out.
- **card_consensus** (view): per photo. Buck-or-not by head count; which buck weighted by confidence. Status is `single`, `agreed`, `leaning` (a clear two-thirds winner) or `disputed`.
- **rater_pairs** / **rater_scores** (views): how often each member agrees with the others on shared photos.

Rules the database enforces: only crew can read or write anything; viewers can't change anything; merging two bucks needs both namers to agree, or an admin; votes, bucks and comments are stamped with the signed-in member; a vote can't name a buck from the other property; merges stay within one property.

## The app

- **Property switch** at the top: every screen works inside the chosen property.
- **Sort**: swipe right (buck) or left (not). Then "Seen him before?": pick from the book, **Compare** (his photos full screen with yours as an inset; swipe through him, tap the inset to swap), name a new buck, or **Can't ID him**.
- **Disputes**: called out the moment they happen, with who disagrees, a switch button, and a comment thread. The deck skips settled photos and puts disputed ones first.
- **Roster**: photo grid of bucks, a **Name them** queue for buck photos nobody has named, and an **Unidentified** pile. Buck profiles support edit, merge, delete, move a photo, and make cover.
- **Crew**: leaderboard with each member's agreement rate.

## Limits and gotchas

- **Supabase free tier**: 1 GB storage (about 90 KB per buck photo), 5 GB egress a month, and the project pauses after 7 days idle (the keep-awake workflow prevents that). No automatic backups, so run `backup`. Queries return at most 1,000 rows, so the app pages through everything.
- **Photo resolution**: Reveal's standard previews only (1280×720 on the Pro 3.0s, 640×480 on older cameras). Full-resolution originals live on the SD cards.
- **Reveal quirks**: deep pages sometimes fail (`DuplicatesFound`), some records arrive without a date, and a few downloads come back truncated. The scripts skip past all three.
- **Reveal weather** is a regional hourly report keyed by ZIP code, 1–2 hours behind the photo, and identical for both properties. Its day/night label is unreliable near dawn.
- **Ollama** occasionally stalls. `tag_deer.py` retries three times, then skips that deer.

## Ideas not built yet

A scheduled daily pull and tag; per-camera weather from Open-Meteo; sorting "Which buck?" by camera history and visual similarity; labeled reference photos per buck (left / right / front); importing full-resolution photos from SD cards.
