/* SafeCross AI service worker.
 *
 * What it does:  makes the app SHELL (page, scripts, styles, icons) available offline and fast.
 * What it never does:
 *   - cache /api/* responses (route results are Google Maps Platform content, whose caching is restricted, and risk data
 *     should always be fresh), or
 *   - touch other origins (Google Maps scripts and tiles go straight to the network), or
 *   - handle anything but GET.
 * __BUILD_ID__ is replaced by the server with a hash of the web files, so every deploy installs a new worker.
 */
const BUILD_ID = "__BUILD_ID__";
const CACHE = `safecross-shell-${BUILD_ID}`;

const PRECACHE = [
  "/",
  "/manifest.webmanifest",
  "/css/styles.css",
  "/js/app.js",
  "/js/api.js",
  "/js/detail.js",
  "/js/dom.js",
  "/js/exploreview.js",
  "/js/gmaps.js",
  "/js/install.js",
  "/js/onboarding.js",
  "/js/routemap.js",
  "/js/routeview.js",
  "/js/storage.js",
  "/icons/favicon-32.png",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-maskable-512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  // "reload" bypasses the HTTP cache so the worker never precaches stale files. No skipWaiting here: the page asks the
  // user before switching to a new version.
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE.map((url) => new Request(url, { cache: "reload" })))));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith("safecross-") && key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

const offlineJson = () =>
  new Response(JSON.stringify({ error: "offline" }), { status: 503, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request, { ignoreSearch: true });
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok && response.type === "basic") cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  if (cached) { network.catch(() => {}); return cached; }
  return (await network) || new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } });
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return; // searches (POST) always go straight to the network
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // Google Maps etc.: never intercepted, never cached

  if (url.pathname.startsWith("/api/") || url.pathname === "/healthz") {
    event.respondWith(fetch(request, { cache: "no-store" }).catch(offlineJson));
    return;
  }
  if (request.mode === "navigate") {
    // Single-page app: any page load is answered with the cached shell, so the app opens offline.
    event.respondWith(caches.match("/").then((cached) => cached || fetch(request)));
    return;
  }
  event.respondWith(staleWhileRevalidate(request));
});
