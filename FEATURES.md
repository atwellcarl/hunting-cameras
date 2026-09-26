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

## Import Tactacam Hit Lists

**What:** Bring the bucks the crew names in the Tactacam app's Hit List into Buck Book as named bucks, with their photos.

**Why:** People already sort bucks in the Tactacam app. The Hit List's buck compare is behind a paywall, but the list itself is readable, so that work shouldn't have to be done twice.

**What we know (checked 2026-09-26, read-only):**
- Each Hit List buck is a Reveal gallery of type `target`: `GET /v1/photoGroups?galleryType=target`. It has a name, a status (`active` / `harvested` / `m.i.a.`), a cover photo, and a photo count.
- Its photos come from `GET /v1/photos/v2?photoGroupId=<id>` (paged with `paginationKey`). Every photo carries its `photoId`, and Buck Book cards already store that ID, so matching is exact.
- The older "Buck / Doe / Turkey…" species tags (`/v1/photo-tags`) and the standard galleries are separate from the Hit List.
- The Hit List doesn't record who added a photo, because everyone shares one Reveal login.

**How it would work:**
- Create a matching Buck Book buck for each Hit List buck, on the property its photos come from. Status maps across (`m.i.a.` → missing).
- Record each photo as a vote from a **"Hit List" crew member**. It counts as one voice, so if the list disagrees with someone's call in Buck Book, that shows up as a normal dispute.
- A photo with two bucks in it (two cards) can't be matched to one of them automatically. Those go to the crew to decide.
- Hit List photos Buck Book doesn't have yet (newer than the last pull, or missed by the AI) come in through the normal pull, SpeciesNet, and import steps.
- Re-running only adds new photos. It never touches anyone's votes.

**Open:** 47 of the 56 matched photos are on the held-back cameras (#2, North Valley 300, Poll plot). Importing the Hit List means pushing at least those cards.

---

## Merge by agreement (naming consensus)

**What:** When two bucks are probably the same deer under different names (for example, a Hit List name and a Buck Book name), anyone can *propose* a merge and a keeper name. The crew votes on it like a dispute, and it merges once there's agreement.

**Why:** Today, Merge on a buck's profile is immediate and one person decides. Hit List imports will create same-buck, different-name pairs regularly, and the name everyone ends up using should be a group decision.

**How it would work:** a `merge_proposals` table (from, into, proposed name, proposer), with agree/disagree votes and comments. It shows up in Disputes with both bucks side by side, using the Compare view. The existing `merge_bucks` runs when a majority of the members who voted on either buck agree.

---

## Backlog (from earlier sessions)

- **Scheduled pull and tag:** a daily job that pulls new Reveal photos, runs SpeciesNet, and leaves Qwen for daytime runs.
- **Per-camera weather from Open-Meteo:** real hourly wind, temperature, and pressure at each camera's location, replacing Reveal's ZIP-code report.
- **Smarter "Which buck?" list:** put bucks recently seen at this camera first, then sort by visual similarity.
- **Reference photos per buck:** labeled left, right, and front views, to make comparing easier.
- **Held-back cameras:** push #2, North Valley 300, and Poll plot once the crew is ready for more photos. That is about 484 cards and 69 MB.
