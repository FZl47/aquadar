const CACHE_NAME = 'aquadar-pwa-v1';
const PRECACHE_URLS = [
    '/',
    '/static/css/base.css',
    '/static/css/style.css',
    '/static/css/bootstrap5-2.min.css',
    '/static/css/leaflet.css',
    '/static/js/jquery.js',
    '/static/js/bootstrap.min.js',
    '/static/js/leaflet.js',
    '/static/img/logo.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS).catch(() => null))
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => Promise.all(
            keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
        ))
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    event.respondWith(
        caches.match(event.request).then((cached) => cached || fetch(event.request).then((resp) => {
            if (!resp || resp.status !== 200 || resp.type === 'opaque') return resp;
            const clone = resp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone)).catch(() => null);
            return resp;
        }).catch(() => cached))
    );
});
