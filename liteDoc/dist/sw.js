// A minimal Service Worker to satisfy PWA install requirements
const CACHE_NAME = 'litedoc-pwa-v1';

self.addEventListener('install', (event) => {
    // We don't cache anything heavily by default since the user runs this locally,
    // but caching the root makes it a valid PWA.
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(['./', './index.html']);
        })
    );
});

self.addEventListener('fetch', (event) => {
    // Just pass through. We just need the event listener for PWA installability.
    event.respondWith(
        fetch(event.request).catch(() => {
            return caches.match(event.request);
        })
    );
});
