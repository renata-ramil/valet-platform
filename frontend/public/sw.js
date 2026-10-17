// Minimal service worker, present only so Chrome treats the app as installable
self.addEventListener("install", () => {
  self.skipWaiting()
})

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener("fetch", (event) => {
  // Passing through to the network, no offline caching. Calling
  // respondWith explicitly rather than leaving the event unhandled: an
  // installed, controlling service worker with a fetch listener that never
  // calls respondWith has caused real, reproducible navigation hangs in
  // Chromium (found live, as a full-suite Playwright run where every
  // page.reload() after the service worker took control of the page never
  // completed).
  event.respondWith(fetch(event.request))
})
