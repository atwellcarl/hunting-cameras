"""Sync Buck Book between this Mac and Supabase, using the secret key from .env.

Commands:
  push      Upload cards from the local deck (import_deck) that Supabase doesn't have yet:
            close-up as WebP, full frame as the original JPEG.
  migrate   Copy local labels and bucks (the pilot sort) to Supabase, credited to a name.
  backup    Save Supabase crew, bucks and labels to data/backups/<timestamp>.json.

Usage: .venv/bin/python -m buckbook.supabase_sync push
       .venv/bin/python -m buckbook.supabase_sync migrate "Your Name"
"""
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from PIL import Image

from buckbook.db import DATA_DIR, IMG_DIR, ROOT, connect
from reveal_poc import load_env

ENV = load_env(ROOT / ".env")
URL = ENV["SUPABASE_URL"].rstrip("/")
KEY = ENV["SUPABASE_SECRET_KEY"]
BUCKET = "photos"


def call(method, path, body=None, headers=None, raw=None):
    """Request against Supabase with the secret key on the apikey header (not Bearer)."""
    hdrs = {"apikey": KEY, **(headers or {})}
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(URL + path, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode()
            return resp.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()[:500]


def rest(method, table, body=None, query="", prefer=None):
    status, out = call(method, f"/rest/v1/{table}{query}", body,
                       {"Prefer": prefer} if prefer else None)
    if status >= 300:
        raise SystemExit(f"{method} {table} failed (HTTP {status}): {out}")
    return out


def upload(object_path, data, content_type):
    status, out = call("POST", f"/storage/v1/object/{BUCKET}/{urllib.parse.quote(object_path)}",
                       headers={"Content-Type": content_type, "x-upsert": "true"}, raw=data)
    if status >= 300:
        raise SystemExit(f"Upload {object_path} failed (HTTP {status}): {out}")


def push():
    conn = connect()
    remote = {r["id"] for r in rest("GET", "cards", query="?select=id")}
    rows = [r for r in conn.execute("SELECT * FROM cards ORDER BY camera, taken_at") if r["id"] not in remote]
    if not rows:
        print("Supabase already has every local card.")
        return

    for i, r in enumerate(rows, 1):
        buf = io.BytesIO()
        Image.open(IMG_DIR / "crop" / f"{r['id']}.jpg").save(buf, "WEBP", quality=80)
        crop_path = f"crop/{r['id']}.webp"
        upload(crop_path, buf.getvalue(), "image/webp")
        frame_path = f"frame/{r['photo_id']}"
        upload(frame_path, (IMG_DIR / "frame" / r["photo_id"]).read_bytes(), "image/jpeg")
        rest("POST", "cards", {
            "id": r["id"], "camera": r["camera"], "property": r["property"], "taken_at": r["taken_at"],
            "daylight": bool(r["daylight"]), "temp_f": r["temp_f"], "wind": r["wind"], "moon": r["moon"],
            "pressure": r["pressure"], "burst": r["burst"], "crop_path": crop_path, "frame_path": frame_path,
        }, prefer="resolution=merge-duplicates")
        print(f"  {i}/{len(rows)} {r['id']}", flush=True)
        time.sleep(0.05)

    # Bursts are recomputed locally on every import; keep Supabase in step for all cards.
    for r in conn.execute("SELECT id, burst FROM cards"):
        rest("PATCH", "cards", {"burst": r["burst"]}, query=f"?id=eq.{urllib.parse.quote(r['id'])}")
    print(f"Uploaded {len(rows)} cards.")


def migrate(name):
    conn = connect()
    bucks = [dict(r) for r in conn.execute("SELECT * FROM bucks")]
    labels = [dict(r) for r in conn.execute("SELECT * FROM labels")]
    if bucks:
        rest("POST", "bucks", [
            {"id": b["id"], "name": b["name"], "cover": b["cover"], "by_name": name, "at": b["at"]}
            for b in bucks
        ], prefer="resolution=merge-duplicates")
    if labels:
        rest("POST", "labels", [
            {"card_id": l["card_id"], "verdict": l["verdict"], "buck_id": l["buck_id"], "points": l["points"],
             "confidence": l["confidence"], "by_name": name, "at": l["at"]}
            for l in labels
        ], prefer="resolution=merge-duplicates")
    print(f"Copied {len(bucks)} bucks and {len(labels)} labels to Supabase, credited to {name!r}.")


def backup():
    out = {t: rest("GET", t, query="?select=*") for t in ("crew", "bucks", "labels")}
    folder = DATA_DIR.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"buckbook-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"Saved {len(out['labels'])} labels, {len(out['bucks'])} bucks, {len(out['crew'])} crew "
          f"to {path.relative_to(ROOT)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "push":
        push()
    elif cmd == "migrate" and len(sys.argv) > 2:
        migrate(sys.argv[2])
    elif cmd == "backup":
        backup()
    else:
        raise SystemExit(__doc__)
