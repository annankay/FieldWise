/* FieldWise service worker: the app opens with weak or no signal and shows the last results viewed. */
const VERSION = "fieldwise-v2";
const SHELL = ["/", "/static/styles.css", "/static/app.js", "/static/i18n.js", "/static/vendor/chart.umd.js",
  "/static/vendor/leaflet/leaflet.js", "/static/vendor/leaflet/leaflet.css", "/static/icons/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;                 // map tiles etc. go straight to the network
  if (url.pathname.startsWith("/api/")) {
    if (e.request.method !== "GET") return;                    // POSTs (rotations) need the server
    // network first, fall back to the last copy (profile, crops) when offline
    e.respondWith(fetch(e.request).then((r) => { const copy = r.clone(); if (r.ok) caches.open(VERSION).then((c) => c.put(e.request, copy)); return r; })
      .catch(() => caches.match(e.request)));
    return;
  }
  const save = (r) => { if (r.ok && e.request.method === "GET") { const copy = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, copy)); } return r; };
  if (url.pathname.startsWith("/static/vendor/") || url.pathname.startsWith("/static/icons/")) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then(save)));   // never change
    return;
  }
  // app code: newest version when online, cached copy when offline
  e.respondWith(fetch(e.request).then(save).catch(() => caches.match(e.request).then((hit) => hit || caches.match("/"))));
});

