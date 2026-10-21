// Buck Book offline: keep the app itself on the phone so it opens with no signal.
// The page and config are fetched fresh whenever there's signal (so updates arrive) and come from this
// cache when there isn't. Libraries, fonts and icons are cached once. Crew data and photos (Supabase) and
// weather lookups are never cached here; the page keeps its own small copy of what Sits needs.
const CACHE = "buckbook-v1";
const SHELL = [
  "./", "index.html", "config.js", "manifest.webmanifest", "icon-192.png", "icon-512.png", "apple-touch-icon.png",
  "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.0/dist/umd/supabase.js",
  "https://cdn.jsdelivr.net/npm/mgrs@2.1.0/dist/mgrs.js",
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  if (url.hostname.endsWith("supabase.co") || url.hostname.endsWith("open-meteo.com")) return;   // data stays live
  const ours = url.origin === self.location.origin;
  // The page itself and its config: network first, the saved copy when offline.
  if (req.mode === "navigate" || (ours && /(\/|index\.html|config\.js)$/.test(url.pathname))) {
    const key = req.mode === "navigate" ? "index.html" : req;
    e.respondWith(fetch(req)
      .then(res => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(key, copy)); } return res; })
      .catch(() => caches.match(key).then(hit => hit || caches.match("index.html"))));
    return;
  }
  // Everything else we serve (libraries, fonts, icons): the saved copy first.
  e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
    if (res.ok || res.type === "opaque") { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
    return res;
  })));
});
