"""Load AI-tagged buck detections for one camera into Buck Book.

Writes a native-resolution crop and the original frame per detection into
data/buckbook/img/, and upserts card rows. Existing labels are untouched.
Bursts are recomputed per camera after every import.

Usage: .venv/bin/python -m buckbook.import_deck cam8 "#8" "Property A"
"""
import json
import shutil
import sys
from datetime import datetime

from PIL import Image

from buckbook.db import IMG_DIR, ROOT, bump_version, connect
from tag_deer import crop

BURST_GAP_MIN = 5


def main():
    folder, camera, prop = sys.argv[1], sys.argv[2], sys.argv[3]
    cam_dir = ROOT / "data" / "photos" / folder
    records = {r["photoId"]: r for r in json.loads((cam_dir / "records.json").read_text())}
    tags = [json.loads(l) for l in (ROOT / "data" / "tags" / f"{folder}_deer.jsonl").open()]

    (IMG_DIR / "crop").mkdir(parents=True, exist_ok=True)
    (IMG_DIR / "frame").mkdir(parents=True, exist_ok=True)
    conn = connect()

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

    # Recompute bursts for this camera: same camera, gaps of at most BURST_GAP_MIN.
    rows = conn.execute("SELECT id, taken_at FROM cards WHERE camera = ? ORDER BY taken_at", (camera,)).fetchall()
    base = conn.execute("SELECT COALESCE(MAX(burst), 0) FROM cards WHERE camera != ?", (camera,)).fetchone()[0]
    burst, prev = base, None
    for r in rows:
        t = datetime.fromisoformat(r["taken_at"])
        if prev is None or (t - prev).total_seconds() > BURST_GAP_MIN * 60:
            burst += 1
        conn.execute("UPDATE cards SET burst = ? WHERE id = ?", (burst, r["id"]))
        prev = t

    bump_version(conn)
    conn.commit()
    print(f"{camera}: {added} new cards ({len(rows)} total for this camera)")


if __name__ == "__main__":
    main()
