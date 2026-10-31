const CACHE_NAME = 'aeterna-shell-v3';
const SHELL_ASSETS = [
  './',
  './index.html',
  './css/style.css',
  './js/db.js',
  './js/zip-loader.js',
  './js/audio-engine.js',
  './js/app.js',
  './manifest.json'
];

// Install: cache app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

// Fetch: NETWORK-FIRST strategy
// When online → always fetch fresh code, update cache
// When offline → serve from cache
self.addEventListener('fetch', (event) => {
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Got fresh response from network — update the cache
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        // Network failed (offline) — serve from cache
        return caches.match(event.request);
      })
  );
});
