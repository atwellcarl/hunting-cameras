"""Sync Buck Book between this Mac and Supabase, using the secret key from .env.

Commands:
  push      Upload cards from the local deck (import_deck) that Supabase doesn't have yet:
            close-up as WebP, full frame as the original JPEG. Shows the upload size against
            the storage already used and the free-tier limit, and asks before sending.
            --yes skips the question; nothing is sent if it would pass the safety limit.
            --skip="Poll plot,North Valley 300" holds those cameras back for now.
  backup    Save Supabase crew, bucks, votes and per-photo consensus to data/backups/<timestamp>.json.
  prune     Delete the photo files of passed photos (009_pass_and_drop.sql): two passes, or one pass
            14+ days old, and no keeper vote. Shows what goes and the space it frees, backs up, and
            asks first (--yes skips the question). The card row stays, marked dropped.

Usage: .venv/bin/python -m buckbook.supabase_sync push
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
FREE_STORAGE = 1024 ** 3          # Supabase free tier: 1 GB of file storage
SAFETY_LIMIT = 0.9 * FREE_STORAGE # refuse uploads that would pass 90% of it


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


def bucket_usage():
    """Total bytes and object count currently in the photos bucket."""
    total = count = 0
    for prefix in ("crop", "frame"):
        offset = 0
        while True:
            status, items = call("POST", f"/storage/v1/object/list/{BUCKET}",
                                 {"prefix": prefix, "limit": 1000, "offset": offset})
            if status >= 300:
                raise SystemExit(f"Listing storage failed (HTTP {status}): {items}")
            for it in items:
                total += (it.get("metadata") or {}).get("size", 0)
                count += 1
            if len(items) < 1000:
                break
            offset += 1000
    return total, count


def mb(n):
    return f"{n / 1024 ** 2:,.1f} MB"


def push(assume_yes=False, skip=(), only=None):
    conn = connect()
    remote = {r["id"] for r in rest("GET", "cards", query="?select=id")}
    rows = [r for r in conn.execute("SELECT * FROM cards ORDER BY camera, taken_at")
            if r["id"] not in remote and r["camera"] not in skip and (only is None or r["id"] in only)]
    held = [] if only is not None else conn.execute(f"SELECT camera, COUNT(*) FROM cards WHERE camera IN ({','.join('?' * len(skip))}) GROUP BY camera",
                        tuple(skip)).fetchall() if skip else []
    for cam, n in held:
        print(f"Holding back {cam}: {n} cards")
    if not rows:
        print("Supabase already has every local card.")
        return

    # Build every upload first so the size check measures exactly what will be sent.
    status, existing = call("POST", f"/storage/v1/object/list/{BUCKET}", {"prefix": "frame", "limit": 10000})
    remote_frames = {f"frame/{it['name']}" for it in existing} if status < 300 else set()
    crops, frames = {}, {}
    for r in rows:
        buf = io.BytesIO()
        Image.open(IMG_DIR / "crop" / f"{r['id']}.jpg").save(buf, "WEBP", quality=80)
        crops[r["id"]] = buf.getvalue()
        frame_path = f"frame/{r['photo_id']}"
        if frame_path not in remote_frames and frame_path not in frames:
            frames[frame_path] = (IMG_DIR / "frame" / r["photo_id"]).read_bytes()
    new_bytes = sum(map(len, crops.values())) + sum(map(len, frames.values()))
    used, objects = bucket_usage()
    after = used + new_bytes

    print(f"Upload: {len(rows)} cards, {len(crops)} close-ups + {len(frames)} full frames = {mb(new_bytes)}")
    print(f"Bucket: {mb(used)} in {objects} files now -> {mb(after)} after "
          f"({after / FREE_STORAGE:.0%} of the free 1 GB)")
    if after > SAFETY_LIMIT:
        raise SystemExit(f"Not uploading: that would pass {SAFETY_LIMIT / FREE_STORAGE:.0%} of the free tier. "
                         "Push fewer cameras, drop full frames for older photos, or move photos to bigger storage.")
    if not assume_yes and input("Upload? [y/N] ").strip().lower() != "y":
        print("Nothing uploaded.")
        return

    for i, r in enumerate(rows, 1):
        crop_path = f"crop/{r['id']}.webp"
        upload(crop_path, crops[r["id"]], "image/webp")
        frame_path = f"frame/{r['photo_id']}"
        if frame_path in frames:
            upload(frame_path, frames.pop(frame_path), "image/jpeg")
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


def prune(assume_yes=False):
    ready = {r["card_id"] for r in rest("GET", "card_drop", query="?droppable=is.true&select=card_id")}
    cards = rest("GET", "cards", query="?select=id,camera,property,crop_path,frame_path,dropped_at")
    todo = [c for c in cards if c["id"] in ready and not c["dropped_at"]]
    if not todo:
        print("Nothing to drop.")
        return
    # A full frame can hold several deer; keep it while any card that isn't being dropped uses it.
    in_use = {c["frame_path"] for c in cards if c["id"] not in ready and not c["dropped_at"] and c["frame_path"]}
    crops = [c["crop_path"] for c in todo if c["crop_path"]]
    frames = sorted({c["frame_path"] for c in todo if c["frame_path"] and c["frame_path"] not in in_use})

    sizes = {}
    for prefix in ("crop", "frame"):
        offset = 0
        while True:
            status, items = call("POST", f"/storage/v1/object/list/{BUCKET}", {"prefix": prefix, "limit": 1000, "offset": offset})
            if status >= 300:
                raise SystemExit(f"Listing storage failed (HTTP {status}): {items}")
            sizes.update({f"{prefix}/{it['name']}": (it.get("metadata") or {}).get("size", 0) for it in items})
            if len(items) < 1000:
                break
            offset += 1000
    freed = sum(sizes.get(p, 0) for p in crops + frames)
    by_cam = {}
    for c in todo:
        by_cam[(c["property"], c["camera"])] = by_cam.get((c["property"], c["camera"]), 0) + 1
    print(f"Drop {len(todo)} passed photos: {len(crops)} close-ups + {len(frames)} full frames = {mb(freed)} freed")
    for (prop, cam), n in sorted(by_cam.items()):
        print(f"  {prop} · {cam}: {n}")
    if not assume_yes and input("Delete these photo files? [y/N] ").strip().lower() != "y":
        print("Nothing deleted.")
        return

    backup()
    paths = crops + frames
    for i in range(0, len(paths), 100):
        status, out = call("DELETE", f"/storage/v1/object/{BUCKET}", {"prefixes": paths[i:i + 100]})
        if status >= 300:
            raise SystemExit(f"Deleting files failed (HTTP {status}): {out}")
    now = datetime.utcnow().isoformat() + "Z"
    gone_frames = set(frames)
    for c in todo:
        patch = {"dropped_at": now, "crop_path": None}
        if c["frame_path"] in gone_frames:
            patch["frame_path"] = None
        rest("PATCH", "cards", patch, query=f"?id=eq.{urllib.parse.quote(c['id'])}")
    print(f"Dropped {len(todo)} photos, freed {mb(freed)}.")


def backup():
    out = {t: rest("GET", t, query="?select=*") for t in ("crew", "bucks", "votes", "card_consensus", "rater_scores")}
    folder = DATA_DIR.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"buckbook-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"Saved {len(out['votes'])} votes, {len(out['bucks'])} bucks, {len(out['crew'])} crew "
          f"to {path.relative_to(ROOT)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "push":
        skip = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--skip=")), "")
        push(assume_yes="--yes" in sys.argv, skip={c.strip() for c in skip.split(",") if c.strip()})
    elif cmd == "backup":
        backup()
    elif cmd == "prune":
        prune(assume_yes="--yes" in sys.argv)
    else:
        raise SystemExit(__doc__)
