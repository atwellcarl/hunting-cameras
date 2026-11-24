"""Model how a given wind moves over a property's terrain, with WindNinja (US Forest Service fire lab).

Everything stays in data/wind/ (git-ignored): the elevation grid, the WindNinja runs, and previews.
WindNinja runs in Docker from tools/windninja/Dockerfile (official source, command line only).

Commands:
  dem PROPERTY                 Fetch USGS 3DEP lidar elevation at 10 m for the property's map box plus
                               1.5 km around it (terrain outside the lines shapes the wind inside them).
  run PROPERTY DIR MPH [AM|PM] One case: wind from DIR (N, SSW, ...) at MPH, measured 20 ft up. AM or PM
                               adds WindNinja's diurnal model (thermal slope flows) for a clear late-fall
                               morning (7:30) or evening (16:30); without it, no thermals.
  preview PROPERTY CASE        Draw a case's arrows over terrain shading with our parcel lines, as a PNG.
  html PROPERTY CASE [leaf-off]  An interactive map of a case (data/wind/runs/CASE/CASE.html): the app's map
                               layers, parcel lines, the property's sits, and the modeled wind, above the
                               trees or where you stand (canopy sheltering from USFS tree cover; leaf-off
                               shelters less). Tap for speed and direction. It holds exact locations, so it
                               stays on this Mac.

  app PROPERTY                 Pack every no-thermals run of a property for the app's Modeled Wind layer, into
                               data/wind/app/<property>/: grid.json (cell positions every 40 m and canopy
                               cover) and one <DIR>_<MPH>.json per run (direction and speed of each cell).
  upload                       Send data/wind/app/ to the private photos bucket (wind/...). Shows the size
                               and asks first (--yes skips the question).

Usage: .venv/bin/python -m buckbook.wind_model run "North Ridge" S 10 PM
Never prints coordinates.
"""
import json
import math
import subprocess
import sys
import urllib.parse
import urllib.request

from buckbook.db import ROOT
from buckbook.map_data import grow

WIND = ROOT / "data" / "wind"
IMAGE = "buckbook-windninja"
DIRS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
MARGIN_M = 1500
MESH_M = 20                       # solver mesh; the 10 m elevation is averaged to this
# A clear late-fall day for the thermal runs. Temperature matters less than the sun and the clouds.
DIURNAL = {"AM": {"hour": 7, "minute": 30, "temp_f": 30}, "PM": {"hour": 16, "minute": 30, "temp_f": 45},
           # sharper tests of the thermal model: before dawn (cold air drains downhill), midday (sun-warmed
           # slopes pull air up), after dark (draining again)
           "DAWN": {"hour": 6, "minute": 0, "temp_f": 28}, "NOON": {"hour": 12, "minute": 0, "temp_f": 50},
           "DARK": {"hour": 17, "minute": 45, "temp_f": 38}}


def slug(prop):
    return prop.lower().replace(" ", "")


def prepared():
    return json.loads((ROOT / "data" / "map" / "prepared.json").read_text())


def docker(*args, capture=False):
    cmd = ["docker", "run", "--rm", "-v", f"{WIND}:/data", IMAGE, *args]
    return subprocess.run(cmd, check=True, text=True, capture_output=capture)


def dem(prop):
    """Lidar elevation in UTM (WindNinja wants a projected grid), 10 m cells."""
    WIND.mkdir(parents=True, exist_ok=True)
    b = prepared()["properties"][prop]
    w, s, e, n = grow((b["map_west"], b["map_south"], b["map_east"], b["map_north"]), MARGIN_M)
    zone = int(((w + e) / 2 + 180) // 6) + 1
    km_w = (e - w) * 111.32 * math.cos(math.radians((s + n) / 2)); km_h = (n - s) * 111.32
    q = {"bbox": f"{w},{s},{e},{n}", "bboxSR": 4326, "imageSR": 26900 + zone, "size": f"{round(km_w * 100)},{round(km_h * 100)}",
         "format": "tiff", "pixelType": "F32", "interpolation": "RSP_BilinearInterpolation", "f": "image"}
    url = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage?" + urllib.parse.urlencode(q)
    path = WIND / f"{slug(prop)}_dem.tif"
    path.write_bytes(urllib.request.urlopen(url, timeout=180).read())
    print(f"{prop}: {km_w:.1f} x {km_h:.1f} km of elevation, UTM zone {zone} -> {path.relative_to(ROOT)}")


def case_name(prop, d, mph, part):
    return f"{slug(prop)}_{d}_{mph}mph_{part or 'none'}"


def run(prop, d, mph, part=None):
    d = d.upper()
    if d not in DIRS:
        raise SystemExit(f"Direction must be one of {', '.join(DIRS)}")
    name = case_name(prop, d, mph, part)
    out = WIND / "runs" / name
    out.mkdir(parents=True, exist_ok=True)
    cfg = {
        "num_threads": 8,
        "elevation_file": f"/data/{slug(prop)}_dem.tif",
        "initialization_method": "domainAverageInitialization",
        "time_zone": "America/Chicago",
        "input_speed": mph, "input_speed_units": "mph",
        "input_direction": DIRS.index(d) * 22.5,          # degrees the wind comes FROM
        "input_wind_height": 20, "units_input_wind_height": "ft",
        "output_wind_height": 20, "units_output_wind_height": "ft",
        "vegetation": "trees",
        "mesh_resolution": MESH_M, "units_mesh_resolution": "m",
        "output_speed_units": "mph",
        "write_ascii_output": "true", "ascii_out_resolution": MESH_M, "units_ascii_out_resolution": "m",
        "output_path": f"/data/runs/{name}",
    }
    if part:
        t = DIURNAL[part]
        cfg.update({"diurnal_winds": "true", "year": 2026, "month": 11, "day": 1, "hour": t["hour"], "minute": t["minute"],
                    "uni_air_temp": t["temp_f"], "air_temp_units": "F", "uni_cloud_cover": 10, "cloud_cover_units": "percent"})
    (out / "run.cfg").write_text("".join(f"{k} = {v}\n" for k, v in cfg.items()))
    print(f"Running {name} ...")
    res = docker("WindNinja_cli", f"/data/runs/{name}/run.cfg", capture=True)
    (out / "windninja.log").write_text(res.stdout + res.stderr)
    grids = sorted(p.name for p in out.glob("*.asc"))
    print(f"Done: {len(grids)} grids in data/wind/runs/{name}/")
    return name


def read_asc(path):
    import numpy as np
    head, rows = {}, []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2 and parts[0][0].isalpha():          # header: ncols, cellsize, NODATA_value…
                head[parts[0].lower()] = float(parts[1])
            else:
                rows.append([float(v) for v in parts])
    return head, np.array(rows)


def utm_of(lonlat_pts, zone):
    """Lon/lat to UTM with gdaltransform in the container (no coordinates printed)."""
    text = "\n".join(f"{x} {y}" for x, y in lonlat_pts)
    res = subprocess.run(["docker", "run", "--rm", "-i", IMAGE, "gdaltransform", "-s_srs", "EPSG:4326", "-t_srs", f"EPSG:{26900 + zone}"],
                         input=text, text=True, capture_output=True, check=True)
    return [tuple(map(float, l.split()[:2])) for l in res.stdout.strip().splitlines()]


def preview(prop, name):
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out = WIND / "runs" / name
    vel = next(out.glob("*_vel.asc")); ang = next(out.glob("*_ang.asc"))
    hv, speed = read_asc(vel); _, frm = read_asc(ang)
    cs, x0, y0 = hv["cellsize"], hv["xllcorner"], hv["yllcorner"]
    nrows, ncols = speed.shape
    xs = x0 + (np.arange(ncols) + .5) * cs; ys = y0 + (np.arange(nrows)[::-1] + .5) * cs
    # Terrain shading from the same grid WindNinja used.
    dem_asc = WIND / f"{slug(prop)}_dem.asc"
    if not dem_asc.exists():
        docker("gdal_translate", "-q", "-of", "AAIGrid", f"/data/{slug(prop)}_dem.tif", f"/data/{slug(prop)}_dem.asc")
    hd, z = read_asc(dem_asc)
    dz_y, dz_x = np.gradient(z, hd["cellsize"])
    slope = np.arctan(np.hypot(dz_x, dz_y)); aspect = np.arctan2(-dz_x, dz_y)
    az, alt = math.radians(315), math.radians(45)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    dext = [hd["xllcorner"], hd["xllcorner"] + z.shape[1] * hd["cellsize"], hd["yllcorner"], hd["yllcorner"] + z.shape[0] * hd["cellsize"]]
    fig, ax = plt.subplots(figsize=(9, 9.6), dpi=110)
    ax.imshow(shade, cmap="gray", extent=dext, vmin=-.2, vmax=1)
    ax.contour(np.linspace(dext[0], dext[1], z.shape[1]), np.linspace(dext[3], dext[2], z.shape[0]), z, levels=np.arange(z.min() // 10 * 10, z.max(), 10),
               colors="k", linewidths=.25, alpha=.35)
    # Arrows every 4 cells (80 m), pointing where the air goes, colored by speed.
    step = 4
    to = np.radians(frm[::step, ::step] + 180)
    u, v = np.sin(to), np.cos(to)
    X, Y = np.meshgrid(xs[::step], ys[::step])
    q = ax.quiver(X, Y, u, v, speed[::step, ::step], cmap="plasma", scale=38, width=.0032, headwidth=4)
    fig.colorbar(q, ax=ax, fraction=.035, pad=.01, label="mph, 20 ft up")
    # Our parcel lines
    zone = int(((prepared()["properties"][prop]["map_west"] + prepared()["properties"][prop]["map_east"]) / 2 + 180) // 6) + 1
    for p in prepared()["parcels"]:
        if p["property"] != prop or not p["ours"]:
            continue
        polys = p["geom"]["coordinates"] if p["geom"]["type"] == "MultiPolygon" else [p["geom"]["coordinates"]]
        for poly in polys:
            pts = utm_of(poly[0], zone)
            ax.plot([a for a, _ in pts], [b for _, b in pts], color="#FF6B1A", lw=2)
    b = prepared()["properties"][prop]
    corners = utm_of([(b["map_west"], b["map_south"]), (b["map_east"], b["map_north"])], zone)
    ax.set_xlim(corners[0][0], corners[1][0]); ax.set_ylim(corners[0][1], corners[1][1])
    ax.set_xticks([]); ax.set_yticks([])
    d, mph, part = name.split("_")[1:4]
    ax.set_title(f"{prop}: wind from {d} at {mph.replace('mph', '')} mph" + ("" if part == "none" else f", {part} thermals") + " (arrows point downwind)")
    png = out / f"{name}.png"
    fig.savefig(png, bbox_inches="tight"); plt.close(fig)
    print(f"Preview: {png.relative_to(ROOT)}")
    return png


# ---------- wind where you stand ----------
# WindNinja reports wind 20 ft above the vegetation: over the woods, that's above the treetops. To bring it
# down to standing height, each 20 m cell is scaled by how much the trees there shelter it:
#  - open ground (under 10% canopy): the wind's log profile from 20 ft down to 5 ft over short vegetation
#    (roughness 0.03 m), about 0.74;
#  - under trees: the sheltered wind adjustment factor used in US fire modeling (Andrews 2012, RMRS-GTR-266):
#    WAF = 0.555 / (sqrt(f H) ln((20 + 0.36 H) / (0.13 H))), with H canopy height in ft and f the crown fill
#    (canopy cover x crown ratio / 3). Driftless hardwoods: H 65 ft, crown ratio 0.5.
# Canopy cover comes from the USFS / NLCD Tree Canopy Cover (30 m, latest year). It's a summer measure, so
# leaf-off sheltering is weaker: LEAF_OFF scales the crown fill down.
TCC = "https://imagery.geoplatform.gov/iipp/rest/services/Vegetation/USFS_EDW_NLCD_TCC_CONUS/ImageServer"
CANOPY_FT, CROWN_RATIO, LEAF_OFF = 65, .5, .35
OPEN_FACTOR = math.log(1.52 / .03) / math.log(6.1 / .03)          # 5 ft vs 20 ft over grass


def canopy(prop, head):
    """Percent tree canopy on the same 20 m grid as the wind runs."""
    import numpy as np
    tif, asc = WIND / f"{slug(prop)}_canopy.tif", WIND / f"{slug(prop)}_canopy.asc"
    if not asc.exists():
        x0, y0, cs, nc, nr = head["xllcorner"], head["yllcorner"], head["cellsize"], int(head["ncols"]), int(head["nrows"])
        zone = int(((prepared()["properties"][prop]["map_west"] + prepared()["properties"][prop]["map_east"]) / 2 + 180) // 6) + 1
        q = {"bbox": f"{x0},{y0},{x0 + nc * cs},{y0 + nr * cs}", "bboxSR": 26900 + zone, "imageSR": 26900 + zone, "size": f"{nc},{nr}",
             "format": "tiff", "pixelType": "U8", "interpolation": "RSP_NearestNeighbor", "time": "1704067200000", "f": "image"}
        tif.write_bytes(urllib.request.urlopen(TCC + "/exportImage?" + urllib.parse.urlencode(q), timeout=120).read())
        docker("gdal_translate", "-q", "-of", "AAIGrid", f"/data/{tif.name}", f"/data/{asc.name}")
    _, cc = read_asc(asc)
    return np.where(cc <= 100, cc, 0)                                # 254/255 = no data: treat as open


def stand_factor(cc, leaf_off=False):
    """Wind at 5 ft where you stand, as a share of WindNinja's 20 ft wind, for each cell's canopy cover."""
    import numpy as np
    def sheltered(c):
        f = c / 100 * CROWN_RATIO / 3 * (LEAF_OFF if leaf_off else 1)
        return np.minimum(.555 / (np.sqrt(np.maximum(f, 1e-6) * CANOPY_FT) * math.log((20 + .36 * CANOPY_FT) / (.13 * CANOPY_FT))), OPEN_FACTOR)
    # Open below 5% canopy, sheltered from 25%, and a blend between for field edges and scattered trees.
    w = np.clip((cc - 5) / 20, 0, 1)
    return (1 - w) * OPEN_FACTOR + w * sheltered(np.maximum(cc, 25))


def html(prop, name, leaf_off=False):
    import numpy as np
    from buckbook.supabase_sync import call
    out = WIND / "runs" / name
    hv, speed = read_asc(next(out.glob("*_vel.asc"))); _, frm = read_asc(next(out.glob("*_ang.asc")))
    cs, x0, y0 = hv["cellsize"], hv["xllcorner"], hv["yllcorner"]
    nrows, ncols = speed.shape
    cc = canopy(prop, hv)
    ground = speed * stand_factor(cc, leaf_off)
    b = prepared()["properties"][prop]
    zone = int(((b["map_west"] + b["map_east"]) / 2 + 180) // 6) + 1
    # Every cell centre to lon/lat in one go, then the wind there as a short arrow (shaft and head).
    cells = [(r, c) for r in range(nrows) for c in range(ncols) if speed[r, c] >= 0]
    utm = [(x0 + (c + .5) * cs, y0 + (nrows - r - .5) * cs) for r, c in cells]
    text = "\n".join(f"{x} {y}" for x, y in utm)
    res = subprocess.run(["docker", "run", "--rm", "-i", IMAGE, "gdaltransform", "-s_srs", f"EPSG:{26900 + zone}", "-t_srs", "EPSG:4326"],
                         input=text, text=True, capture_output=True, check=True)
    lonlat = [tuple(map(float, l.split()[:2])) for l in res.stdout.strip().splitlines()]
    k = 1 / (111320 * math.cos(math.radians(lonlat[0][1])))
    def arrow(lon, lat, to_deg, length):
        t = math.radians(to_deg)
        ex, ey = math.sin(t), math.cos(t)
        tail = (lon - ex * length / 2 * k, lat - ey * length / 2 / 111320)
        tip = (lon + ex * length / 2 * k, lat + ey * length / 2 / 111320)
        barbs = []
        for side in (-1, 1):
            a = t + math.pi + side * math.radians(28)
            barbs.append([tip, (tip[0] + math.sin(a) * length * .32 * k, tip[1] + math.cos(a) * length * .32 / 111320)])
        rnd = lambda p: [round(p[0], 6), round(p[1], 6)]
        return [[rnd(tail), rnd(tip)]] + [[rnd(a), rnd(bb)] for a, bb in barbs]
    sparse, coarse, fine, points = [], [], [], []      # arrows every 160, 80 and 40 m, for zoomed out to zoomed in
    for (r, c), (lon, lat) in zip(cells, lonlat):
        v, f = float(speed[r, c]), float(frm[r, c])
        props = {"mph": round(v, 1), "ground": round(float(ground[r, c]), 1), "from": DIRS[round(f / 22.5) % 16], "deg": round(f)}
        points.append([round(lon, 6), round(lat, 6), props["mph"], props["deg"], props["ground"], int(cc[r, c])])
        if r % 2 == 0 and c % 2 == 0:
            fine.append({"type": "Feature", "properties": props, "geometry": {"type": "MultiLineString", "coordinates": arrow(lon, lat, f + 180, 32)}})
        if r % 8 == 0 and c % 8 == 0:
            sparse.append({"type": "Feature", "properties": props, "geometry": {"type": "MultiLineString", "coordinates": arrow(lon, lat, f + 180, 120)}})
        if r % 4 == 0 and c % 4 == 0:
            coarse.append({"type": "Feature", "properties": props, "geometry": {"type": "MultiLineString", "coordinates": arrow(lon, lat, f + 180, 64)}})
    parcels = [{"type": "Feature", "properties": {"ours": p["ours"]}, "geometry": p["geom"]} for p in prepared()["parcels"] if p["property"] == prop]
    st, sits = call("GET", "/rest/v1/sits?select=set_at,wind_dir,lat,lon,spot,hunter_name&property=eq." + urllib.parse.quote(prop) + "&lat=not.is.null&order=set_at")
    sit_feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                  "properties": {"label": (s["spot"] or "Sit") + " · " + s["set_at"][:10], "wind": s["wind_dir"] or "?", "who": s["hunter_name"] or ""}} for s in sits]
    d, mph, part = name.split("_")[1:4]
    title = f"{prop}: wind from {d} at {mph.replace('mph', '')} mph" + ("" if part == "none" else f", {part} thermals")
    data = {"title": title, "box": [[b["map_west"], b["map_south"]], [b["map_east"], b["map_north"]]],
            "sparse": {"type": "FeatureCollection", "features": sparse}, "coarse": {"type": "FeatureCollection", "features": coarse}, "fine": {"type": "FeatureCollection", "features": fine},
            "parcels": {"type": "FeatureCollection", "features": parcels}, "sits": {"type": "FeatureCollection", "features": sit_feats},
            "points": points, "maxmph": round(float(speed.max()), 1), "maxground": round(float(ground.max()), 1),
            "season": "leaves off" if leaf_off else "leaves on"}
    page = (ROOT / "tools" / "windninja" / "wind_map.html").read_text().replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
    path = out / f"{name}.html"
    path.write_text(page)
    print(f"Map: {path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.1f} MB, {len(fine)} arrows, {len(sit_feats)} sits)")
    return path


# ---------- for the app ----------
APP = WIND / "app"
APP_STEP = 2                      # every 2nd 20 m cell: 40 m apart


def cells_lonlat(prop, head, step):
    """Lon/lat of every step-th cell centre, row by row from the north, via gdaltransform in the container."""
    cs, x0, y0, nc, nr = head["cellsize"], head["xllcorner"], head["yllcorner"], int(head["ncols"]), int(head["nrows"])
    b = prepared()["properties"][prop]
    zone = int(((b["map_west"] + b["map_east"]) / 2 + 180) // 6) + 1
    rows, cols = list(range(0, nr, step)), list(range(0, nc, step))
    text = "\n".join(f"{x0 + (c + .5) * cs} {y0 + (nr - r - .5) * cs}" for r in rows for c in cols)
    res = subprocess.run(["docker", "run", "--rm", "-i", IMAGE, "gdaltransform", "-s_srs", f"EPSG:{26900 + zone}", "-t_srs", "EPSG:4326"],
                         input=text, text=True, capture_output=True, check=True)
    return rows, cols, [tuple(map(float, l.split()[:2])) for l in res.stdout.strip().splitlines()]


def app(prop):
    import base64
    import numpy as np
    runs = sorted(r for r in (WIND / "runs").iterdir() if r.name.startswith(slug(prop) + "_") and r.name.endswith("_none"))
    if not runs:
        raise SystemExit(f"No runs for {prop} yet.")
    head, _ = read_asc(next(runs[0].glob("*_vel.asc")))
    rows, cols, ll = cells_lonlat(prop, head, APP_STEP)
    cc = canopy(prop, head)[::APP_STEP, ::APP_STEP]
    lon0, lat0 = ll[0]
    def pack(a, dtype):
        return base64.b64encode(np.asarray(a, dtype=dtype).tobytes()).decode()
    out = APP / slug(prop)
    out.mkdir(parents=True, exist_ok=True)
    # Positions as millionths of a degree from the first cell (little-endian int32), canopy as whole percent.
    grid = {"property": prop, "rows": len(rows), "cols": len(cols), "cell_m": head["cellsize"] * APP_STEP, "origin": [round(lon0, 6), round(lat0, 6)],
            "dlon": pack([round((x - lon0) * 1e6) for x, _ in ll], "<i4"), "dlat": pack([round((y - lat0) * 1e6) for _, y in ll], "<i4"),
            "canopy": pack(np.clip(cc, 0, 100).ravel(), "u1"),
            "model": "WindNinja 4.0.0 standard solver, 20 ft above vegetation; canopy: USFS/NLCD tree canopy cover"}
    (out / "grid.json").write_text(json.dumps(grid, separators=(",", ":")))
    index = []
    for r in runs:
        d, mph = r.name.split("_")[1], int(r.name.split("_")[2].replace("mph", ""))
        _, v = read_asc(next(r.glob("*_vel.asc"))); _, a = read_asc(next(r.glob("*_ang.asc")))
        v, a = v[::APP_STEP, ::APP_STEP].ravel(), a[::APP_STEP, ::APP_STEP].ravel()
        # Speed in fifths of a mph (to 51 mph), direction the wind comes from in 256ths of a turn.
        run_json = {"dir": d, "mph": mph, "speed": pack(np.clip(np.round(v * 5), 0, 255), "u1"), "from": pack(np.round(a / 360 * 256) % 256, "u1")}
        (out / f"{d}_{mph}.json").write_text(json.dumps(run_json, separators=(",", ":")))
        index.append({"dir": d, "mph": mph, "file": f"{d}_{mph}.json"})
    (out / "index.json").write_text(json.dumps({"property": prop, "runs": index}, separators=(",", ":")))
    size = sum(f.stat().st_size for f in out.iterdir())
    names = ", ".join(f"{i['dir']} {i['mph']}" for i in index)
    print(f"{prop}: {len(rows)} x {len(cols)} cells every {grid['cell_m']:.0f} m, {len(index)} runs ({names}), {size / 1024:.0f} KB")


def upload(assume_yes=False):
    from buckbook.supabase_sync import upload as put
    files = sorted(f for f in APP.rglob("*.json"))
    size = sum(f.stat().st_size for f in files)
    print(f"{len(files)} files, {size / 1e6:.2f} MB, to the private photos bucket under wind/ (crew only).")
    if not assume_yes and input("Send them? [y/N] ").strip().lower() != "y":
        return print("Nothing sent.")
    for f in files:
        put("wind/" + str(f.relative_to(APP)), f.read_bytes(), "application/json")
    print("Sent.")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["dem"] and len(a) == 2:
        dem(a[1])
    elif a[:1] == ["run"] and len(a) in (4, 5):
        preview(a[1], run(a[1], a[2], int(a[3]), a[4].upper() if len(a) == 5 else None))
    elif a[:1] == ["preview"] and len(a) == 3:
        preview(a[1], a[2])
    elif a[:1] == ["app"] and len(a) == 2:
        app(a[1])
    elif a[:1] == ["upload"]:
        upload("--yes" in a)
    elif a[:1] == ["html"] and len(a) in (3, 4):
        html(a[1], a[2], leaf_off=a[3:] == ["leaf-off"])
    else:
        print(__doc__)
