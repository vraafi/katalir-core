/**
 * sw.js — service worker minimal untuk "Add to Home Screen" (FASE 6, opsional).
 *
 * KEPUTUSAN YANG DISENGAJA:
 *  - Navigasi memakai **network-first** dengan fallback cache. Cache-first untuk
 *    HTML akan menyajikan halaman basi setelah deploy (kelas bug yang paling
 *    mahal untuk aplikasi yang sedang berkembang).
 *  - Aset statis `_next/static` memakai **cache-first** (namanya ber-hash,
 *    jadi tidak mungkin basi).
 *  - Hanya GET yang di-cache; request API/mutasi selalu langsung ke jaringan.
 *  - Tidak ada versi cache "abadi": `CACHE` dinaikkan saat strategi berubah.
 */
const CACHE = "katalir-v1";
const PRECACHE = ["/", "/help", "/manifest.json", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // API (origin lain) diabaikan

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match("/")))
    );
    return;
  }

  if (url.pathname.startsWith("/_next/static") || /\.(png|svg|ico|woff2?|css|js)$/.test(url.pathname)) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
            return res;
          })
      )
    );
  }
});
