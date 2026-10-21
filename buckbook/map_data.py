"""Map data for Buck Book: where the cameras stand, and the parcel lines around each property.

Commands:
  prepare   Work it out locally, into data/map/ (git-ignored); nothing leaves the Mac.
            Cameras: each camera's positions over time from the GPS on its photos (a move of more than
            150 m starts a new position). Cameras that send no GPS get a row with no position, to be
            placed by hand on the map. Parcels: the Wisconsin statewide parcel layer (public record)
            around each property's cameras; parcels a camera stands on are ours, and so are touching
            parcels with the same owner. Each property's map covers our parcels plus a margin.
  push      Write data/map/prepared.json to Supabase (013_map.sql must be applied): camera positions,
            parcels, and each property's map box. Shows what goes and asks first (--yes skips the
            question). Parcels an admin has already marked ours or not keep that mark.

Usage: .venv/bin/python -m buckbook.map_data prepare
Never prints coordinates; the repo is public and so is anything pasted from a terminal.
"""
import json
import math
import sqlite3
import sys
import urllib.parse
import urllib.request

from buckbook.db import ROOT
from buckbook.import_deck import gps_of

OUT = ROOT / "data" / "map"
PARCELS_URL = ("https://services3.arcgis.com/n6uYoouQZW75n5WI/ArcGIS/rest/services/"
               "Wisconsin_Statewide_Parcels_DB/FeatureServer/0/query")
MOVE_M = 150          # farther than this from where it stood = the camera was moved
SEARCH_M = 500        # look for parcels this far around the cameras
MARGIN_M = 400        # the map shows this much past our parcel lines


def metres(a, b):
    k = math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 111320 * k)


def grow(box, m):
    """A (west, south, east, north) box grown by m metres on every side."""
    w, s, e, n = box
    dlat = m / 111320
    dlon = m / (111320 * math.cos(math.radians((s + n) / 2)))
    return w - dlon, s - dlat, e + dlon, n + dlat


def box_of(points):
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    return min(lons), min(lats), max(lons), max(lats)


# ---------- cameras ----------
def camera_names():
    """photoId -> (camera name the cards use, property), from the local staging deck."""
    conn = sqlite3.connect(f"file:{ROOT / 'data' / 'buckbook' / 'buckbook.db'}?mode=ro", uri=True)
    return {pid: (cam, prop) for pid, cam, prop in conn.execute("SELECT photo_id, camera, property FROM cards")}


def cameras():
    names = camera_names()
    by_id = {}
    for records in sorted((ROOT / "data" / "photos").glob("*/records.json")):
        for r in json.loads(records.read_text()):
            cam = by_id.setdefault(r["cameraId"], {"reveal": r.get("cameraName"), "pts": [], "card_names": {}, "props": {}})
            when = r.get("photoDateUtc") or ""
            if when >= (cam.get("latest") or ""):
                cam["latest"], cam["reveal"] = when, r.get("cameraName")
            if r["photoId"] in names:
                name, prop = names[r["photoId"]]
                cam["card_names"][name] = cam["card_names"].get(name, 0) + 1
                if prop:
                    cam["props"].setdefault(when[:10], {}).setdefault(prop, 0)
                    cam["props"][when[:10]][prop] += 1
            if when and (pos := gps_of(r)) and all(pos):
                cam["pts"].append((when, *pos))
    rows = []
    for cid, cam in by_id.items():
        if not cam["card_names"]:
            continue                                   # never imported (barn food plot etc.)
        name = max(cam["card_names"], key=cam["card_names"].get)
        segs = []
        for when, lat, lon in sorted(cam["pts"]):
            if segs and metres((lat, lon), segs[-1]["pts"][-1][1:]) < MOVE_M:
                segs[-1]["pts"].append((when, lat, lon))
            else:
                segs.append({"pts": [(when, lat, lon)]})
        segs = [s for s in segs if len(s["pts"]) >= 3]   # a stray fix isn't a move
        for s in segs:
            lats = sorted(p[1] for p in s["pts"]); lons = sorted(p[2] for p in s["pts"])
            first, last = s["pts"][0][0], s["pts"][-1][0]
            # Property for this position: what the photos taken there were filed under.
            tally = {}
            for day, props in cam["props"].items():
                if first[:10] <= day <= last[:10]:
                    for p, n in props.items():
                        tally[p] = tally.get(p, 0) + n
            rows.append({"id": f"{cid}:{first[:10]}", "camera": name,
                         "reveal_name": cam["reveal"] if cam["reveal"] != name else None,
                         "property": max(tally, key=tally.get) if tally else None,
                         "lat": round(lats[len(lats) // 2], 6), "lon": round(lons[len(lons) // 2], 6),   # median: GPS jitters
                         "first_at": first, "last_at": last, "photos": len(s["pts"]), "source": "photos"})
        if not segs:
            tally = {}
            for props in cam["props"].values():
                for p, n in props.items():
                    tally[p] = tally.get(p, 0) + n
            rows.append({"id": f"{cid}:nogps", "camera": name, "reveal_name": cam["reveal"] if cam["reveal"] != name else None,
                         "property": max(tally, key=tally.get) if tally else None, "lat": None, "lon": None,
                         "first_at": None, "last_at": cam.get("latest") or None, "photos": sum(cam["card_names"].values()),
                         "source": "photos"})
    # A position whose photos aren't imported yet takes the property of the nearest position that is known.
    known = [r for r in rows if r["property"] and r["lat"] is not None]
    for r in rows:
        if not r["property"] and r["lat"] is not None and known:
            r["property"] = min(known, key=lambda k: metres((k["lat"], k["lon"]), (r["lat"], r["lon"])))["property"]
    return rows


# ---------- parcels ----------
def fetch_parcels(box):
    w, s, e, n = box
    params = {"where": "1=1", "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "STATEID,OWNERNME1,OWNERNME2,GISACRES,DEEDACRES",
              "outSR": 4326, "returnGeometry": "true", "f": "geojson", "resultRecordCount": 2000}
    req = urllib.request.Request(PARCELS_URL + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "BuckBook map_data"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["features"]


def rounded(geom):
    """Coordinates to 6 decimals (about 10 cm), dropping repeats: smaller to store and to send to phones."""
    def ring(r):
        out = []
        for x, y in r:
            p = [round(x, 6), round(y, 6)]
            if not out or out[-1] != p:
                out.append(p)
        return out
    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [ring(r) for r in geom["coordinates"]]}
    return {"type": "MultiPolygon", "coordinates": [[ring(r) for r in poly] for poly in geom["coordinates"]]}


def polygons(geom):
    return geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]


def contains(geom, lat, lon):
    def inside(ring):
        hit = False
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                hit = not hit
        return hit
    return any(inside(poly[0]) and not any(inside(h) for h in poly[1:]) for poly in polygons(geom))


def touches(a, b, within_m=3):
    """Parcels share a corner or an edge: some corner of one lies within a few metres of the other's outline."""
    ra = [poly[0] for poly in polygons(a)]
    rb = [poly[0] for poly in polygons(b)]
    ba, bb = geom_box(a), geom_box(b)
    if ba[2] < bb[0] or bb[2] < ba[0] or ba[3] < bb[1] or bb[3] < ba[1]:
        return False

    def near_outline(x, y, rings):
        k = 111320 * math.cos(math.radians(y))
        for ring in rings:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                # point-to-segment distance in metres, on a flat local grid
                px, py, ax, ay, bx, by = x * k, y * 111320, x1 * k, y1 * 111320, x2 * k, y2 * 111320
                dx, dy = bx - ax, by - ay
                t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
                if math.hypot(px - ax - t * dx, py - ay - t * dy) < within_m:
                    return True
        return False
    return (any(near_outline(x, y, rb) for ring in ra for x, y in ring)
            or any(near_outline(x, y, ra) for ring in rb for x, y in ring))


def geom_box(geom):
    return box_of([(y, x) for poly in polygons(geom) for x, y in poly[0]])


def spread(feats, ours, owners):
    """Touching parcels with the same owner as ours are ours too (a farm is often several tax parcels)."""
    grew = True
    while grew:
        grew = False
        for f in feats:
            sid = f["properties"]["STATEID"]
            if sid in ours or (f["properties"]["OWNERNME1"] or "").strip().upper() not in owners:
                continue
            if any(touches(f["geometry"], g["geometry"]) for g in feats if g["properties"]["STATEID"] in ours):
                ours.add(sid); grew = True


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    cams = cameras()
    placed = [c for c in cams if c["lat"] is not None]
    print(f"Cameras: {len({c['camera'] for c in cams})}, {len(placed)} positions from photo GPS")
    for c in sorted(cams, key=lambda c: (c["camera"], c["first_at"] or "")):
        where = f"{c['photos']} photos, {(c['first_at'] or '')[:10]} to {(c['last_at'] or '')[:10]}" if c["lat"] is not None else "no GPS: place it on the map"
        print(f"  {c['camera']:<34} {c['property'] or '?':<12} {where}")
    properties, parcels = {}, {}
    for prop in ("Stoddard", "North Ridge"):
        here = [c for c in placed if c["property"] == prop]        # every place a camera has stood here
        if not here:
            print(f"{prop}: no camera GPS, skipped"); continue
        feats = fetch_parcels(grow(box_of([(c["lat"], c["lon"]) for c in here]), SEARCH_M))
        ours = {f["properties"]["STATEID"] for f in feats if any(contains(f["geometry"], c["lat"], c["lon"]) for c in here)}
        owners = {(f["properties"]["OWNERNME1"] or "").strip().upper() for f in feats if f["properties"]["STATEID"] in ours} - {""}
        for _ in range(4):                              # a parcel found may reach past the area searched: search again
            spread(feats, ours, owners)
            boxes = [geom_box(f["geometry"]) for f in feats if f["properties"]["STATEID"] in ours] or [box_of([(c["lat"], c["lon"]) for c in here])]
            core = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
            box = grow(core, MARGIN_M)
            before = len(ours)
            feats = fetch_parcels(box)                  # everything inside the map box
            spread(feats, ours, owners)
            if len(ours) == before:
                break
        for f in feats:
            p = f["properties"]
            parcels[p["STATEID"]] = {"id": p["STATEID"], "property": prop, "ours": p["STATEID"] in ours,
                                     "owner": (p["OWNERNME1"] or "").strip() or None, "owner2": (p["OWNERNME2"] or "").strip() or None,
                                     "acres": round(p["GISACRES"] or p["DEEDACRES"] or 0, 1) or None, "geom": rounded(f["geometry"])}
        acres = sum(parcels[s]["acres"] or 0 for s in ours if s in parcels)
        w_m = metres((box[1], box[0]), (box[1], box[2])); h_m = metres((box[1], box[0]), (box[3], box[0]))
        properties[prop] = {"map_west": box[0], "map_south": box[1], "map_east": box[2], "map_north": box[3]}
        print(f"{prop}: {len(ours)} parcels ours ({acres:.0f} acres), {len(feats)} parcels on the map, "
              f"map {w_m / 1000:.1f} x {h_m / 1000:.1f} km")
    data = {"cameras": cams, "parcels": list(parcels.values()), "properties": properties}
    (OUT / "prepared.json").write_text(json.dumps(data))
    size = len(json.dumps(data["parcels"]).encode())
    print(f"Saved data/map/prepared.json ({size / 1024:.0f} KB of parcel lines). Next: push.")


# ---------- push ----------
def push(assume_yes=False):
    from buckbook.supabase_sync import rest, rest_all
    data = json.loads((OUT / "prepared.json").read_text())
    try:
        marked = {r["id"]: r["ours"] for r in rest_all("parcels", "?select=id,ours")}
    except SystemExit as err:
        raise SystemExit(f"Can't read parcels; has 013_map.sql been run? ({err})")
    parcels = [{**p, "ours": marked.get(p["id"], p["ours"])} for p in data["parcels"]]
    cams = [c for c in data["cameras"]]
    size = len(json.dumps(parcels).encode()) + len(json.dumps(cams).encode())
    print(f"Writes {len(cams)} camera rows, {len(parcels)} parcels ({sum(p['ours'] for p in parcels)} ours), "
          f"map boxes for {', '.join(data['properties']) or 'no property'}: about {size / 1024:.0f} KB of rows, no files.")
    if not assume_yes and input("Send it? [y/N] ").strip().lower() != "y":
        return print("Nothing sent.")
    for i in range(0, len(cams), 200):
        rest("POST", "camera_spots", cams[i:i + 200], "?on_conflict=id", "resolution=merge-duplicates,return=minimal")
    for i in range(0, len(parcels), 100):
        rest("POST", "parcels", parcels[i:i + 100], "?on_conflict=id", "resolution=merge-duplicates,return=minimal")
    for prop, box in data["properties"].items():
        rest("PATCH", "properties", box, "?name=eq." + urllib.parse.quote(prop), "return=minimal")
    print("Sent.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prepare":
        prepare()
    elif cmd == "push":
        push("--yes" in sys.argv)
    else:
        print(__doc__)
