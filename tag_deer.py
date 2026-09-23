"""Stage 3 tagging: buck/doe/fawn + antler detail via a local Ollama vision model.

Reads SpeciesNet predictions, crops each deer detection (padded, upscaled),
and asks the model for structured JSON. Results go to a JSONL file so runs
can resume.

Usage: .venv/bin/python tag_deer.py data/tags/cam8_speciesnet.json data/tags/cam8_deer.jsonl [limit]
"""
import base64
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.8:27b-mlx"
MIN_DET_CONF = 0.5
MIN_CROP_PX = 40  # skip detections smaller than this on their short side
PAD = 0.15
TARGET_SHORT_SIDE = 512

PROMPT = """This is a cropped trail camera image of a white-tailed deer in Wisconsin \
(may be night infrared, black and white). Classify the deer.

- class: "buck" only if antlers are visible. "fawn" if small with spots or clearly a juvenile. \
"doe" if an adult with no antlers visible and the head is visible. "unknown" if the head \
is not visible or the image is too unclear to tell.
- antler_points_estimate: total visible tines on both sides combined, or null if not a buck \
or not countable.
- velvet: true/false/null.
- maturity: for bucks only, "young" (1.5 yr), "mid" (2.5-3.5 yr), "mature" (4.5+ yr), or null. \
Judge by body: neck thickness, chest depth, belly sag, and antler mass.
- confidence: 0 to 1.
- notes: one short sentence describing distinguishing features (antler shape, body, marks)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "class": {"type": "string", "enum": ["buck", "doe", "fawn", "unknown"]},
        "antler_points_estimate": {"type": ["integer", "null"]},
        "velvet": {"type": ["boolean", "null"]},
        "maturity": {"type": ["string", "null"], "enum": ["young", "mid", "mature", None]},
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": ["class", "antler_points_estimate", "velvet", "maturity", "confidence", "notes"],
}


def crop(image, bbox):
    w, h = image.size
    x, y, bw, bh = bbox
    px, py = bw * PAD, bh * PAD
    box = (
        max(0, (x - px) * w), max(0, (y - py) * h),
        min(w, (x + bw + px) * w), min(h, (y + bh + py) * h),
    )
    c = image.crop(tuple(int(v) for v in box))
    scale = TARGET_SHORT_SIDE / min(c.size)
    if scale > 1:
        c = c.resize((int(c.width * scale), int(c.height * scale)), Image.LANCZOS)
    return c, box


def ask(img):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    body = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0},
        "messages": [{
            "role": "user", "content": PROMPT,
            "images": [base64.b64encode(buf.getvalue()).decode()],
        }],
    }
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(json.loads(resp.read())["message"]["content"])


def main():
    preds_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None

    done = set()
    if out_path.exists():
        done = {(r["file"], r["det_index"]) for r in map(json.loads, out_path.open())}

    preds = json.loads(preds_path.read_text())["predictions"]
    # Genus match: includes "white-tailed deer" and SpeciesNet's less certain "odocoileus species".
    deer = [p for p in preds if "odocoileus" in p.get("prediction", "")]

    n = 0
    with out_path.open("a") as out:
        for p in deer:
            image = Image.open(p["filepath"]).convert("RGB")
            for i, det in enumerate(p.get("detections", [])):
                if det["label"] != "animal" or det["conf"] < MIN_DET_CONF:
                    continue
                key = (Path(p["filepath"]).name, i)
                if key in done:
                    continue
                img, box = crop(image, det["bbox"])
                if min(box[2] - box[0], box[3] - box[1]) < MIN_CROP_PX:
                    continue
                t0 = time.time()
                result = ask(img)
                rec = {"file": key[0], "det_index": i, "det_conf": det["conf"],
                       "bbox": det["bbox"], "seconds": round(time.time() - t0, 1), **result}
                out.write(json.dumps(rec) + "\n")
                out.flush()
                print(f"{key[0][20:34]} #{i}: {result['class']:7} pts={result['antler_points_estimate']} "
                      f"mat={result['maturity']} conf={result['confidence']} ({rec['seconds']}s)")
                n += 1
                if limit and n >= limit:
                    return


if __name__ == "__main__":
    main()
