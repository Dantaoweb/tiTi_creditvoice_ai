/*
 * Minimal service worker for CreditVoice.
 *
 * Purpose: satisfy PWA installability (so Add-to-Home-Screen works) and give a
 * friendly offline page for navigations. It deliberately does NOT cache the app
 * bundle — that avoids serving a stale/broken JS build after a deploy. App
 * assets always go straight to the network.
 */
const CACHE = "cv-offline-v1";
const OFFLINE_URL = "/app/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.add(OFFLINE_URL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  // Only intervene for page navigations; everything else uses the network as
  // normal (no caching of JS/CSS/API responses).
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE_URL)));
});
