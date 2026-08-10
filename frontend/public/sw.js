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

// ── Web Push: show the notification on the phone ─────────────────────────────
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  const title = data.title || "CreditVoice";
  const options = {
    body: data.body || "",
    icon: "/app/pwa-192.png",
    badge: "/app/pwa-192.png",
    tag: data.tag || "cv-notify",
    data: { url: data.url || "/app" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// Tapping the notification focuses an open app window or opens one.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/app";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const c of clients) {
        if (c.url.includes("/app") && "focus" in c) return c.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
