"""Package AI-tagged buck crops into the Buck Book page.

Reads the Qwen tags (tag_deer.py output) and Reveal photo records, builds one
card per buck detection (crop + full-frame thumbnail as data URIs, camera,
local time, weather, AI guess, burst id), and injects them into the page
template.

Usage: .venv/bin/python build_buck_deck.py
"""
import base64
import io
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from tag_deer import crop

ROOT = Path(__file__).parent
CAMERAS = {"cam8": "#8"}
BURST_GAP_MIN = 5
TEMPLATE = ROOT / "apps" / "buck-book" / "template.html"
OUT = ROOT / "apps" / "buck-book" / "index.html"


def data_uri(img, max_side, quality):
    img = img.copy()
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    cards = []
    for folder, cam_name in CAMERAS.items():
        cam_dir = ROOT / "data" / "photos" / folder
        records = {r["photoId"]: r for r in json.loads((cam_dir / "records.json").read_text())}
        tags = [json.loads(l) for l in (ROOT / "data" / "tags" / f"{folder}_deer.jsonl").open()]

        for t in tags:
            if t["class"] != "buck":
                continue
            rec = records[t["file"]]
            w = rec.get("weatherRecord") or {}
            wind = w.get("windDirection") or {}
            when = datetime.strptime(rec["photoTimestamp"], "%m%d%Y%H%M%S")
            image = Image.open(cam_dir / "images" / t["file"]).convert("RGB")
            crop_img, _ = crop(image, t["bbox"])
            cards.append({
                "id": f"{folder}-{rec['photoTimestamp']}-{t['det_index']}",
                "cam": cam_name,
                "when": when.isoformat(),
                "daylight": w.get("sunPhase") == "Daytime",
                "temp": w.get("temperature"),
                "wind": f"{wind.get('cardinalLabel', '')} {wind.get('speed', '')}".strip(),
                "moon": w.get("moonPhase"),
                "pressure": w.get("barometricPressure"),
                "ai": {
                    "points": t["antler_points_estimate"],
                    "maturity": t["maturity"],
                    "notes": t["notes"],
                },
                "crop": data_uri(crop_img, 1024, 90),
                "frame": data_uri(image, 640, 92),
            })

    cards.sort(key=lambda c: (c["cam"], c["when"]))
    burst, prev = 0, None
    for c in cards:
        t = datetime.fromisoformat(c["when"])
        if prev is None or prev[0] != c["cam"] or (t - prev[1]).total_seconds() > BURST_GAP_MIN * 60:
            burst += 1
        c["burst"] = burst
        prev = (c["cam"], t)

    html = TEMPLATE.read_text().replace("/*__CARDS__*/[]", json.dumps(cards))
    OUT.write_text(html)
    print(f"{len(cards)} cards in {burst} bursts -> {OUT.relative_to(ROOT)} "
          f"({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
