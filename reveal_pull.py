"""Pull photo records (and optionally standard-res images) from Reveal.

Read-only: one login, one camera list call, then pages of 100 photo records per
camera with a pause between calls. Image downloads go to the signed S3 URLs in
each record, not the Reveal API. Records merge into any already saved, and
already-downloaded images are skipped, so re-runs only fetch what's new.

Usage:
  python3 reveal_pull.py "#8" 100             # latest 100 photos + images for one camera
  python3 reveal_pull.py all all --no-images  # every record from every camera, no images
  python3 reveal_pull.py all all --since=2026-08-01   # this season, records + images
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request

from reveal_poc import ROOT, api_get, load_env, login

PAGE_SIZE = 100


def folder_for(camera_name):
    """'#8' -> 'cam8', 'East Valley Plot' -> 'east-valley-plot'."""
    name = camera_name.replace("#", "cam")
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def pull_camera(token, cam, count, with_images, since=None):
    out_dir = ROOT / "data" / "photos" / folder_for(cam["name"])
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    records_path = out_dir / "records.json"
    saved = {r["photoId"]: r for r in json.loads(records_path.read_text())} if records_path.exists() else {}

    fetched, page = [], 0
    while count is None or len(fetched) < count:
        size = PAGE_SIZE if count is None else min(PAGE_SIZE, count - len(fetched))
        try:
            photos = api_get(token, "photos", {
                "size": size, "page": page, "cameraId": cam["cameraId"], "includeWeatherData": "true",
            }).get("photos", [])
        except SystemExit as err:
            # Reveal sometimes rejects deep pages ("DuplicatesFound"); keep what we have.
            print(f"  {cam['name']}: stopped at page {page}: {err}", flush=True)
            break
        if not photos:
            break
        # A few records arrive without a date (still syncing from the camera); skip them.
        photos = [p for p in photos if p.get("photoDateUtc")] or photos[:0]
        if not photos:
            page += 1
            continue
        older = since and photos[-1]["photoDateUtc"][:10] < since
        if since:
            photos = [p for p in photos if p["photoDateUtc"][:10] >= since]
        fetched.extend(photos)
        if older:
            break
        # Pages are newest-first; once a whole page is already saved, the rest is too.
        # Image runs keep paging: saved photo links expire, so downloads need fresh ones.
        if count is None and not with_images and all(p["photoId"] in saved for p in photos):
            break
        page += 1

    new = sum(p["photoId"] not in saved for p in fetched)
    saved.update({p["photoId"]: p for p in fetched})
    records = sorted(saved.values(), key=lambda r: r["photoDateUtc"])
    records_path.write_text(json.dumps(records, indent=2))

    downloaded = 0
    if with_images:
        for rec in fetched:
            path = img_dir / rec["photoId"]
            if path.exists() or not rec.get("photoUrl"):
                continue
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(rec["photoUrl"], timeout=60) as resp:
                        path.write_bytes(resp.read())
                    break
                except (urllib.error.URLError, TimeoutError, OSError) as err:
                    if attempt == 2:
                        print(f"  skipped {rec['photoId']}: {err}", flush=True)
                    time.sleep(5 * (attempt + 1))
            else:
                continue
            downloaded += 1
            time.sleep(0.2)

    span = f"{records[0]['photoDateUtc'][:10]} to {records[-1]['photoDateUtc'][:10]}" if records else "none"
    print(f"{cam['name']:32} {len(records):6} records ({new} new) {span}"
          + (f", {downloaded} images downloaded" if with_images else ""), flush=True)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    camera_name, count = args[0], (None if args[1] == "all" else int(args[1]))
    with_images = "--no-images" not in sys.argv
    since = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--since=")), None)

    env = load_env(ROOT / ".env")
    token = login(env["EMAIL"], env["PASSWORD"])
    cameras = api_get(token, "cameras").get("cameras", [])
    targets = cameras if camera_name == "all" else [c for c in cameras if c.get("name") == camera_name]
    if not targets:
        raise SystemExit(f"No camera named {camera_name!r}. Have: {[c.get('name') for c in cameras]}")

    for cam in targets:
        pull_camera(token, cam, count, with_images, since)


if __name__ == "__main__":
    main()
