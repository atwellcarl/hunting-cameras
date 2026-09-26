"""Bring Tactacam Hit List bucks into Buck Book.

A Hit List buck is a Reveal gallery of type "target". Its photos are matched to Buck Book
cards by Reveal photo ID. Each Hit List becomes a buck (created once, remembered in
data/hitlist/map.json), and each matched photo becomes a vote from the crew member who
keeps the Hit List. Nobody's existing vote is ever changed.

Commands:
  pull                   Read the Hit Lists and their photos from Reveal (read-only GETs).
  apply --as="Name"      Push any matched cards Supabase doesn't have yet (size check first),
                         then create bucks and add that member's votes. Shows the plan and asks.
                         --yes skips the questions.

Photos with more than one buck card can't be pinned to one deer automatically; they're
listed and left for the crew to name in the app.

Usage: .venv/bin/python -m buckbook.hitlist pull
"""
import json
import secrets
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

from buckbook.crew_admin import find_user
from buckbook.db import ROOT, connect
from buckbook.supabase_sync import backup, push, rest
from reveal_poc import api_get, load_env, login

HL_DIR = ROOT / "data" / "hitlist"
HL_FILE = HL_DIR / "hitlist.json"
MAP_FILE = HL_DIR / "map.json"
STATUS = {"active": "active", "harvested": "harvested", "m.i.a.": "missing"}


def pull():
    env = load_env(ROOT / ".env")
    token = login(env["EMAIL"], env["PASSWORD"])
    lists = api_get(token, "photoGroups", {"galleryType": "target"}).get("photoGroups", [])
    for g in lists:
        photos, key = [], None
        while True:
            params = {"size": 100, "photoGroupId": g["photoGroupId"]}
            if key:
                params["paginationKey"] = key
            page = api_get(token, "photos/v2", params)
            photos += page.get("photos", [])
            key = page.get("nextToken")
            if not key:
                break
        g["photos"] = [{k: p.get(k) for k in ("photoId", "cameraName", "photoDateUtc")} for p in photos]
        print(f"  {g['name']}: {len(photos)} photos")
    HL_DIR.mkdir(parents=True, exist_ok=True)
    HL_FILE.write_text(json.dumps(lists, indent=1))
    print(f"Saved {len(lists)} Hit List bucks to {HL_FILE.relative_to(ROOT)}")


def cover_card(cards, box):
    """Of a photo's cards, the one whose detection centre sits inside the Hit List cover crop."""
    if len(cards) == 1:
        return cards[0]["id"]
    x1, y1, x2, y2 = box or (0, 0, 1, 1)
    for c in cards:
        bx, by, bw, bh = json.loads(c["bbox"])
        if x1 <= bx + bw / 2 <= x2 and y1 <= by + bh / 2 <= y2:
            return c["id"]
    return None


def apply(member, assume_yes=False):
    if not HL_FILE.exists():
        raise SystemExit("Run `pull` first.")
    user = find_user(member)
    if not user:
        raise SystemExit(f"{member!r} has no Buck Book account yet. Run: crew_admin add \"{member}\"")
    lists = json.loads(HL_FILE.read_text())
    mapping = json.loads(MAP_FILE.read_text()) if MAP_FILE.exists() else {}

    conn = connect()
    by_photo = defaultdict(list)
    for r in conn.execute("SELECT id, photo_id, camera, property, bbox FROM cards"):
        by_photo[r["photo_id"]].append(r)

    # 1. Every card on a Hit List photo has to be in Supabase before it can be voted on.
    needed = {c["id"] for g in lists for p in g["photos"] for c in by_photo.get(p["photoId"], [])}
    remote = {r["id"] for r in rest("GET", "cards", query="?select=id")}
    if needed - remote:
        print(f"{len(needed - remote)} Hit List cards aren't in Buck Book yet.")
        push(assume_yes=assume_yes, only=needed - remote)
        remote = {r["id"] for r in rest("GET", "cards", query="?select=id")}

    # 2. Plan bucks and votes.
    bucks = {b["id"]: b for b in rest("GET", "bucks", query="?select=id,name,property")}
    mine = {v["card_id"] for v in rest("GET", "votes", query=f"?select=card_id&voter=eq.{user['id']}")}
    new_bucks, votes, ambiguous, missing, report = [], [], [], [], []
    for g in lists:
        matched = [(p, by_photo[p["photoId"]]) for p in g["photos"] if by_photo.get(p["photoId"])]
        missing += [(g["name"], p) for p in g["photos"] if not by_photo.get(p["photoId"])]
        props = {c["property"] for _, cards in matched for c in cards}
        if len(props) != 1:
            print(f"Skipping {g['name']}: its photos span {sorted(props) or 'no Buck Book cards'}.")
            continue
        prop = props.pop()
        buck_id = mapping.get(g["photoGroupId"])
        if buck_id and buck_id not in bucks:
            print(f"Skipping {g['name']}: its Buck Book buck was merged or deleted. "
                  f"Remove it from {MAP_FILE.relative_to(ROOT)} to recreate it.")
            continue
        if not buck_id:
            buck_id = "b" + format(int(time.time() * 1000), "x") + secrets.token_hex(2)
            clash = [b["name"] for b in bucks.values() if b["property"] == prop
                     and b["name"].strip().lower() == g["name"].strip().lower()]
            cover_cards = by_photo.get(g.get("summaryPhotoId"), [])
            cover = cover_card(cover_cards, (g.get("summaryPhotoSettings") or {}).get("boundingBox")) if cover_cards else None
            cover = cover if cover in remote else None
            new_bucks.append({"id": buck_id, "name": g["name"].strip()[:40], "property": prop,
                              "status": STATUS.get(g.get("status"), "active"), "cover": cover,
                              "by_user": user["id"], "by_name": member, "_group": g["photoGroupId"],
                              "_clash": bool(clash)})
        n_votes = n_had = 0
        for p, cards in matched:
            if len(cards) > 1:
                ambiguous.append((g["name"], p, len(cards)))
                continue
            card = cards[0]["id"]
            if card not in remote:
                continue
            if card in mine:
                n_had += 1
                continue
            votes.append({"card_id": card, "voter": user["id"], "voter_name": member, "verdict": "buck",
                          "buck_id": buck_id, "at": datetime.now(timezone.utc).isoformat()})
            n_votes += 1
        report.append(f"  {g['name']:<14} {prop:<12} {len(g['photos']):>3} photos: {n_votes} new votes"
                      + (f", {n_had} already voted by {member}" if n_had else "")
                      + ("  (new buck)" if not mapping.get(g["photoGroupId"]) else ""))

    print(f"\nHit List -> Buck Book, voting as {member}:")
    print("\n".join(report))
    for b in new_bucks:
        if b["_clash"]:
            print(f"  Note: {b['name']} already exists at {b['property']}; a second buck with that name will be made.")
    if ambiguous:
        print(f"\n{len(ambiguous)} photos show more than one buck; left for the crew to name:")
        for name, p, n in ambiguous:
            print(f"  {name}: {p['cameraName']} {p['photoDateUtc'][:16]} ({n} bucks in frame)")
    if missing:
        print(f"\n{len(missing)} Hit List photos aren't in the local deck yet (pull, tag and import them first):")
        for name, p in missing:
            print(f"  {name}: {p['cameraName']} {p['photoDateUtc'][:16]}")
    if not new_bucks and not votes:
        print("\nNothing new to add.")
        return
    if not assume_yes and input(f"\nCreate {len(new_bucks)} bucks and add {len(votes)} votes? [y/N] ").strip().lower() != "y":
        print("Nothing changed.")
        return

    backup()
    for b in new_bucks:
        rest("POST", "bucks", {k: v for k, v in b.items() if not k.startswith("_")})
        mapping[b["_group"]] = b["id"]
        MAP_FILE.write_text(json.dumps(mapping, indent=1))
    for i in range(0, len(votes), 50):
        rest("POST", "votes", votes[i:i + 50], prefer="resolution=ignore-duplicates")
    print(f"Created {len(new_bucks)} bucks and added {len(votes)} votes as {member}.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    member = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--as=")), "")
    if cmd == "pull":
        pull()
    elif cmd == "apply" and member:
        apply(member, assume_yes="--yes" in sys.argv)
    else:
        raise SystemExit(__doc__)
