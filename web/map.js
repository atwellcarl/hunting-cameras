// Buck Book map: cameras, spots, the trees we've sat and the parcel lines, over leaf-off photos, summer
// photos, topo or lidar terrain shading, with the wind lens for planning. index.html loads this file (and
// MapLibre) the first time the Map tab opens, and it uses the page's own helpers: state, sb, $, toast,
// queueOp, mustQueue, netError, friendly, mgrsOf, fmtDay, fmtWhen, eventsOf, openSitView, WIND16, ALL_CARDS.
//
// Map pictures come straight from public services (USGS, Wisconsin DNR) and are kept on the phone in a
// cache of their own, so a downloaded property works with no signal. None of them pass through Supabase.
(() => {
  // ---------- map pictures ----------
  const TILE_CACHE = "buckbook-tiles-v1";
  const R = 6378137, HALF = Math.PI * R;
  // Web Mercator box of one tile, for services that draw any box we ask for (exportImage).
  const tileBox = (z, x, y) => { const s = 2 * HALF / 2 ** z, w = -HALF + x * s, n = HALF - y * s; return [w, n - s, w + s, n]; };
  const exportUrl = (service, z, x, y, extra, px = 256) => `${service}/exportImage?` + new URLSearchParams({
    bbox: tileBox(z, x, y).join(","), bboxSR: 3857, imageSR: 3857, size: `${px},${px}`, f: "image", ...extra });
  const DNR = "https://dnrmaps.wi.gov/arcgis_image/rest/services/DW_Imagery/EN_Image_Basemap_Latest_Leaf_Off/ImageServer";
  const DEP = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer";
  const USGS = name => `https://basemap.nationalmap.gov/arcgis/rest/services/${name}/MapServer/tile`;
  const rule = fn => JSON.stringify({ rasterFunction: fn });
  // min/max: the zooms the service has (the map enlarges the last one past that). save: zooms a download keeps.
  // Listed bottom to top: Leaf-Off draws over Summer, which fills in while the slow leaf-off pieces load.
  // The state's leaf-off server takes 5-30 s per request whatever its size, so it's asked for 512-pixel
  // pieces: one request covers four ordinary tiles at the same detail.
  const LAYERS = {
    summer: { name: "Summer", note: "Leaves on", min: 0, max: 16, save: [12, 16],
      url: (z, x, y) => `${USGS("USGSImageryOnly")}/${z}/${y}/${x}` },
    leafoff: { name: "Leaf-Off", note: "Bare trees, sharpest", min: 13, max: 17, px: 512, save: [13, 17],
      url: (z, x, y) => exportUrl(DNR, z, x, y, { format: "jpg" }, 512) },
    topo: { name: "Topo", note: "USGS map", min: 0, max: 16, save: [12, 16],
      url: (z, x, y) => `${USGS("USGSTopo")}/${z}/${y}/${x}` },
    terrain: { name: "Terrain", note: "Lidar shading", min: 10, max: 17, save: [12, 17],
      url: (z, x, y) => exportUrl(DEP, z, x, y, { format: "jpgpng", renderingRule: rule("Hillshade Multidirectional") }) },
    contours: { name: "Contours", note: "10 ft lines", overlay: true, min: 13, max: 17, save: [13, 17],
      url: (z, x, y) => exportUrl(DEP, z, x, y, { format: "png32", transparent: "true", renderingRule: rule("Preset 10ft Contour Interval") }) },
  };
  const BASES = ["leafoff", "summer", "topo", "terrain"];          // the order they're offered in
  const tileKey = (layer, z, x, y) => `https://tiles.buckbook.invalid/${layer}/${z}/${x}/${y}`;

  // A few requests at a time per service: the state's server is slow, and we share it with everyone.
  const running = {}, waiting = {};
  async function gently(host, job) {
    while ((running[host] || 0) >= 4) await new Promise(ok => (waiting[host] ||= []).push(ok));
    running[host] = (running[host] || 0) + 1;
    try { return await job(); } finally { running[host]--; waiting[host]?.shift()?.(); }
  }
  let cacheP = null;
  const tiles = () => cacheP ||= caches.open(TILE_CACHE);
  async function getTile(layer, z, x, y, signal) {
    const key = tileKey(layer, z, x, y), c = await tiles();
    const hit = await c.match(key);
    if (hit) return hit.arrayBuffer();
    const url = LAYERS[layer].url(z, x, y);
    const res = await gently(new URL(url).host, () => fetch(url, { signal }));
    const type = res.headers.get("content-type") || "";
    if (!res.ok || !type.startsWith("image/")) throw new Error(`no ${layer} tile`);   // the services report errors as JSON
    const buf = await res.arrayBuffer();
    c.put(key, new Response(buf, { headers: { "content-type": type } })).catch(() => {});   // browsing saves it too
    return buf;
  }
  maplibregl.addProtocol("bbt", async (params, abort) => {
    const [, layer, z, x, y] = params.url.match(/^bbt:\/\/(\w+)\/(\d+)\/(\d+)\/(\d+)/);
    return { data: await getTile(layer, +z, +x, +y, abort.signal) };
  });

  // ---------- small helpers ----------
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const metres = (a, b) => {
    const k = Math.cos((a[1] + b[1]) / 2 * Math.PI / 180);
    return Math.hypot((a[1] - b[1]) * 111320, (a[0] - b[0]) * 111320 * k);
  };
  const bearing = (a, b) => {          // degrees from a to b, lon/lat pairs
    const k = Math.cos(a[1] * Math.PI / 180);
    return (Math.atan2((b[0] - a[0]) * k, b[1] - a[1]) * 180 / Math.PI + 360) % 360;
  };
  const offset = (p, deg, m) => {      // the point m metres from p toward deg
    const r = deg * Math.PI / 180;
    return [p[0] + Math.sin(r) * m / (111320 * Math.cos(p[1] * Math.PI / 180)), p[1] + Math.cos(r) * m / 111320];
  };
  const yd = m => Math.round(m * 1.0936);
  const away = m => m < 1609 ? `${yd(m)} yd` : `${(m / 1609).toFixed(1)} mi`;
  const DEG = d => WIND16.indexOf(d) * 22.5;
  const near16 = (a, b) => { const i = WIND16.indexOf(a), j = WIND16.indexOf(b); return i >= 0 && j >= 0 && Math.min((i - j + 16) % 16, (j - i + 16) % 16) <= 1; };
  const canEdit = () => !document.body.classList.contains("role-viewer");
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  };
  const prefs = Object.assign({ base: "leafoff", contours: false, show: { cameras: true, spots: true, trees: true, parcels: true } }, store.get("buckbook-map") || {});
  const savePrefs = () => store.set("buckbook-map", prefs);

  const SPOT_KINDS = [["stand", "Stand"], ["saddle", "Saddle Tree"], ["scrape", "Scrape"], ["rub", "Rub"], ["bedding", "Bedding"],
    ["crossing", "Crossing"], ["food", "Food"], ["water", "Water"], ["parking", "Parking"], ["other", "Other"]];
  const kindLabel = k => (SPOT_KINDS.find(([v]) => v === k) || [, "Spot"])[1];
  const ICON = {
    camera: '<path d="M4 8h3l1.5-2h7L17 8h3v10H4z"/><circle cx="12" cy="13" r="3.2"/>',
    stand: '<path d="M12 3l5 7h-3l3 5H7l3-5H7z"/><path d="M12 15v6"/>',
    saddle: '<path d="M12 3v18"/><path d="M8 9c2 1 6 1 8 0M8 13c2 1 6 1 8 0"/>',
    scrape: '<path d="M5 18c3-1 4-5 7-5s4 4 7 5"/><path d="M9 9l1 2M12 7v3M15 9l-1 2"/>',
    rub: '<path d="M12 3v18"/><path d="M9 8h6v6H9z"/>',
    bedding: '<ellipse cx="12" cy="13" rx="7" ry="4.5"/>',
    crossing: '<path d="M4 8h16M4 16h16"/><path d="M9 5l-3 3 3 3M15 13l3 3-3 3"/>',
    food: '<path d="M12 20V9"/><path d="M12 9c-3 0-4-3-4-5 3 0 4 2 4 5zM12 13c3 0 4-3 4-5-3 0-4 2-4 5z"/>',
    water: '<path d="M12 4c3 4 5 7 5 10a5 5 0 0 1-10 0c0-3 2-6 5-10z"/>',
    parking: '<path d="M8 20V5h5a4 4 0 0 1 0 8H8"/>',
    other: '<circle cx="12" cy="12" r="3"/>',
    tree: '<path d="M12 3l6 8h-3l4 6H5l4-6H6z"/><path d="M12 17v4"/>',
  };
  const svg = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON[name] || ICON.other}</svg>`;

  // ---------- what's on the map ----------
  const prop = () => state.property;
  function boxOf(p) {
    const b = state.properties?.[p];
    if (b?.map_west != null) return [[b.map_west, b.map_south], [b.map_east, b.map_north]];
    // Before map_data.py has run: fit whatever we know about.
    const pts = [...cameras(p).map(c => [c.lon, c.lat]), ...Object.values(state.spots || {}).filter(s => s.property === p).map(s => [s.lon, s.lat]),
      ...Object.values(state.sits || {}).filter(s => s.property === p && s.lat != null).map(s => [s.lon, s.lat])];
    if (pts.length) {
      const xs = pts.map(q => q[0]), ys = pts.map(q => q[1]);
      return [[Math.min(...xs) - .004, Math.min(...ys) - .003], [Math.max(...xs) + .004, Math.max(...ys) + .003]];
    }
    if (b?.weather_lat != null) return [[b.weather_lon - .02, b.weather_lat - .015], [b.weather_lon + .02, b.weather_lat + .015]];
    return null;
  }
  // Survey lines run a degree or two off true north on screen. The bearing that turns our parcels square
  // with the phone: the length-weighted average direction of their edges, folded into one quarter turn.
  function squareBearing(p = prop()) {
    let x = 0, y = 0;
    (state.parcels || []).filter(q => q.property === p && q.ours).forEach(q => {
      const polys = q.geom.type === "MultiPolygon" ? q.geom.coordinates : [q.geom.coordinates];
      polys.forEach(poly => poly[0].forEach((a, i, ring) => {
        const b = ring[i + 1]; if (!b) return;
        const len = metres(a, b), ang = bearing(a, b) * Math.PI / 180 * 4;     // ×4: N, E, S and W edges agree
        x += Math.cos(ang) * len; y += Math.sin(ang) * len;
      }));
    });
    if (!x && !y) return 0;
    let deg = Math.atan2(y, x) * 180 / Math.PI / 4;                             // within ±45°
    return Math.abs(deg) < 0.2 ? 0 : +deg.toFixed(2);
  }
  // Each camera where it stands now; where it stood before is kept as its history.
  function cameras(p = prop()) {
    const by = {};
    (state.cameraSpots || []).filter(c => c.lat != null).forEach(c => (by[c.camera] ||= []).push(c));
    return Object.values(by).map(list => {
      list.sort((a, b) => (b.last_at || b.updated_at || "").localeCompare(a.last_at || a.updated_at || ""));
      return { ...list[0], history: list.slice(1) };
    }).filter(c => c.property === p);
  }
  const unplaced = (p = prop()) => {
    const placed = new Set((state.cameraSpots || []).filter(c => c.lat != null).map(c => c.camera));
    return [...new Set((state.cameraSpots || []).filter(c => c.lat == null && c.property === p && !placed.has(c.camera)).map(c => c.camera))];
  };
  const spots = (p = prop()) => Object.values(state.spots || {}).filter(s => s.property === p);
  // Trees: sits within 35 m of each other are the same tree.
  function trees(p = prop()) {
    const out = [];
    Object.values(state.sits || {}).filter(s => s.property === p && s.lat != null).sort((a, b) => a.set_at.localeCompare(b.set_at)).forEach(s => {
      const t = out.find(t => metres([t.lon, t.lat], [s.lon, s.lat]) < 35);
      if (t) { t.sits.push(s); const n = t.sits.length; t.lat += (s.lat - t.lat) / n; t.lon += (s.lon - t.lon) / n; }
      else out.push({ lat: s.lat, lon: s.lon, sits: [s] });
    });
    out.forEach((t, i) => {
      t.id = "tree" + i;
      const named = t.sits.map(s => s.spot).filter(Boolean);
      const stand = spots(p).filter(s => ["stand", "saddle"].includes(s.kind) && s.label && metres([s.lon, s.lat], [t.lon, t.lat]) < 40)[0];
      const cam = cameras(p).map(c => [c, metres([c.lon, c.lat], [t.lon, t.lat])]).sort((a, b) => a[1] - b[1])[0];
      t.name = named.length ? mode(named) : stand ? stand.label : cam ? `Tree by ${cam[0].camera}` : "Tree";
    });
    return out;
  }
  const mode = list => Object.entries(list.reduce((m, v) => (m[v] = (m[v] || 0) + 1, m), {})).sort((a, b) => b[1] - a[1])[0][0];
  // What a sit saw: deer, bucks, and how many groups knew we were there.
  function tally(sitList) {
    let deer = 0, bucks = 0, bad = 0;
    const named = new Set();
    sitList.forEach(s => eventsOf(s.id).forEach(e => {
      if (e.kind !== "deer") return;
      (e.members || []).forEach(m => { deer += m.count || 1; if (m.kind === "buck") { bucks += m.count || 1; if (m.buck_id) named.add(m.buck_id); } });
      if (["busted", "winded"].includes(e.ended_how)) bad++;
    }));
    return { deer, bucks, bad, named: [...named].map(id => state.bucks?.[id]?.name).filter(Boolean) };
  }
  // A sit "had" a wind if it started in it or changed to it.
  // A sit has two winds: the one we felt at the tree (and any changes we logged), and the day's prevailing wind,
  // the weather service's hourly wind at the property's town during the sit. Picking a wind finds sits by the
  // prevailing wind, because that's what a forecast gives us; what we felt at the tree is what the terrain did
  // with it. With no weather record, the wind we felt stands in.
  const sitWinds = s => [s.wind_dir, ...eventsOf(s.id).filter(e => e.kind === "wind").map(e => e.wind_dir)].filter(w => w && w !== "variable");
  function dayWinds(s) {
    const from = new Date(s.set_at).getTime() - 30 * 60e3, to = new Date(s.down_at || s.set_at).getTime() + 30 * 60e3;
    const hrs = (state.sitWeather?.[s.id] || []).filter(h => h.wind_from_deg != null);
    const during = hrs.filter(h => { const t = new Date(h.hour).getTime(); return t >= from && t <= to; });
    return (during.length ? during : hrs).map(h => ({ dir: WIND16[Math.round(h.wind_from_deg / 22.5) % 16], mph: Math.round(h.wind_mph) }));
  }
  const sitMatches = (s, dir) => { const day = dayWinds(s); return day.length ? day.some(w => near16(w.dir, dir)) : sitWinds(s).some(w => near16(w, dir)); };
  // "day SSE 7 · felt WNW", or just what we felt when there's no weather record.
  function windLine(s) {
    const day = dayWinds(s), felt = sitWinds(s).join(" → ");
    if (!day.length) return felt ? `felt ${felt}` : "wind —";
    const dirs = [...new Set(day.map(w => w.dir))].join("/"), mph = Math.round(day.reduce((a, w) => a + w.mph, 0) / day.length);
    return `day ${dirs} ${mph}` + (felt ? ` · felt ${felt}` : "");
  }

  // ---------- the map ----------
  const view = $("view-map");
  const ui = document.createElement("div");
  ui.className = "m-ui";
  ui.innerHTML = `
    <div class="m-tools">
      <button type="button" class="m-tool" data-act="layers" aria-label="Map layers"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/></svg></button>
      <button type="button" class="m-tool" data-act="wind" aria-label="Wind lens"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 9h11a3 3 0 1 0-3-3M3 15h15a3 3 0 1 1-3 3M3 12h7"/></svg><span class="m-windtag" hidden></span></button>
      <button type="button" class="m-tool" data-act="locate" aria-label="Where I am"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg></button>
      <button type="button" class="m-tool m-add" data-act="add" aria-label="Add to the map"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg></button>
    </div>
    <button type="button" class="m-tool m-north" data-act="north" aria-label="North up, or square to our parcels"><svg viewBox="0 0 24 24"><path d="M12 3l5 15-5-3.5L7 18z" fill="#FF6B1A"/><text x="12" y="23.5" text-anchor="middle" font-size="6" font-weight="700" fill="currentColor" font-family="sans-serif">N</text></svg></button>
    <div class="m-cross" hidden><i></i></div>
    <button type="button" class="m-wpill" hidden></button>
    <div class="m-pinfo" hidden></div>
    <div class="m-card" hidden><button type="button" class="m-x" aria-label="Close">×</button><div class="m-body"></div></div>`;
  view.append(ui);
  const card = ui.querySelector(".m-card"), body = ui.querySelector(".m-body"), cross = ui.querySelector(".m-cross");

  const style = { version: 8, sources: {}, layers: [] };
  for (const [id, L] of Object.entries(LAYERS)) {
    style.sources[id] = { type: "raster", tiles: [`bbt://${id}/{z}/{x}/{y}`], tileSize: L.px || 256, minzoom: L.min, maxzoom: L.max };
    style.layers.push({ id, type: "raster", source: id, layout: { visibility: "none" },
      paint: L.overlay ? { "raster-opacity": .6 } : { "raster-fade-duration": 150 } });
  }
  style.layers.unshift({ id: "bg", type: "background", paint: { "background-color": "#1b2118" } });
  const fc = features => ({ type: "FeatureCollection", features });
  for (const id of ["parcels", "cones", "paths", "mwind"]) style.sources[id] = { type: "geojson", data: fc([]) };
  // Modeled wind arrows: every 160 m zoomed out, 80 m, then 40 m close in. Color is speed; the scale runs to
  // the run's fastest wind above the trees, so ground level reads as calmer on the same scale.
  const mwColor = ["interpolate", ["linear"], ["get", "v"], 0, "#3b0f70", 5, "#8c2981", 10, "#de4968", 15, "#fe9f6d", 22, "#fcfdbf"];
  const mwLayers = [["mw-sparse", 2, 0, 14.5], ["mw-coarse", 1, 14.5, 15.5], ["mw-fine", 0, 15.5, 24]];
  style.layers.push(
    { id: "parcel-fill", type: "fill", source: "parcels", paint: { "fill-color": "#FF6B1A", "fill-opacity": ["case", ["get", "ours"], .07, 0] } },
    { id: "parcel-line", type: "line", source: "parcels", filter: ["!", ["get", "ours"]], paint: { "line-color": "#ffffff", "line-opacity": .55, "line-width": 1 } },
    { id: "ours-line", type: "line", source: "parcels", filter: ["get", "ours"], paint: { "line-color": "#FF6B1A", "line-width": 3 } },
    { id: "parcel-pick", type: "line", source: "parcels", filter: ["==", ["get", "id"], ""], paint: { "line-color": "#ffffff", "line-width": 3, "line-dasharray": [2, 1] } },
    { id: "cones", type: "fill", source: "cones", paint: { "fill-color": "#FF6B1A", "fill-opacity": .22 } },
    { id: "cone-edge", type: "line", source: "cones", paint: { "line-color": "#FF6B1A", "line-opacity": .7, "line-width": 1 } },
    { id: "paths", type: "line", source: "paths", filter: ["==", ["geometry-type"], "LineString"],
      paint: { "line-color": ["case", ["get", "bad"], "#E88A70", "#7BD06C"], "line-width": 2.5, "line-dasharray": [3, 1.5] } },
    { id: "path-heads", type: "circle", source: "paths", filter: ["==", ["geometry-type"], "Point"],
      paint: { "circle-radius": 4, "circle-color": ["case", ["get", "bad"], "#E88A70", "#7BD06C"], "circle-stroke-color": "#0E110D", "circle-stroke-width": 1 } },
    ...mwLayers.flatMap(([id, lvl, min, max]) => [
      { id: id + "-case", type: "line", source: "mwind", filter: ["==", ["get", "lvl"], lvl], minzoom: min, maxzoom: max,
        paint: { "line-color": "#000", "line-opacity": .5, "line-width": 4 }, layout: { "line-cap": "round" } },
      { id, type: "line", source: "mwind", filter: ["==", ["get", "lvl"], lvl], minzoom: min, maxzoom: max,
        paint: { "line-color": mwColor, "line-width": 2 }, layout: { "line-cap": "round" } }]),
  );

  const start = boxOf(prop());
  const map = new maplibregl.Map({
    container: "map", style, minZoom: 12, maxZoom: 20, attributionControl: false,
    pitchWithRotate: false, touchPitch: false, renderWorldCopies: false,      // two fingers turn the map
    // With nothing to fit yet, the middle of Wisconsin (the repo is public: no property coordinates here).
    ...(start ? { bounds: start, fitBoundsOptions: { padding: 20, bearing: squareBearing() } } : { center: [-89.8, 44.6], zoom: 12 }),
  });
  const north = ui.querySelector(".m-north");
  const pointNorth = () => { north.firstElementChild.style.transform = `rotate(${-map.getBearing()}deg)`; };
  map.on("rotate", pointNorth); map.on("moveend", pointNorth); pointNorth();
  // Square to our parcels, or north up if it's already square.
  north.addEventListener("click", () => { const sq = squareBearing(), b = map.getBearing(); map.easeTo({ bearing: Math.abs(b - sq) < 0.5 && sq ? 0 : sq }); });
  map.addControl(new maplibregl.ScaleControl({ unit: "imperial", maxWidth: 90 }), "bottom-left");
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "Photos: WI DNR (WROC), USGS · Elevation: USGS 3DEP · Parcels: WI Statewide Parcels" }), "bottom-right");
  let ready = false, shownProp = prop();
  // Pins and lines go on as soon as the style is in; "load" would wait for every photo tile first.
  // (isStyleLoaded() waits for tiles too, so use the style's own flag and its "style.load" event.)
  const whenStyled = () => { if (ready || !map.style?._loaded) return; ready = true; applyLayers(); draw(); };
  map.on("style.load", whenStyled); map.on("styledata", whenStyled); map.once("load", whenStyled);
  whenStyled();
  // The credits start folded behind their (i), so they don't sit on the scale bar.
  map.once("load", () => view.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show"));
  map.on("zoom", () => view.classList.toggle("m-close", map.getZoom() >= 16));

  function applyLayers() {
    if (!ready) return;
    BASES.forEach(b => map.setLayoutProperty(b, "visibility", b === prefs.base || (b === "summer" && prefs.base === "leafoff") ? "visible" : "none"));
    map.setLayoutProperty("contours", "visibility", prefs.contours ? "visible" : "none");
    // White lines over the photos, dark ones over the light topo map and terrain shading.
    const light = prefs.base === "topo" || prefs.base === "terrain";
    map.setPaintProperty("contours", "raster-brightness-min", light ? 0 : 1);
    map.setPaintProperty("contours", "raster-opacity", light ? .45 : .6);
    map.setPaintProperty("parcel-line", "line-color", light ? "#2b2f2a" : "#ffffff");
    map.setPaintProperty("parcel-pick", "line-color", light ? "#000000" : "#ffffff");
    for (const id of ["parcel-fill", "parcel-line", "ours-line", "parcel-pick"]) map.setLayoutProperty(id, "visibility", prefs.show.parcels ? "visible" : "none");
  }

  // ---------- markers ----------
  let markers = [];
  function marker(lngLat, cls, inner, label, onTap) {
    const el = document.createElement("button");
    el.type = "button"; el.className = "m-pin " + cls;
    el.innerHTML = `<span class="m-dot">${inner}</span>${label ? `<span class="m-label">${esc(label)}</span>` : ""}`;
    el.addEventListener("click", e => {
      e.stopPropagation();
      if (!picking) return onTap();
      if (!cls.includes("m-cam")) pickTarget(lngLat, label);           // picking a sit's place: stands and trees count
    });
    const m = new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat(lngLat).addTo(map);
    markers.push(m);
    return el;
  }
  let me = null, meMarker = null, watch = null;
  let lens = null;               // { dir } while the wind tool is on: sits in that wind light up
  let picked = null;             // what the card is showing, so a redraw keeps it
  function draw() {
    if (!ready) return;
    markers.forEach(m => m.remove()); markers = [];
    const p = prop();
    // parcels
    map.getSource("parcels").setData(fc((state.parcels || []).filter(x => x.property === p).map(x => ({
      type: "Feature", geometry: x.geom, properties: { id: x.id, ours: !!x.ours } }))));
    if (prefs.show.cameras) cameras(p).forEach(c => marker([c.lon, c.lat], "m-cam", svg("camera"), c.camera, () => pick({ type: "camera", id: c.camera })));
    if (prefs.show.spots) spots(p).forEach(s => marker([s.lon, s.lat], "m-spot k-" + s.kind, svg(s.kind), s.label || kindLabel(s.kind), () => pick({ type: "spot", id: s.id })));
    const ts = trees(p);
    if (prefs.show.trees || lens) ts.forEach(t => {
      const n = lens ? t.sits.filter(s => sitMatches(s, lens.dir)).length : t.sits.length;
      const el = marker([t.lon, t.lat], "m-tree" + (lens && !n ? " m-dim" : "") + (lens && n ? " m-hit" : ""), `<b>${n}</b>`, t.name, () => pick({ type: "tree", id: t.id }));
      el.setAttribute("aria-label", `${t.name}: ${n} sit${n === 1 ? "" : "s"}`);
    });
    drawLens(ts);
    if (me) { meMarker?.remove(); meMarker = new maplibregl.Marker({ element: meEl(), anchor: "center" }).setLngLat(me).addTo(map); }
    const tag = ui.querySelector(".m-windtag"); tag.hidden = !lens; tag.textContent = lens?.dir || "";
    if (picked) pick(picked, true);
  }
  function meEl() { const el = document.createElement("div"); el.className = "m-me"; return el; }

  // ---------- the bottom card ----------
  function openCard(html, cls = "") {
    body.innerHTML = html; card.className = "m-card " + cls; card.hidden = false;
    return body;
  }
  function closeCard() {
    card.hidden = true; picked = null; cross.hidden = true; adding = null;
  }
  ui.querySelector(".m-x").addEventListener("click", () => picking ? endPick(null) : closeCard());
  const fromYou = lngLat => me ? `<p class="m-away">${away(metres(me, lngLat))} ${WIND16[Math.round(bearing(me, lngLat) / 22.5) % 16]} of you</p>` : "";
  const btnRow = (...btns) => `<div class="m-btns">${btns.filter(Boolean).join("")}</div>`;
  const b = (act, label, cls = "") => `<button type="button" class="btn ${cls}" data-act="${act}">${esc(label)}</button>`;
  function on(root, handlers) { root.querySelectorAll("[data-act]").forEach(el => el.addEventListener("click", () => handlers[el.dataset.act]?.(el))); }

  function pick(what, quiet = false) {
    picked = what;
    if (what.type === "camera") return cameraCard(what.id);
    if (what.type === "spot") return spotCard(what.id);
    if (what.type === "tree") return treeCard(what.id, quiet);
    if (what.type === "parcel") return parcelInfo(what.id);
  }

  function cameraCard(name) {
    const c = cameras().find(x => x.camera === name);
    if (!c) return closeCard();
    const since = c.first_at ? `Here since ${fmtDay(c.first_at)}` : "Placed by hand";
    const hist = c.history.map(h => `<li>${h.first_at ? `${fmtDay(h.first_at)} – ${fmtDay(h.last_at)}` : "Earlier"} · ${away(metres([h.lon, h.lat], [c.lon, c.lat]))} away${h.property !== c.property ? ` (${esc(h.property)})` : ""}</li>`).join("");
    const winds = cameraWinds(c.camera);
    const el = openCard(`
      <p class="label">Camera</p><h3>${esc(c.camera)}</h3>
      <p class="m-sub">${since}${c.photos ? ` · ${c.photos} photos` : ""}${c.reveal_name ? ` · Reveal calls it “${esc(c.reveal_name)}”` : ""}</p>
      ${fromYou([c.lon, c.lat])}
      ${winds}
      ${hist ? `<p class="label">Moved From</p><ul class="m-list">${hist}</ul>` : ""}
      <p class="m-grid">${esc(mgrsOf(c.lat, c.lon))}</p>
      ${c.source === "placed" && canEdit() ? btnRow(b("move", "Move It"), b("remove", "Take Off Map", "danger")) : ""}`);
    on(el, {
      move: () => startAdd({ kind: "camera", camera: c.camera, row: c }),
      remove: async () => { await removeCam(c.id); closeCard(); draw(); },
    });
  }
  // Buck photos at a camera by the wind Reveal reported, once the photos are loaded.
  function cameraWinds(name) {
    if (!state.photosLoaded) return "";
    const cards = (typeof ALL_CARDS !== "undefined" ? ALL_CARDS : []).filter(c => c.cam === name && c.wind);
    if (!cards.length) return "";
    const by = {};
    cards.forEach(c => { const d = String(c.wind).split(/\s+/)[0].toUpperCase(); if (WIND16.includes(d)) by[d] = (by[d] || 0) + 1; });
    const top = Object.entries(by).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([d, n]) => `${d} ${n}`).join(" · ");
    return `<p class="label">Buck Photos By Wind</p><p class="m-sub">${top}${lens ? ` · <b>${cards.filter(c => near16(String(c.wind).split(/\s+/)[0].toUpperCase(), lens.dir)).length} in ${lens.dir}-ish</b>` : ""}</p>`;
  }

  function spotCard(id) {
    const s = state.spots?.[id];
    if (!s) return closeCard();
    const mine = s.created_by === state.myUid || state.isAdmin;
    const el = openCard(`
      <p class="label">${esc(kindLabel(s.kind))}</p><h3>${esc(s.label || kindLabel(s.kind))}</h3>
      ${s.notes ? `<p class="m-notes">${esc(s.notes)}</p>` : ""}
      <p class="m-sub">Added by ${esc(s.created_by_name || "someone")} · ${fmtDay(s.created_at || new Date().toISOString())}</p>
      ${fromYou([s.lon, s.lat])}
      <p class="m-grid">${esc(mgrsOf(s.lat, s.lon))}</p>
      ${mine ? btnRow(b("edit", "Edit"), b("move", "Move")) : ""}`);
    on(el, { edit: () => spotForm(s), move: () => startAdd({ kind: "spot", row: s, keepForm: true }) });
  }

  function treeCard(id, quiet) {
    const t = trees().find(x => x.id === id);
    if (!t) return closeCard();
    const list = t.sits.slice().sort((a, b) => b.set_at.localeCompare(a.set_at));
    const all = tally(list);
    const match = lens ? list.filter(s => sitMatches(s, lens.dir)) : null;
    const m = match ? tally(match) : null;
    const rows = list.map(s => {
      const tl = tally([s]);
      const hit = lens && sitMatches(s, lens.dir);
      return `<li><button type="button" class="m-sit${hit ? " m-hit" : ""}" data-sit="${esc(s.id)}"><b>${fmtDay(s.set_at)} ${new Date(s.set_at).getHours() < 12 ? "AM" : "PM"}</b>
        <span>${esc(s.hunter_name || "")} · ${esc(windLine(s))}</span>
        <small>${tl.deer ? `${tl.deer} deer${tl.bucks ? `, ${tl.bucks} buck${tl.bucks === 1 ? "" : "s"}` : ""}` : "Nothing seen"}${tl.bad ? ` · ${tl.bad} busted/winded` : ""}</small>
        <small class="m-check" data-check="${esc(s.id)}"></small></button></li>`;
    }).join("");
    const el = openCard(`
      <p class="label">Tree</p><h3>${esc(t.name)}</h3>
      <p class="m-sub">${list.length} sit${list.length === 1 ? "" : "s"} · ${all.deer} deer · ${all.bucks} buck${all.bucks === 1 ? "" : "s"}${all.bad ? ` · ${all.bad} busted/winded` : ""}</p>
      ${m ? `<p class="m-lens">On ${esc(lens.dir)}-ish days: ${match.length} sit${match.length === 1 ? "" : "s"} · ${m.deer} deer · ${m.bucks} buck${m.bucks === 1 ? "" : "s"}${m.bad ? ` · ${m.bad} busted/winded` : ""}</p>` : ""}
      ${all.named.length ? `<p class="m-sub">Seen here: ${esc(all.named.join(", "))}</p>` : ""}
      ${fromYou([t.lon, t.lat])}
      <p class="m-sub" id="mSlope"></p>
      <ul class="m-list m-sits">${rows}</ul>`);
    el.querySelectorAll("[data-sit]").forEach(x => x.addEventListener("click", () => openSitView(x.dataset.sit)));
    // Each sit against the model for that day's wind.
    list.forEach(sit => modelAtSit(sit).then(c => {
      const box = body.querySelector(`[data-check="${CSS.escape(sit.id)}"]`);
      if (!box || !c) return;
      box.textContent = !c.modeled ? `Day's wind ${c.day.dir} ${c.day.mph}: not modeled yet`
        : `Model (${c.run}): ${c.model} here, ${c.ground} mph · felt ${c.felt} ${c.match ? "✓" : "✗"}`;
      box.classList.toggle("bad", !c.match && c.modeled);
    }));
    slopeAt(t.lon, t.lat).then(sl => {
      const box = body.querySelector("#mSlope");
      if (!box || !sl || picked?.id !== id) return;
      box.textContent = sl.pct < 3 ? `Nearly flat here, ${sl.ft.toLocaleString()} ft.`
        : `Ground falls to the ${sl.down} (${sl.pct}% slope), ${sl.ft.toLocaleString()} ft. Cool air at dawn and dusk drifts that way; as the day warms it rises the other way.`;
    });
  }
  // Which way the ground falls at a point, from USGS lidar elevations 30 m around it. Kept on the phone
  // once looked up, so it shows with no signal too.
  const SLOPES = "buckbook-map-slopes";
  async function slopeAt(lon, lat) {
    const key = `${lon.toFixed(4)},${lat.toFixed(4)}`, saved = store.get(SLOPES) || {};
    if (saved[key]) return saved[key];
    if (!navigator.onLine) return null;
    const pts = [[lon, lat], ...[0, 90, 180, 270].map(d => offset([lon, lat], d, 30))];
    try {
      const q = new URLSearchParams({ geometry: JSON.stringify({ points: pts, spatialReference: { wkid: 4326 } }),
        geometryType: "esriGeometryMultipoint", returnFirstValueOnly: "true", f: "json" });
      const r = await (await fetch(`${DEP}/getSamples?${q}`)).json();
      const z = []; r.samples.forEach(x => { z[x.locationId] = parseFloat(x.value); });
      if (z.length < 5 || z.some(v => !isFinite(v))) return null;
      const east = (z[2] - z[4]) / 60, north = (z[1] - z[3]) / 60;      // rise per metre
      const downDeg = (Math.atan2(-east, -north) * 180 / Math.PI + 360) % 360;
      const out = { down: WIND16[Math.round(downDeg / 22.5) % 16], pct: Math.round(Math.hypot(east, north) * 100), ft: Math.round(z[0] * 3.2808) };
      saved[key] = out; store.set(SLOPES, saved);
      return out;
    } catch { return null; }
  }

  // A tapped parcel is outlined, with a small info chip at the bottom; tap the chip for owner and acres.
  let parcelOn = null;
  function parcelInfo(id, open = false) {
    const x = (state.parcels || []).find(p => p.id === id), chip = ui.querySelector(".m-pinfo");
    if (!x) return parcelOff();
    parcelOn = id;
    map.setFilter("parcel-pick", ["==", ["get", "id"], id]);
    chip.hidden = false;
    chip.classList.toggle("open", open);
    chip.innerHTML = `<button type="button" class="m-pi-head"><span class="m-i">i</span>${x.ours ? "Our ground" : "Neighbor"}${x.acres ? ` · ${Math.round(x.acres)} ac` : ""}</button>` + (open ? `
      <div class="m-pi-body"><b>${esc(x.owner || "Owner not listed")}</b>${x.owner2 ? `<br>${esc(x.owner2)}` : ""}<br>${x.acres ? `${x.acres} acres · ` : ""}Wisconsin parcel map
      ${state.isAdmin ? `<br><button type="button" class="linkish" data-act="ours">${x.ours ? "Not ours" : "Mark as ours"}</button>` : ""}</div>` : "");
    chip.querySelector(".m-pi-head").addEventListener("click", () => parcelInfo(id, !open));
    on(chip, { ours: async () => {
      const { error } = await sb.from("parcels").update({ ours: !x.ours }).eq("id", x.id);
      if (error) return toast(netError(error) ? "That needs signal." : friendly(error));
      x.ours = !x.ours; draw(); parcelInfo(id, true);
    } });
  }
  function parcelOff() {
    parcelOn = null;
    ui.querySelector(".m-pinfo").hidden = true;
    if (ready) map.setFilter("parcel-pick", ["==", ["get", "id"], ""]);
  }

  // Taps on the map itself: a parcel, or nothing (close the card).
  // Taps on the map itself: with Modeled Wind on, the wind at that spot; otherwise a parcel (or nothing).
  map.on("click", e => {
    if (adding || picking) return;
    closeCard();
    if (mw.on) { parcelOff(); return mwReadout(e.lngLat); }
    const hit = prefs.show.parcels && map.queryRenderedFeatures(e.point, { layers: ["parcel-fill"] })[0];
    if (hit && hit.properties.id !== parcelOn) parcelInfo(hit.properties.id);
    else parcelOff();
  });

  // ---------- picking where a sit was ----------
  let picking = null;              // { resolve, target } while the sit form is asking for a place
  function pickCard() {
    const t = picking.target;
    const el = openCard(`
      <p class="label">Where Was the Sit?</p>
      <p class="m-sub">${t ? `<b>${esc(t.label)}</b>` : "Move the map until the cross is on the tree, or tap a stand or a tree you've sat."}</p>
      ${btnRow(b("cancel", "Cancel"), me && !t ? b("gps", "Use My GPS") : "", b("use", t ? "Use This One" : "Use This Spot"))}`, "m-adding");
    on(el, {
      cancel: () => endPick(null),
      gps: () => map.easeTo({ center: me, zoom: Math.max(map.getZoom(), 17) }),
      use: () => { const c = map.getCenter(); endPick(picking.target || { lat: +c.lat.toFixed(6), lon: +c.lng.toFixed(6) }); },
    });
  }
  function pickTarget(lngLat, label) {
    picking.target = { lat: lngLat[1], lon: lngLat[0], label };
    map.easeTo({ center: lngLat });
    pickCard();
  }
  // Dragging the map after tapping a stand means "somewhere else": back to the crosshair.
  map.on("dragstart", () => { if (picking?.target) { picking.target = null; pickCard(); } });
  function endPick(result) {
    const p = picking;
    picking = null;
    view.classList.remove("m-picking");
    closeCard();
    p?.resolve(result);
  }

  // ---------- adding a spot, placing a camera ----------
  let adding = null;
  function startAdd(what) {
    adding = what; picked = null;
    cross.hidden = false;
    if (what.row?.lat != null) map.easeTo({ center: [what.row.lon, what.row.lat], zoom: Math.max(map.getZoom(), 17) });
    const isCam = what.kind === "camera";
    const el = openCard(`
      <p class="label">${isCam ? `Place ${esc(what.camera)}` : what.row ? "Move Spot" : "New Spot"}</p>
      <p class="m-sub">Move the map until the cross is on the spot.</p>
      ${btnRow(me ? b("gps", "Use My GPS") : "", b("here", isCam ? "Place It Here" : what.row ? "Move It Here" : "Next"))}`, "m-adding");
    on(el, {
      gps: () => map.easeTo({ center: me, zoom: Math.max(map.getZoom(), 17) }),
      here: () => {
        const c = map.getCenter(), pos = { lat: +c.lat.toFixed(6), lon: +c.lng.toFixed(6) };
        cross.hidden = true;
        if (isCam) return placeCam(what, pos);
        if (what.row && !what.keepForm) return spotForm({ ...what.row, ...pos });
        if (what.row) return saveSpot({ ...what.row, ...pos }).then(ok => ok && (closeCard(), draw(), pick({ type: "spot", id: what.row.id })));
        spotForm({ id: crypto.randomUUID(), property: prop(), kind: "stand", label: "", notes: "", ...pos, isNew: true });
      },
    });
  }
  function addMenu() {
    const loose = canEdit() ? unplaced() : [];
    const el = openCard(`
      <p class="label">Add to the Map</p>
      ${btnRow(b("spot", "Add a Spot"))}
      ${loose.length ? `<p class="label">Cameras With No GPS</p><div class="chips">${loose.map(n => `<button type="button" data-cam="${esc(n)}">${esc(n)}</button>`).join("")}</div><p class="m-sub">Tap one to place it.</p>` : ""}`, "m-menu");
    on(el, { spot: () => startAdd({ kind: "spot" }) });
    el.querySelectorAll("[data-cam]").forEach(x => x.addEventListener("click", () => startAdd({ kind: "camera", camera: x.dataset.cam })));
  }
  function spotForm(s) {
    adding = { kind: "form" };
    const el = openCard(`
      <p class="label">${s.isNew ? "New Spot" : "Edit Spot"}</p>
      <div class="chips m-kinds">${SPOT_KINDS.map(([k, l]) => `<button type="button" data-kind="${k}" aria-pressed="${k === s.kind}">${l}</button>`).join("")}</div>
      <input class="newname sitsmall" id="mSpotLabel" maxlength="40" placeholder="Name (optional): Ridge stand…" value="${esc(s.label || "")}">
      <textarea class="newname sitsmall" id="mSpotNotes" maxlength="500" rows="2" placeholder="Notes (optional)">${esc(s.notes || "")}</textarea>
      ${btnRow(!s.isNew ? b("delete", "Delete", "danger") : "", b("save", s.isNew ? "Save Spot" : "Save"))}`, "m-form");
    let kind = s.kind;
    el.querySelectorAll("[data-kind]").forEach(x => x.addEventListener("click", () => {
      kind = x.dataset.kind; el.querySelectorAll("[data-kind]").forEach(y => y.setAttribute("aria-pressed", String(y === x)));
    }));
    on(el, {
      save: async () => {
        const row = { id: s.id, property: s.property, kind, label: $("mSpotLabel").value.trim() || null, notes: $("mSpotNotes").value.trim() || null, lat: s.lat, lon: s.lon };
        if (await saveSpot(row)) { closeCard(); draw(); toast(s.isNew ? "Spot saved" : "Saved"); }
      },
      delete: () => {
        const box = el.querySelector(".m-btns");
        box.innerHTML = `<span class="m-ask">Delete this spot for everyone?</span>${b("keep", "Keep It")}${b("gone", "Delete", "danger")}`;
        on(box, { keep: () => spotForm(s), gone: async () => { const err = await removeRow("deleteSpot", s.id); if (err) return toast(friendly(err)); delete state.spots[s.id]; closeCard(); draw(); toast("Spot deleted"); } });
      },
    });
  }
  async function saveSpot(row) {
    const local = { ...(state.spots?.[row.id] || { created_by: state.myUid, created_by_name: state.crewById?.[state.myUid] || null, created_at: new Date().toISOString() }), ...row };
    state.spots ||= {};
    if (mustQueue()) { queueOp({ kind: "spot", row }); state.spots[row.id] = local; return true; }
    const { data, error } = await sb.from("spots").upsert(row).select().single();
    if (error && netError(error)) { queueOp({ kind: "spot", row }); state.spots[row.id] = local; return true; }
    if (error) { toast(friendly(error)); return false; }
    state.spots[row.id] = data;
    return true;
  }
  async function placeCam(what, pos) {
    const old = (state.cameraSpots || []).find(c => c.camera === what.camera && c.lat == null);
    const row = { id: what.row?.source === "placed" ? what.row.id : "placed:" + crypto.randomUUID(), camera: what.camera, property: prop(),
      lat: pos.lat, lon: pos.lon, first_at: what.row?.first_at || null, last_at: new Date().toISOString(), photos: old?.photos ?? what.row?.photos ?? null };
    const local = { ...row, source: "placed", placed_by: state.myUid, placed_by_name: state.crewById?.[state.myUid] || null };
    const keep = () => { state.cameraSpots = [...(state.cameraSpots || []).filter(c => c.id !== row.id), local]; };
    if (mustQueue()) { queueOp({ kind: "camSpot", row }); keep(); }
    else {
      const { error } = await sb.from("camera_spots").upsert(row);
      if (error && !netError(error)) return toast(friendly(error));
      if (error) queueOp({ kind: "camSpot", row });
      keep();
    }
    closeCard(); draw(); toast(`${what.camera} placed`);
  }
  async function removeCam(id) {
    const err = await removeRow("deleteCamSpot", id);
    if (err) return toast(friendly(err));
    state.cameraSpots = (state.cameraSpots || []).filter(c => c.id !== id);
  }

  // ---------- layers and the offline download ----------
  const DL = "buckbook-map-saved";            // { [property]: { at, bytes, tiles } }
  function layersCard() {
    const saved = store.get(DL) || {};
    const here = saved[prop()];
    const est = tileList(prop());
    const el = openCard(`
      <p class="label">Map</p>
      <div class="m-bases">${BASES.map(id => `<button type="button" data-base="${id}" aria-pressed="${prefs.base === id}"><b>${LAYERS[id].name}</b><small>${LAYERS[id].note}</small></button>`).join("")}</div>
      <p class="label">Show</p>
      <div class="chips m-show">
        <button type="button" data-show="contours" aria-pressed="${prefs.contours}">Contours</button>
        ${[["parcels", "Parcels"], ["cameras", "Cameras"], ["spots", "Spots"], ["trees", "Sits"]].map(([k, l]) => `<button type="button" data-show="${k}" aria-pressed="${!!prefs.show[k]}">${l}</button>`).join("")}
      </div>
      <p class="label">Offline</p>
      <div class="m-dl">
        <p class="m-sub" id="mDlNote">${here ? `${esc(prop())} saved ${fmtDay(new Date(here.at).toISOString())} · ${(here.bytes / 1e6).toFixed(0)} MB. Works with no signal.` : `Save ${esc(prop())} on this phone for no signal: about ${Math.max(1, Math.round(est.reduce((n, t) => n + (LAYERS[t[0]].px ? 0.07 : 0.015), 0)))} MB. The leaf-off photos come slowly, so give it 10 to 20 minutes on Wi-Fi with the app open.`}</p>
        <div class="m-bar" hidden><i></i></div>
        ${btnRow(b("download", here ? "Update" : "Download Map"), here ? b("forget", "Remove", "danger") : "")}
      </div>`, "m-layers");
    el.querySelectorAll("[data-base]").forEach(x => x.addEventListener("click", () => { prefs.base = x.dataset.base; savePrefs(); applyLayers(); layersCard(); }));
    el.querySelectorAll("[data-show]").forEach(x => x.addEventListener("click", () => {
      const k = x.dataset.show;
      if (k === "contours") prefs.contours = !prefs.contours; else prefs.show[k] = !prefs.show[k];
      savePrefs(); applyLayers(); draw(); layersCard();
    }));
    on(el, { download: () => download(prop()), forget: () => forget(prop()) });
    if (dl) showProgress();
  }
  // Every tile a property needs: each layer at the zooms it keeps, over the property's map box.
  function tileList(p) {
    const box = boxOf(p);
    if (!box) return [];
    const [[w, s], [e, n]] = box, out = [];
    const tx = (lon, z) => Math.floor((lon + 180) / 360 * 2 ** z);
    const ty = (lat, z) => Math.floor((1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * 2 ** z);
    for (const [id, L] of Object.entries(LAYERS)) for (let z = L.save[0]; z <= L.save[1]; z++)
      for (let x = tx(w, z); x <= tx(e, z); x++) for (let y = ty(n, z); y <= ty(s, z); y++) out.push([id, z, x, y]);
    return out;
  }
  let dl = null;                               // the download running now
  function showProgress() {
    const bar = body.querySelector(".m-bar"), note = body.querySelector("#mDlNote");
    if (!bar || !dl) return;
    bar.hidden = false; bar.firstElementChild.style.width = (dl.done / dl.total * 100).toFixed(1) + "%";
    note.textContent = dl.finished ? dl.message : `Saving ${dl.prop}: ${dl.done.toLocaleString()} of ${dl.total.toLocaleString()} · ${(dl.bytes / 1e6).toFixed(1)} MB${dl.failed ? ` · ${dl.failed} to retry` : ""}`;
    const go = body.querySelector('[data-act="download"]');
    if (go) { go.disabled = !dl.finished; go.textContent = dl.finished ? "Update" : "Saving…"; }
  }
  async function download(p) {
    if (dl && !dl.finished) return;
    if (!navigator.onLine) return toast("Downloading the map needs signal.");
    navigator.storage?.persist?.().catch(() => {});
    const list = tileList(p), c = await tiles();
    dl = { prop: p, total: list.length, done: 0, bytes: 0, failed: 0 };
    showProgress();
    let next = 0;
    const misses = [];
    async function worker() {
      while (next < list.length) {
        const t = list[next++];
        try {
          // Size first, then add: "dl.bytes += await …" would read the total before the wait and lose the
          // other workers' additions.
          const hit = await c.match(tileKey(...t));
          const n = hit ? (await hit.arrayBuffer()).byteLength : (await getTile(...t)).byteLength;
          dl.bytes += n;
        } catch { misses.push(t); dl.failed++; }
        dl.done++;
        showProgress();
      }
    }
    await Promise.all(Array.from({ length: 6 }, worker));
    // The modeled wind for this property, so it works with no signal too.
    try {
      const idx = await windFile(p, "index.json");
      for (const f of ["grid.json", ...idx.runs.map(r => r.file)]) { const t = await windFile(p, f, true); dl.bytes += t.length; }
    } catch {}
    // One more try for the ones that didn't come back; the state's server drops a few under load.
    dl.failed = 0;
    for (const t of misses) { try { const n = (await getTile(...t)).byteLength; dl.bytes += n; } catch { dl.failed++; } }
    const saved = store.get(DL) || {};
    saved[p] = { at: Date.now(), bytes: dl.bytes, tiles: list.length - dl.failed };
    store.set(DL, saved);
    dl.finished = true;
    dl.message = dl.failed ? `${p} saved, except ${dl.failed} pieces that didn't come back. Tap Update later to fill them in.` : `${p} saved: ${(dl.bytes / 1e6).toFixed(0)} MB. Works with no signal.`;
    showProgress();
    toast(dl.failed ? `${p} map saved, with a few gaps` : `${p} map saved for no signal`);
  }
  async function forget(p) {
    const c = await tiles(), list = tileList(p);
    await Promise.all(list.map(t => c.delete(tileKey(...t))));
    const saved = store.get(DL) || {}; delete saved[p]; store.set(DL, saved);
    toast(`${p} map removed from this phone`); layersCard();
  }

  // ---------- modeled wind (WindNinja runs, buckbook/wind_model.py) ----------
  // Each property has a grid (cell positions every 40 m, canopy cover) and runs for a wind direction and speed,
  // in the private photos bucket under wind/<property>/. Shown: the run nearest the wind you pick, else the
  // wind lens direction, else the wind now at the property's weather town. WindNinja's wind is 20 ft above
  // the vegetation; ground level brings it to 5 ft with the same canopy sheltering as wind_model.py.
  const mw = { on: !!prefs.mwind, height: prefs.mwHeight || "ground", leafOff: prefs.mwLeafOff ?? [10, 11, 0, 1, 2, 3].includes(new Date().getMonth()),
    pick: prefs.mwPick || null, shown: null, cells: null, readout: "" };
  const windSlug = p => p.toLowerCase().replace(/\s+/g, "");
  const windKey = (p, f) => `https://tiles.buckbook.invalid/wind/${windSlug(p)}/${f}`;
  // Runs never change once made, so they come from the phone's copy; the index lists which runs exist and
  // grows as we model more, so with signal it's fetched fresh once per session.
  const freshIndex = new Set();
  async function windFile(p, f, raw = false) {
    const c = await tiles(), fresh = f === "index.json" && navigator.onLine && !freshIndex.has(p);
    const hit = fresh ? null : await c.match(windKey(p, f));
    let text = hit ? await hit.text() : null;
    if (fresh) {
      try {
        const { data, error } = await sb.storage.from("photos").download(`wind/${windSlug(p)}/${f}`);
        if (error) throw error;
        text = await data.text(); freshIndex.add(p);
        c.put(windKey(p, f), new Response(text, { headers: { "content-type": "application/json" } })).catch(() => {});
      } catch { const old = await c.match(windKey(p, f)); text = old ? await old.text() : null; }
    }
    if (text == null) {
      const { data, error } = await sb.storage.from("photos").download(`wind/${windSlug(p)}/${f}`);
      if (error) throw error;
      text = await data.text();
      c.put(windKey(p, f), new Response(text, { headers: { "content-type": "application/json" } })).catch(() => {});
    }
    return raw ? text : JSON.parse(text);
  }
  const bytes = (b64, T) => { const s = atob(b64), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return new T(u.buffer); };
  const OPEN = Math.log(1.52 / .03) / Math.log(6.1 / .03);
  function standFactor(cc, leafOff) {
    const sheltered = c => Math.min(.555 / (Math.sqrt(Math.max(c / 100 * .5 / 3 * (leafOff ? .35 : 1), 1e-6) * 65) * Math.log((20 + .36 * 65) / (.13 * 65))), OPEN);
    const w = Math.min(1, Math.max(0, (cc - 5) / 20));
    return (1 - w) * OPEN + w * sheltered(Math.max(cc, 25));
  }
  // The forecast wind at the property's weather town for a day and time (local), from the same service sits use.
  async function forecastAt(p, day, time) {
    const town = state.properties?.[p];
    if (!town?.weather_lat) throw new Error("No weather town set for " + p);
    const q = new URLSearchParams({ latitude: town.weather_lat, longitude: town.weather_lon, hourly: "wind_direction_10m,wind_speed_10m",
      wind_speed_unit: "mph", timezone: "auto", forecast_days: 7 });
    const h = (await (await fetch("https://api.open-meteo.com/v1/forecast?" + q)).json()).hourly;
    const want = new Date(`${day}T${time}`).getTime();
    let i = 0;
    h.time.forEach((t, j) => { if (Math.abs(new Date(t).getTime() - want) < Math.abs(new Date(h.time[i]).getTime() - want)) i = j; });
    return { dir: WIND16[Math.round(h.wind_direction_10m[i] / 22.5) % 16], mph: Math.round(h.wind_speed_10m[i]) };
  }
  async function mwShow() {
    const p = prop(), pill = ui.querySelector(".m-wpill");
    if (!mw.on) { pill.hidden = true; if (ready) map.getSource("mwind").setData(fc([])); if (lens) { lens = null; draw(); } return; }
    pill.hidden = false;
    let idx;
    try { idx = await windFile(p, "index.json"); }
    catch { mw.shown = null; map.getSource("mwind")?.setData(fc([])); pill.textContent = `No modeled wind for ${p} on this phone yet`; return; }
    const want = mw.pick;
    if (!want) {
      mw.shown = null; map.getSource("mwind")?.setData(fc([]));
      if (lens) { lens = null; draw(); }
      pill.innerHTML = "<b>Tap to pick a wind</b>";
      return;
    }
    // The trees sat in this wind light up with it, as the wind lens did.
    if (lens?.dir !== want.dir) { lens = { dir: want.dir }; draw(); }
    const same = idx.runs.filter(r => r.dir === want.dir);
    if (!same.length) {
      mw.shown = null; map.getSource("mwind")?.setData(fc([]));
      pill.innerHTML = `Nothing here yet for a ${esc(want.dir)} wind (have ${esc([...new Set(idx.runs.map(r => r.dir))].join(", "))})<br><b>Tap to pick another</b>`;
      return;
    }
    const run = same.reduce((a, b) => Math.abs(b.mph - want.mph) < Math.abs(a.mph - want.mph) ? b : a);
    const [grid, r] = await Promise.all([windFile(p, "grid.json"), windFile(p, run.file)]);
    const dlon = bytes(grid.dlon, Int32Array), dlat = bytes(grid.dlat, Int32Array), cc = bytes(grid.canopy, Uint8Array);
    const sp = bytes(r.speed, Uint8Array), fr = bytes(r.from, Uint8Array);
    const cells = [];
    for (let i = 0; i < dlon.length; i++) {
      const above = sp[i] / 5, from = fr[i] / 256 * 360;
      cells.push({ lon: grid.origin[0] + dlon[i] / 1e6, lat: grid.origin[1] + dlat[i] / 1e6, row: Math.floor(i / grid.cols), col: i % grid.cols,
        above, ground: above * standFactor(cc[i], mw.leafOff), from, canopy: cc[i] });
    }
    mw.cells = cells; mw.shown = { ...run, want };
    const feats = [];
    const arrow = (c, len, lvl) => {
      const t = (c.from + 180) * Math.PI / 180, k = 1 / (111320 * Math.cos(c.lat * Math.PI / 180));
      const ex = Math.sin(t), ey = Math.cos(t);
      const tail = [c.lon - ex * len / 2 * k, c.lat - ey * len / 2 / 111320], tip = [c.lon + ex * len / 2 * k, c.lat + ey * len / 2 / 111320];
      const barb = side => { const a = t + Math.PI + side * .49; return [tip, [tip[0] + Math.sin(a) * len * .32 * k, tip[1] + Math.cos(a) * len * .32 / 111320]]; };
      feats.push({ type: "Feature", properties: { lvl, v: +(mw.height === "ground" ? c.ground : c.above).toFixed(1) },
        geometry: { type: "MultiLineString", coordinates: [[tail, tip], barb(-1), barb(1)] } });
    };
    cells.forEach(c => {
      arrow(c, 32, 0);
      if (c.row % 2 === 0 && c.col % 2 === 0) arrow(c, 64, 1);
      if (c.row % 4 === 0 && c.col % 4 === 0) arrow(c, 120, 2);
    });
    map.getSource("mwind")?.setData(fc(feats));
    drawLens(trees());                          // scent cones follow the modeled wind at each tree
    mwPill();
  }
  function mwPill() {
    const pill = ui.querySelector(".m-wpill"), s = mw.shown;
    if (!s) return;
    const why = s.want.label ? ` (${esc(s.want.label)})` : "";
    pill.innerHTML = `<b>Modeled ${esc(s.dir)} ${s.mph} mph</b>${why} · ${mw.height === "ground" ? "ground level" : "above canopy"}` + (mw.readout ? `<br>${mw.readout}` : "");
  }
  // A small marker where you tapped, so it's clear which spot the reading is for.
  let mwPin = null;
  function mwPinAt(ll) {
    if (!ll) { mwPin?.remove(); mwPin = null; return; }
    if (!mwPin) { const el = document.createElement("div"); el.className = "m-wpin"; mwPin = new maplibregl.Marker({ element: el, anchor: "center" }); }
    mwPin.setLngLat(ll).addTo(map);
  }
  function mwReadout(ll) {
    if (!mw.cells) return;
    let best = null, bd = Infinity;
    const k = Math.cos(ll.lat * Math.PI / 180);
    for (const c of mw.cells) { const d = (c.lon - ll.lng) ** 2 * k * k + (c.lat - ll.lat) ** 2; if (d < bd) { bd = d; best = c; } }
    if (!best || Math.sqrt(bd) * 111320 > 60) { mw.readout = ""; mwPinAt(null); return mwPill(); }
    mwPinAt([ll.lng, ll.lat]);
    const from = WIND16[Math.round(best.from / 22.5) % 16];
    mw.readout = `At the pin: <b>${best.ground.toFixed(1)} mph</b> ground level · ${best.above.toFixed(1)} above canopy · from ${from} · ${best.canopy}% canopy`;
    mwPill();
  }
  function mwToggle() { parcelOff(); mw.on = !mw.on; prefs.mwind = mw.on; savePrefs(); mw.readout = ""; mwPinAt(null); return mwShow(); }
  // The wind tool. First the dial and a speed, then Apply: the run nearest that wind goes on the map (or "nothing
  // here yet"). Or Use Local Weather: pick a day and the time you'll walk in, and the forecast wind for that hour
  // is applied. Below: how the arrows are drawn, our sits on days with that wind, and the model check.
  let mwDraft = null;                          // the dial and slider before Apply
  async function mwCard() {
    let idx = null;
    try { idx = await windFile(prop(), "index.json"); } catch {}
    const dirs = idx ? [...new Set(idx.runs.map(r => r.dir))] : [];
    const applied = mw.pick, s = mw.shown;
    mwDraft ||= { dir: applied?.dir || "S", mph: applied?.mph ?? 10 };
    const speeds = d => idx ? idx.runs.filter(r => r.dir === d).map(r => r.mph).sort((a, b) => a - b) : [];
    const nearest = (d, v) => speeds(d).reduce((a, b) => Math.abs(b - v) < Math.abs(a - v) ? b : a, speeds(d)[0]);
    const showing = !applied ? "Nothing applied yet."
      : !idx ? "No modeled wind on this phone yet; it needs signal the first time."
      : s ? `Showing ${esc(s.dir)} ${s.mph} mph${s.mph !== applied.mph ? ` (closest to ${applied.mph})` : ""}${applied.label ? `, ${esc(applied.label)}` : ""}.`
      : `Nothing here yet for ${applied.label ? `the ${esc(applied.label)} wind, ${esc(applied.dir)} ${applied.mph} mph` : `a ${esc(applied.dir)} wind`}. Runs so far: ${esc(dirs.join(", ") || "none")}.`;
    const days = Array.from({ length: 5 }, (_, i) => { const d = new Date(); d.setDate(d.getDate() + i);
      return [localDate(d), i === 0 ? "Today" : i === 1 ? "Tomorrow" : d.toLocaleDateString("en-US", { weekday: "short" })]; });
    const el = openCard(`
      <p class="label">Wind</p>
      <p class="m-sub m-showing${applied && !s ? " m-none" : ""}">${showing}</p>
      <div id="mwDial"></div>
      <label class="m-speed"><span>Speed <b id="mwMph">${mwDraft.mph}</b> mph</span><input type="range" id="mwRange" min="0" max="25" step="1" value="${mwDraft.mph}"></label>
      <p class="m-sub" id="mwWill"></p>
      ${btnRow(b("apply", "Apply"))}
      <button type="button" class="btn ghost m-localbtn" data-act="local">Use Local Weather</button>
      <div class="m-local" hidden>
        <p class="label">When you'll walk in</p>
        <div class="chips m-kinds" id="mwDays">${days.map(([v, l], i) => `<button type="button" data-day="${v}" aria-pressed="${i === 0}">${l}</button>`).join("")}</div>
        <div class="m-when"><input type="hidden" id="mwTime" data-wheel="required"></div>
        ${btnRow(b("forecast", "Apply Forecast Wind"))}
        <p class="m-sub" id="mwFc"></p>
      </div>
      <p class="label">Arrows</p>
      <div class="chips m-kinds"><button type="button" data-h="ground" aria-pressed="${mw.height === "ground"}">Ground Level</button><button type="button" data-h="above" aria-pressed="${mw.height === "above"}">Above Canopy</button></div>
      <div class="chips m-kinds" style="margin-top:6px"><button type="button" data-leaf="on" aria-pressed="${!mw.leafOff}">Leaves On</button><button type="button" data-leaf="off" aria-pressed="${mw.leafOff}">Leaves Off</button></div>
      <div class="m-legend"><i></i><span>0</span><span>22+ mph</span></div>
      <div id="mRank"></div>
      ${btnRow(b("off", "Turn Off"))}`, "m-mwind");
    const will = () => { el.querySelector("#mwWill").innerHTML = !idx ? "" : speeds(mwDraft.dir).length
      ? `Apply shows the ${esc(mwDraft.dir)} ${nearest(mwDraft.dir, mwDraft.mph)} mph run.` : `Nothing here yet for a ${esc(mwDraft.dir)} wind.`; };
    const apply = w => { mw.pick = w; prefs.mwPick = w; savePrefs(); mwDraft = { dir: w.dir, mph: w.mph }; mw.readout = ""; mwPinAt(null); mwShow().then(() => mwCard()); };
    windClock(el.querySelector("#mwDial"), mwDraft.dir, d => { if (!d) return; mwDraft.dir = d; mwCard(); }, { variable: false, clearable: false });
    const range = el.querySelector("#mwRange");
    range.addEventListener("input", () => { mwDraft.mph = +range.value; el.querySelector("#mwMph").textContent = range.value; will(); });
    will();
    // Local weather: a day and the time you'll walk in (the same time wheel as a sit).
    const t = el.querySelector("#mwTime"), soon = new Date(Date.now() + 30 * 60e3);
    soon.setMinutes(soon.getMinutes() < 30 ? 0 : 30);
    t.value = localTime(soon);
    timeWheel(t);
    let day = days[0][0];
    el.querySelectorAll("[data-day]").forEach(x => x.addEventListener("click", () => {
      day = x.dataset.day; el.querySelectorAll("[data-day]").forEach(y => y.setAttribute("aria-pressed", String(y === x)));
    }));
    el.querySelectorAll("[data-h]").forEach(x => x.addEventListener("click", () => { mw.height = x.dataset.h; prefs.mwHeight = mw.height; savePrefs(); mwShow().then(() => mwCard()); }));
    el.querySelectorAll("[data-leaf]").forEach(x => x.addEventListener("click", () => { mw.leafOff = x.dataset.leaf === "off"; prefs.mwLeafOff = mw.leafOff; savePrefs(); mwShow().then(() => mwCard()); }));
    on(el, {
      apply: () => apply({ dir: mwDraft.dir, mph: mwDraft.mph }),
      local: () => { el.querySelector(".m-local").hidden = !el.querySelector(".m-local").hidden; },
      forecast: async () => {
        const out = el.querySelector("#mwFc");
        if (!navigator.onLine) return out.textContent = "The forecast needs signal. Pick the wind on the dial instead.";
        out.textContent = "Looking up the forecast…";
        try {
          const w = await forecastAt(prop(), day, t.value);
          const when = `${days.find(d => d[0] === day)[1]} ${fmtWhen(new Date(`${day}T${t.value}`).toISOString(), false)}`;
          apply({ ...w, label: `forecast ${when}` });
        } catch (e) { out.textContent = `Couldn't get the forecast (${e.message}).`; }
      },
      off: () => { mwToggle(); closeCard(); },
    });
    // What our sits say about this wind: trees sat on days with it, and how often the model matched what we felt.
    const dir = applied?.dir || mwDraft.dir, ts = trees();
    const ranked = ts.map(t => ({ t, hits: t.sits.filter(x => sitMatches(x, dir)) })).filter(r => r.hits.length)
      .map(r => ({ ...r, k: tally(r.hits) })).sort((a, b) => b.hits.length - a.hits.length || b.k.deer - a.k.deer || a.k.bad - b.k.bad);
    const cams = state.photosLoaded ? cameras().map(c => {
      const list = ALL_CARDS.filter(x => x.cam === c.camera && x.wind);
      return { name: c.camera, n: list.filter(x => near16(String(x.wind).split(/\s+/)[0].toUpperCase(), dir)).length, of: list.length };
    }).filter(c => c.of).sort((a, b) => b.n - a.n) : null;
    // Sits are matched on the day's prevailing wind, whatever we felt at the tree.
    const camLine = cams?.filter(c => c.n).slice(0, 6).map(c => `${esc(c.name)} ${c.n}/${c.of}`).join(" · ");
    el.querySelector("#mRank").innerHTML = (ranked.length ? `
      <p class="label">Our sits on ${esc(dir)}-ish days</p>
      <ul class="m-list m-sits">${ranked.map(({ t, hits, k }) => `<li><button type="button" class="m-sit" data-tree="${t.id}"><b>${esc(t.name)}</b>
        <span>${hits.length} sit${hits.length === 1 ? "" : "s"} · ${k.deer} deer · ${k.bucks} buck${k.bucks === 1 ? "" : "s"}</span>
        <small>${k.bad ? `${k.bad} busted/winded` : "Never busted"}</small></button></li>`).join("")}</ul>` : "") +
      `<p class="m-sub" id="mCheck"></p>` +
      (camLine ? `<p class="label">Buck photos in this wind</p><p class="m-sub">${camLine}</p>` : "");
    el.querySelectorAll("[data-tree]").forEach(x => x.addEventListener("click", () => {
      const t = ts.find(y => y.id === x.dataset.tree);
      map.easeTo({ center: [t.lon, t.lat], zoom: Math.max(map.getZoom(), 16) });
      pick({ type: "tree", id: t.id });
    }));
    modelCheck(prop()).then(c => {
      const box = el.querySelector("#mCheck");
      if (!box) return;
      if (!c.compared) return;
      box.innerHTML = `<b>Model check:</b> matched the wind we felt on ${c.matched} of ${c.compared} sit${c.compared === 1 ? "" : "s"}.`;
    });
  }

  // Did the model get it right? For a sit with the wind we felt and the weather service's wind that hour, take
  // the run nearest that day's wind and read its direction at the tree. A match is within one compass point.
  const checked = {};
  async function modelAtSit(sit) {
    if (sit.id in checked) return checked[sit.id];
    const felt = sit.wind_dir && sit.wind_dir !== "variable" ? sit.wind_dir : null;
    const hours = (state.sitWeather?.[sit.id] || []).filter(h => h.wind_from_deg != null);
    if (!felt || sit.lat == null || !hours.length) return checked[sit.id] = null;
    const t = new Date(sit.set_at).getTime() + 3600e3;          // an hour in: settled in, wind as felt
    const h = hours.reduce((a, b) => Math.abs(new Date(b.hour) - t) < Math.abs(new Date(a.hour) - t) ? b : a);
    const day = { dir: WIND16[Math.round(h.wind_from_deg / 22.5) % 16], mph: Math.round(h.wind_mph) };
    let idx;
    try { idx = await windFile(sit.property, "index.json"); } catch { return checked[sit.id] = null; }
    const same = idx.runs.filter(r => r.dir === day.dir);
    if (!same.length) return checked[sit.id] = { day, modeled: false };
    const run = same.reduce((a, b) => Math.abs(b.mph - day.mph) < Math.abs(a.mph - day.mph) ? b : a);
    const [grid, r] = await Promise.all([windFile(sit.property, "grid.json"), windFile(sit.property, run.file)]);
    const dlon = bytes(grid.dlon, Int32Array), dlat = bytes(grid.dlat, Int32Array), fr = bytes(r.from, Uint8Array), sp = bytes(r.speed, Uint8Array), cc = bytes(grid.canopy, Uint8Array);
    const k = Math.cos(sit.lat * Math.PI / 180);
    let best = 0, bd = Infinity;
    for (let i = 0; i < dlon.length; i++) {
      const d = (grid.origin[0] + dlon[i] / 1e6 - sit.lon) ** 2 * k * k + (grid.origin[1] + dlat[i] / 1e6 - sit.lat) ** 2;
      if (d < bd) { bd = d; best = i; }
    }
    const model = WIND16[Math.round(fr[best] / 256 * 16) % 16];
    return checked[sit.id] = { day, modeled: true, run: `${run.dir} ${run.mph}`, model, felt, match: near16(model, felt),
      ground: +(sp[best] / 5 * standFactor(cc[best], [10, 11, 0, 1, 2, 3].includes(new Date(sit.set_at).getMonth()))).toFixed(1) };
  }
  async function modelCheck(p) {
    const out = { compared: 0, matched: 0, skipped: 0 };
    for (const sit of Object.values(state.sits || {}).filter(x => x.property === p)) {
      const c = await modelAtSit(sit);
      if (!c) continue;
      if (!c.modeled) { out.skipped++; continue; }
      out.compared++; if (c.match) out.matched++;
    }
    return out;
  }
  ui.querySelector(".m-wpill").addEventListener("click", () => mwCard());

  // ---------- wind lens and planning ----------
  // The modeled wind's direction at a tree (degrees it comes from), when a run is showing.
  function treeWind(t) {
    if (!mw.cells) return null;
    const k = Math.cos(t.lat * Math.PI / 180);
    let best = null, bd = Infinity;
    for (const c of mw.cells) { const d = (c.lon - t.lon) ** 2 * k * k + (c.lat - t.lat) ** 2; if (d < bd) { bd = d; best = c; } }
    return best && Math.sqrt(bd) * 111320 < 60 ? best.from : null;
  }
  function drawLens(ts) {
    if (!lens) { map.getSource("cones").setData(fc([])); map.getSource("paths").setData(fc([])); return; }
    const deg = DEG(lens.dir);
    const cones = [], paths = [];
    ts.forEach(t => {
      const hits = t.sits.filter(s => sitMatches(s, lens.dir));
      if (!hits.length) return;
      const at = [t.lon, t.lat], down = (treeWind(t) ?? deg) + 180;   // scent drifts away from where the wind comes from
      cones.push({ type: "Feature", properties: {}, geometry: { type: "Polygon",
        coordinates: [[at, ...[-20, -10, 0, 10, 20].map(a => offset(at, down + a, a === 0 ? 150 : 140)), at]] } });
      hits.forEach(s => eventsOf(s.id).filter(e => e.kind === "deer" && (e.from_dir || e.to_dir)).forEach(e => {
        const d = Math.max(30, Math.min(250, (e.distance_yd || 60) / 1.0936));
        const from = e.from_dir ? offset(at, DEG(e.from_dir) || 0, d * 1.6) : at;
        const to = e.to_dir ? offset(at, DEG(e.to_dir) || 0, d * 1.6) : at;
        const bad = ["busted", "winded"].includes(e.ended_how);
        paths.push({ type: "Feature", properties: { bad }, geometry: { type: "LineString", coordinates: [from, to] } });
        paths.push({ type: "Feature", properties: { bad }, geometry: { type: "Point", coordinates: to } });
      }));
    });
    map.getSource("cones").setData(fc(cones));
    map.getSource("paths").setData(fc(paths));
  }

  // ---------- where you are ----------
  function locate(center) {
    if (!navigator.geolocation) return toast("This phone won't share its location.");
    if (center && me) map.easeTo({ center: me, zoom: Math.max(map.getZoom(), 16) });
    if (watch != null) return;
    let first = true;
    watch = navigator.geolocation.watchPosition(pos => {
      me = [pos.coords.longitude, pos.coords.latitude];
      if (!meMarker) meMarker = new maplibregl.Marker({ element: meEl(), anchor: "center" }).setLngLat(me).addTo(map);
      else meMarker.setLngLat(me);
      if (first && center) map.easeTo({ center: me, zoom: Math.max(map.getZoom(), 16) });
      first = false;
    }, err => { if (center) toast(err.code === 1 ? "Location is off for this site. Allow it in Settings." : "No GPS fix yet."); stopLocate(); },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 30000 });
  }
  function stopLocate() { if (watch != null) navigator.geolocation.clearWatch(watch); watch = null; }

  on(ui.querySelector(".m-tools"), {
    layers: () => card.hidden || !card.classList.contains("m-layers") ? layersCard() : closeCard(),
    // Turning the wind on loads its run first, so the card says what's showing.
    wind: () => { if (!mw.on) return mwToggle().then(() => mwCard()); if (!card.hidden && card.classList.contains("m-mwind")) return closeCard(); mwCard(); },
    locate: () => locate(true),
    add: () => { const open = !card.hidden && card.classList.contains("m-menu"); closeCard(); if (!open) addMenu(); },
  });

  // ---------- the page talks to the map through these ----------
  window.BBMap = {
    map,                                      // for poking at in the browser console
    show() {
      requestAnimationFrame(() => map.resize());
      if (prop() !== shownProp) { shownProp = prop(); parcelOff(); mw.readout = ""; mwPinAt(null); if (mw.on) mwShow(); if (!picking) closeCard(); const bx = boxOf(prop()); if (bx) map.fitBounds(bx, { padding: 20, duration: 0, bearing: squareBearing() }); }
      draw();
      if (window.mapFocus) { const f = window.mapFocus; window.mapFocus = null; map.jumpTo({ center: [f.lon, f.lat], zoom: Math.max(map.getZoom(), 17) }); }
      // GPS only while the map is open, so it doesn't drain the phone; quietly, without moving the map.
      if (navigator.permissions?.query) navigator.permissions.query({ name: "geolocation" }).then(r => { if (r.state === "granted") locate(false); }).catch(() => {});
    },
    hide() { stopLocate(); if (picking) endPick(null); },
    // Where was a sit? Resolves to { lat, lon, label? }, or null if cancelled (index.html's Mark on Map).
    pick(opts = {}) {
      return new Promise(resolve => {
        picking?.resolve(null);
        closeCard();
        picking = { resolve, target: null };
        view.classList.add("m-picking"); cross.hidden = false;
        if (opts.at) map.jumpTo({ center: [opts.at.lon, opts.at.lat], zoom: Math.max(map.getZoom(), 17) });
        pickCard();
      });
    },
    refresh() {
      if (prop() !== shownProp) return this.show();
      if (adding) return;                     // don't redraw under someone placing a spot
      draw();
    },
  };
  window.BBMap.show();
})();
