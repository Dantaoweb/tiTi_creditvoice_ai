/*
 * Service worker for CreditVoice — makes the app open and work offline.
 *
 *   Pages (navigations)   network first; the last good copy of the app when
 *                         offline (never an old build while online).
 *   /app/assets/*         the build's files have unique names per build, so a
 *                         stored copy can never be a stale version: kept on
 *                         first use, served from the phone after.
 *   GET /app/api/*        network first; the last answer when offline, so
 *                         products, customers and debts still show. Cleared on
 *                         logout (message "cv-clear-api") so the next person on
 *                         the phone never sees them.
 *   Writes (POST…)        untouched — the app's offline queue handles them.
 */
const SHELL = "cv-shell-v4";
const ASSETS = "cv-assets-v4";
const API = "cv-api-v1";
const KEEP = [SHELL, ASSETS, API];
const OFFLINE_URL = "/app/offline.html";
const SHELL_URL = "/app/";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll([OFFLINE_URL, SHELL_URL]).catch(() => c.add(OFFLINE_URL))));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !KEEP.includes(k)).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "cv-clear-api") event.waitUntil(caches.delete(API));
});

function sameOrigin(url) { return url.origin === self.location.origin; }

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (!sameOrigin(url)) return;

  // The app's pages: network first, then the stored app, then the offline page
  if (req.mode === "navigate") {
    if (!url.pathname.startsWith("/app")) return;
    event.respondWith(
      fetch(req).then((res) => {
        if (res.ok) caches.open(SHELL).then((c) => c.put(SHELL_URL, res.clone()));
        return res;
      }).catch(() => caches.match(SHELL_URL).then((r) => r || caches.match(OFFLINE_URL)))
    );
    return;
  }

  // The build's own files: unique names, so a stored copy is always right
  if (url.pathname.startsWith("/app/assets/")) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(ASSETS).then((c) => c.put(req, copy)); }
        return res;
      }))
    );
    return;
  }

  // Data: the network first; the last answer when offline
  if (url.pathname.startsWith("/app/api/")) {
    event.respondWith(
      fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(API).then((c) => c.put(req, copy)); }
        return res;
      }).catch(() => caches.match(req).then((hit) => hit || Promise.reject(new TypeError("offline"))))
    );
  }
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
    // One tag per alert type: a low-stock alert no longer replaces an overdue-debt
    // one. renotify makes a repeat of the SAME type alert again (sound + vibration)
    // instead of swapping in silently.
    tag: data.tag || "cv-notify",
    renotify: true,
    vibrate: [200, 100, 200],   // noticeable in a noisy shop/market
    data: { url: data.url || "/app" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// Tapping the notification opens the page it's about (e.g. Payments to
// confirm) — in the app window that's already open, or a new one. The page
// still needs the person to be signed in.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/app";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const c of clients) {
        if (c.url.includes("/app") && "focus" in c) {
          return c.focus().then((w) => (w && "navigate" in w ? w.navigate(url) : w)).catch(() => c.focus());
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
