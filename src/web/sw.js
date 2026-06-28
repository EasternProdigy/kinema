/* Kadmu service worker — an offline app shell, nothing more.
   Strategy: network-first for the shell (so new code ships the moment you're
   online), falling back to the cached shell when offline. The API and media
   (stream / thumb / transcode / storyboard) are never intercepted — they're
   large, dynamic, and must always hit the server. */
"use strict";
const CACHE = "kadmu-shell-v1";
const SHELL = [
  "/", "/style.css", "/qr.js", "/favicon.svg", "/manifest.webmanifest",
  "/js/util.js", "/js/icons.js", "/js/state.js", "/js/routing.js", "/js/library.js",
  "/js/home.js", "/js/manage.js", "/js/settings.js", "/js/accounts.js", "/js/player.js",
  "/js/audio.js", "/js/filters.js", "/js/tune.js", "/js/playerui.js", "/js/party.js",
  "/js/palette.js", "/js/keys.js", "/js/main.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()).catch(() => {}));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;          // dynamic + media: always network
  e.respondWith(
    fetch(req).then(res => {
      if (res && res.ok && (req.mode === "navigate" || SHELL.includes(url.pathname))) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
      }
      return res;
    }).catch(() =>
      caches.match(req).then(r => r || (req.mode === "navigate" ? caches.match("/") : undefined))
    )
  );
});
