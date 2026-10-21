"""Load AI-tagged buck detections for one camera into Buck Book.

Writes a native-resolution crop and the original frame per detection into
data/buckbook/img/, and upserts card rows. Existing labels are untouched.
Bursts are recomputed per camera after every import.

Each photo's property comes from its own GPS: whichever property's existing photos it sits
closest to. Cameras get moved between properties, so the camera's name or Reveal's location
label can't be trusted. The property argument is only the fallback for a photo without GPS.

Usage: .venv/bin/python -m buckbook.import_deck cam8 "#8" [fallback property]
"""
import json
import shutil
import sys
from datetime import datetime

from PIL import Image

from buckbook.db import IMG_DIR, ROOT, bump_version, connect
from tag_deer import crop

BURST_GAP_MIN = 5
# Cameras that watch the same spot (#2 and #8 are ~21 m apart), so a buck passing
# trips both; their photos chain into shared bursts.
SHARED_BURSTS = [{"#2", "#8"}]


def recompute_bursts(conn):
    """Number every burst across all cameras: photos from one camera (or one shared-burst
    group) taken at most BURST_GAP_MIN apart share a burst. A shared group only chains photos
    on the same property, since cameras get moved."""
    group_of = {cam: min(g) for g in SHARED_BURSTS for cam in g}
    rows = conn.execute("SELECT id, camera, property, taken_at FROM cards").fetchall()
    by_group = {}
    for r in rows:
        by_group.setdefault((r["property"] or "", group_of.get(r["camera"], r["camera"])), []).append(r)
    burst = 0
    for group in sorted(by_group):
        prev = None
        for r in sorted(by_group[group], key=lambda r: r["taken_at"]):
            t = datetime.fromisoformat(r["taken_at"])
            if prev is None or (t - prev).total_seconds() > BURST_GAP_MIN * 60:
                burst += 1
            conn.execute("UPDATE cards SET burst = ? WHERE id = ?", (burst, r["id"]))
            prev = t


def gps_of(rec):
    g = rec.get("gpsLocation") or {}
    lat, lon = g.get("lat") or g.get("latitude"), g.get("lon") or g.get("longitude")
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def property_centres(conn):
    """Average position of each property's photos already in the deck (no coordinates kept in code)."""
    where = {}
    for records in (ROOT / "data" / "photos").glob("*/records.json"):
        for r in json.loads(records.read_text()):
            if (pos := gps_of(r)):
                where[r["photoId"]] = pos
    sums = {}
    for row in conn.execute("SELECT DISTINCT photo_id, property FROM cards WHERE property IS NOT NULL"):
        if row["photo_id"] in where:
            lat, lon = where[row["photo_id"]]
            s = sums.setdefault(row["property"], [0.0, 0.0, 0])
            s[0] += lat; s[1] += lon; s[2] += 1
    return {prop: (a / n, b / n) for prop, (a, b, n) in sums.items() if n}


def nearest_property(rec, centres, fallback):
    pos = gps_of(rec)
    if not pos or not centres:
        return fallback
    return min(centres, key=lambda p: (centres[p][0] - pos[0]) ** 2 + (centres[p][1] - pos[1]) ** 2)


def main():
    folder, camera = sys.argv[1], sys.argv[2]
    fallback = sys.argv[3] if len(sys.argv) > 3 else None
    cam_dir = ROOT / "data" / "photos" / folder
    records = {r["photoId"]: r for r in json.loads((cam_dir / "records.json").read_text())}
    tags = [json.loads(l) for l in (ROOT / "data" / "tags" / f"{folder}_deer.jsonl").open()]

    (IMG_DIR / "crop").mkdir(parents=True, exist_ok=True)
    (IMG_DIR / "frame").mkdir(parents=True, exist_ok=True)
    conn = connect()
    centres = property_centres(conn)
    by_prop = {}

    added = 0
    for t in tags:
        if t["class"] != "buck":
            continue
        rec = records[t["file"]]
        card_id = f"{folder}-{rec['photoTimestamp']}-{t['det_index']}"
        src = cam_dir / "images" / t["file"]
        crop_img, _ = crop(Image.open(src).convert("RGB"), t["bbox"])
        crop_img.save(IMG_DIR / "crop" / f"{card_id}.jpg", quality=92)
        frame_path = IMG_DIR / "frame" / f"{rec['photoId']}"
        if not frame_path.exists():
            shutil.copyfile(src, frame_path)

        w = rec.get("weatherRecord") or {}
        wind = w.get("windDirection") or {}
        taken = datetime.strptime(rec["photoTimestamp"], "%m%d%Y%H%M%S")
        prop = nearest_property(rec, centres, fallback)
        if not prop:
            print(f"  skipping {card_id}: no GPS and no fallback property given")
            continue
        by_prop[prop] = by_prop.get(prop, 0) + 1
        cur = conn.execute(
            """INSERT INTO cards (id, camera, property, taken_at, daylight, temp_f, wind, moon, pressure,
                                  photo_id, bbox, ai)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO NOTHING""",
            (card_id, camera, prop, taken.isoformat(), int(w.get("sunPhase") == "Daytime"),
             w.get("temperature"), f"{wind.get('cardinalLabel', '')} {wind.get('speed', '')}".strip(),
             w.get("moonPhase"), w.get("barometricPressure"), rec["photoId"],
             json.dumps(t["bbox"]), json.dumps({k: t[k] for k in ("class", "notes")})),
        )
        added += cur.rowcount

    recompute_bursts(conn)
    bump_version(conn)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM cards WHERE camera = ?", (camera,)).fetchone()[0]
    print(f"{camera}: {added} new cards ({total} total for this camera)"
          + (f"; by GPS: {', '.join(f'{p} {n}' for p, n in sorted(by_prop.items()))}" if by_prop else ""))


if __name__ == "__main__":
    main()
