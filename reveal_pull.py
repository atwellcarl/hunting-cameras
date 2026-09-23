"""Pull the most recent N photos (records + standard-res images) for one camera.

Read-only: one login, one camera list call, ceil(N/100) photo-page calls.
Image downloads go to the signed S3 URLs in each record, not the Reveal API.
Already-downloaded images are skipped.

Usage: python3 reveal_pull.py "#8" 100
"""
import json
import sys
import time
import urllib.request

from reveal_poc import ROOT, api_get, load_env, login

PAGE_SIZE = 100


def main():
    camera_name, count = sys.argv[1], int(sys.argv[2])

    env = load_env(ROOT / ".env")
    token = login(env["EMAIL"], env["PASSWORD"])

    cameras = api_get(token, "cameras").get("cameras", [])
    cam = next((c for c in cameras if c.get("name") == camera_name), None)
    if cam is None:
        raise SystemExit(f"No camera named {camera_name!r}. "
                         f"Have: {[c.get('name') for c in cameras]}")

    records, page = [], 0
    while len(records) < count:
        photos = api_get(token, "photos", {
            "size": min(PAGE_SIZE, count - len(records)), "page": page,
            "cameraId": cam["cameraId"], "includeWeatherData": "true",
        }).get("photos", [])
        if not photos:
            break
        records.extend(photos)
        page += 1

    out_dir = ROOT / "data" / "photos" / camera_name.replace("#", "cam")
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "records.json").write_text(json.dumps(records, indent=2))

    downloaded = 0
    for rec in records:
        path = img_dir / rec["photoId"]
        if path.exists() or not rec.get("photoUrl"):
            continue
        with urllib.request.urlopen(rec["photoUrl"], timeout=60) as resp:
            path.write_bytes(resp.read())
        downloaded += 1
        time.sleep(0.2)

    dates = [r["photoDateUtc"] for r in records]
    print(f"{camera_name}: {len(records)} records "
          f"({min(dates)} to {max(dates)}), {downloaded} images downloaded "
          f"to {img_dir.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
