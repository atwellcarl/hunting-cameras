# Feature ideas

Features we might add to Buck Book. Nothing here is built yet. Each entry has what it is, why we want it, and how it would work.

---

## SD-card importer (full-resolution photos)

**What:** Import the original photos straight from a camera's SD card and use them in place of Reveal's small previews.

**Why:**
- Reveal only sends standard previews: 1280×720 on the Pro 3.0s and 640×480 on older cameras. The full-resolution originals are only on the SD card.
- Counting points and telling bucks apart is much easier on a sharp close-up.
- The cellular plan is the main cost. Terrain blocks most camera-to-camera radio links at both properties, so a mesh (CuddeLink / BuckEye style) won't fix that. The plan is a hybrid: keep cellular on the few cameras we need to see live, and run the rest SD-only, checked on normal trips. This importer is what makes the SD-only cameras useful.

**How it would work:**
1. Copy the card to the Mac and run it against one camera:
   ```bash
   .venv/bin/python -m buckbook.import_sd /Volumes/<card> "#2" "Stoddard"
   ```
2. Read each photo's EXIF time and **match it to its Reveal record** (same camera, time within a few seconds; photos taken in the same second are ordered by file number).
   - **Matched:** the original replaces the preview. The detection box carries over, and the close-up is re-cut from the full-resolution image.
   - **No Reveal record** (SD-only cameras, or photos that were never sent): becomes a new record. It goes through SpeciesNet and Qwen like a pulled photo, with its time and camera taken from the file.
3. Keep the full-resolution originals on the Mac under `data/sd/<camera>/`, git-ignored like the rest of `data/`.
4. **Upload a sharper version, not the raw file.** Originals are several MB each and would fill the 1 GB free tier quickly. Upload a higher-quality WebP close-up, plus a frame scaled to phone-screen size. `push` keeps its size check and asks before uploading.
5. Cards that get an upgrade are marked in the app, for example with an "SD" tag and a "View original" option when zoomed in.

**To check first:**
- Which EXIF fields the Tactacam cameras write (time, camera ID). Does the camera clock match the time Reveal reports, or is it offset or off by a time zone?
- Whether the originals have the same aspect ratio as the previews, so the saved detection boxes line up.
- The card's folder and file naming.
- Weather for SD-only photos: Reveal's weather won't exist for them. This could pair with the per-camera Open-Meteo idea below.
- Whether any existing votes, crops, or covers would be lost when a card's image is swapped. The goal is that nothing changes except sharpness.

---

## Download budget (for discussion)

**The concern:** Supabase's free tier allows **5 GB of downloads a month** ("egress"). Once we're past it, Supabase warns and can restrict the project, so the 5 GB is a real limit. It will probably run out before the 1 GB of storage does, because the buck page gallery (added 2026-09-26) loads full frames. A full frame averages about 125 KB, and a close-up about 32 KB.

**Measured 2026-09-27** (Stoddard, 202 photos, 8 bucks, 129 votes). Sizes are file sizes and uncompressed database replies; it isn't confirmed whether Supabase counts the compressed size, which would be smaller:

| Action | Downloads |
|---|---|
| Open the app (Roster close-ups ~0.5 MB, photo list and votes ~0.2 MB, photo links) | ~0.8 MB |
| Open a buck and scroll his whole gallery | 0.1–3.6 MB (Too Tall, 25 photos, is the biggest; average ~1.4 MB) |
| One full frame in the viewer | 0.12–0.18 MB |
| Sort one photo | ~0.03 MB for the close-up, plus ~0.06 MB for **every open copy of the app** (see below) |

Every app open starts from zero, because photo links change on each load.

**Traffic it takes to reach 5 GB a month (~170 MB a day):**
- A normal browsing visit (open, look through 3 bucks, zoom into 10 photos) is about 6 MB. **5 GB is about 28 of those a day, every day**, for example 10 people each checking three times a day. Three or four of us checking a few times a day comes to roughly 1–2 GB a month.
- A "scroll every buck" visit is about 15 MB, so about 11 a day.
- Both numbers **get worse as the season fills in.** Galleries grow as bucks collect photos, and pushing the 484 held-back photos adds more. Tripling the photos roughly triples the browsing cost.

**The bigger hidden cost, found while measuring:** whenever anyone votes, every open copy of the app downloads the whole vote and consensus tables again (~60 KB now). A sorting session of 50 swipes costs ~1.7 MB in photos but ~3 MB in these reloads, times the number of people who have the app open. The reload grows with the total number of votes, so by a few thousand votes it would be the largest cost. The fix is to download only the rows that changed, since the live-update message already says which row it was.

**Ways to cut it, cheapest first:**
1. ~~**Reload only what changed**~~ **Done 2026-09-27.** A vote or comment now applies just its own row and fetches consensus for that photo only (~0.2 KB instead of ~60 KB for every open copy of the app). A full reload happens only on opening the app, after more than a minute away, or when bucks, crew or merge proposals change.
2. **Check the real number.** Supabase's Usage page shows egress per day. Look at it after a week of real use before changing anything.
3. **Small thumbnails for the gallery grid.** Make a ~20 KB preview per photo at upload and load the full frame only when someone opens a photo. This is the biggest saving, roughly 5× on the gallery.
4. **Full frames as WebP.** About half the size, for both storage and downloads. Same change to the upload script as the storage fix.
5. **Let the browser reuse photos.** Keep each photo's signed link for its whole lifetime (save it on the phone) instead of making new links on every load, so repeat visits come from the phone's cache.
6. **If we still outgrow it:** Cloudflare R2 has no download charges at all, or Supabase Pro raises the limit to 250 GB.

---

## Share a photo

**What:** A **Share** button in the photo viewer that sends the picture out of Buck Book (text, group chat, email) to people who aren't in the crew.

**Why:** "Look at this one" is half the fun, and right now it means a screenshot.

**How it would work:**
- Use the phone's own share sheet (the Web Share API). The app downloads the photo it's showing and hands the phone the image *file*, not a link. Buck Book's photo links are private and expire after a few hours, and the people you're sending to can't sign in.
- Share whichever version is on screen, close-up or full frame, with a short caption such as "Too Tall · CAM #2 · Sep 20".
- **Strip the photo's hidden details before sharing.** Re-save the image in the browser so camera metadata, possibly including GPS, doesn't go out with it. The Reveal date stamp on the frame stays.
- On a computer without a share sheet, fall back to "Save image".
- Viewers can share too, since it doesn't change the book.

**To check:** how the share sheet behaves on iPhone Safari (it needs the file ready before the tap finishes). The full frames sampled on 2026-09-26 carried no metadata (no GPS), but re-saving before sharing is still the safe default.

---

## Compare two bucks

**What:** From a buck's page, **Compare with…** another buck: both bucks' photos on screen together, each one swipeable on its own.

**Why:** Deciding whether two names are the same deer, or checking a buck against last season, means flipping between two galleries. Comparing them together is how the crew will settle merges.

**How it would work:**
- On a phone, split the screen top and bottom, one buck in each half. Each half swipes through his photos and zooms on its own. On a wider screen, put them side by side.
- Start each half on the buck's cover photo. The Close-up / Full frame switch applies to both.
- Also reachable from a **Compare** button on the "Name merges" cards, so the people deciding can look before they agree.
- This builds on the existing Compare view (which today puts one unsorted photo against one buck).

---

## Built

- **Tactacam Hit List import** (`buckbook/hitlist.py`, 2026-09-26): reads Hit List bucks read-only and imports them as bucks, with the photos credited as votes from the member who keeps the list. Photos with more than one buck in them are left for the crew. Re-running adds only new photos.
- **Merge by agreement** (`008_member_types.sql`, 2026-09-26): name-merge suggestions from shared photos. Anyone proposes; it merges once both bucks' namers agree, and either namer can say "not the same buck". Admins merge straight away. Member types: admin / user / viewer.
- **Map** (`013_map.sql`, `buckbook/map_data.py`, `web/map.js`, 2026-10-21): a mini onX for the two properties.
  - **Layers:** Wisconsin DNR leaf-off photos (3-inch, from the regional orthophoto program; sharpest, and slow to load), USGS summer photos, USGS topo, USGS 3DEP lidar terrain shading, and 10 ft contours over any of them.
  - **On the map:** cameras where they stand now, from the GPS on their photos, with where they stood before (cameras with no GPS are placed by hand). Spots anyone adds (stand, saddle tree, scrape, rub, bedding, crossing, food, water, parking). The trees we've sat, from sit GPS. Wisconsin statewide parcel lines, with our parcels bold; tap a parcel for owner and acres.
  - **Offline:** "Download Map" saves a property's map on the phone (about 14 MB, 10 to 20 minutes on Wi-Fi, because the leaf-off server is slow). With the GPS dot, distance and direction to anything, and spots added with no signal, it works in the woods.
  - **Wind lens:** pick a wind, or a forecast morning or evening, and the trees sat in that wind light up. Each shows its scent cone and the paths of the deer seen there (red if they busted or winded us), and the trees are ranked by sits, deer and busts. Buck photos per camera in that wind show once photos are loaded. Plain counts, not odds, until there's a season or two of sits.
  - **Still to do:** thermals from the elevation data (morning air sinks, evening air rises); a compass heading for the blue dot; leaf-off photos older than the latest flight.

---

## Backlog (from earlier sessions)

- **Scheduled pull and tag:** a daily job that pulls new Reveal photos, runs SpeciesNet, and leaves Qwen for daytime runs.
- **Per-camera weather from Open-Meteo:** real hourly wind, temperature, and pressure at each camera's location, replacing Reveal's ZIP-code report.
- **Smarter "Which buck?" list:** put bucks recently seen at this camera first, then sort by visual similarity.
- **Reference photos per buck:** labeled left, right, and front views, to make comparing easier.
- **Held-back cameras:** push #2, North Valley 300, and Poll plot once the crew is ready for more photos. That is about 484 cards and 69 MB.
