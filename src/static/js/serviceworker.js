const CACHE_NAME = 'aquadar-pwa-v3';
const OFFLINE_URL = '/offline/';
const PRECACHE_URLS = [
    OFFLINE_URL,
    '/static/img/logo.png',
    '/static/img/icon-192.png',
    '/static/img/icon-512.png',
    '/static/css/base.css',
    '/static/css/style.css',
    '/static/css/bootstrap5-2.min.css',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => Promise.all(
            PRECACHE_URLS.map((url) => cache.add(url).catch(() => null))
        ))
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
    const request = event.request;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request).catch(() => caches.match(OFFLINE_URL))
        );
        return;
    }

    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(request).then((cached) => {
                const network = fetch(request).then((resp) => {
                    if (resp && resp.status === 200 && resp.type === 'basic') {
                        const clone = resp.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(request, clone)).catch(() => null);
                    }
                    return resp;
                });
                return cached || network;
            })
        );
    }
});
