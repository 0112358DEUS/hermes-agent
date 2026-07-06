// DEUS PWA overlay — keep additive for upstream merges.
//
// Deus Ex Machina service worker for the Hermes dashboard SPA.
//
// Policy (matches the deusexmachina machine precedent): cache STATIC SHELL
// ASSETS ONLY. Never cache /api/* (REST, WS tickets, PTY), WebSockets, auth
// endpoints, or the token-injected index.html — navigations are network-only
// so expired sessions, rotated tokens, and auth redirects are never hidden
// by stale HTML. The Vite build emits content-hashed files under /assets/,
// so cache-first is safe there: a new build means new URLs, never a stale hit.

"use strict";

const DEUS_SW_VERSION = "deus-shell-v1";

// The SW may be registered under a reverse-proxy prefix (X-Forwarded-Prefix,
// e.g. /hermes/deus-sw.js). Derive the base from our own script URL so every
// path rule respects the base path without a rebuild.
const DEUS_BASE = self.location.pathname.replace(/\/deus-sw\.js$/, "");

const DEUS_SW_POLICY = Object.freeze({
  cacheName: DEUS_SW_VERSION + ":" + DEUS_BASE,
  // Static, unauthenticated shell files precached at install (relative to
  // the SW scope, so the proxy prefix is honoured automatically).
  precache: [
    "manifest.webmanifest",
    "deus-icon-180.png",
    "deus-icon-192.png",
    "deus-icon-512.png",
    "favicon.ico",
  ],
  // Runtime cache-first is allowed ONLY under these static directories.
  // /assets/ is Vite's content-hashed output; fonts are immutable binaries.
  shellPrefixes: ["/assets/", "/fonts/", "/fonts-terminal/", "/ds-assets/"],
  // Absolute bans — never read from or write to the cache for these, even
  // if a future rule accidentally widens. Paths are relative to DEUS_BASE.
  neverCachePrefixes: ["/api/", "/ws/", "/auth/", "/oauth/"],
  neverCacheExact: ["/login", "/logout", "/deus-sw.js"],
});

function deusRelativePath(url) {
  let path = url.pathname || "/";
  if (DEUS_BASE && path.startsWith(DEUS_BASE)) {
    path = path.slice(DEUS_BASE.length) || "/";
  }
  return path;
}

function deusShouldBypass(request) {
  if (request.method !== "GET") return true;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return true;

  const path = deusRelativePath(url);
  if (DEUS_SW_POLICY.neverCacheExact.includes(path)) return true;
  if (DEUS_SW_POLICY.neverCachePrefixes.some((p) => path.startsWith(p))) {
    return true;
  }
  return false;
}

function deusIsShellAsset(request) {
  const url = new URL(request.url);
  const path = deusRelativePath(url);
  if (DEUS_SW_POLICY.shellPrefixes.some((p) => path.startsWith(p))) return true;
  return DEUS_SW_POLICY.precache.some((rel) => path === "/" + rel);
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(DEUS_SW_POLICY.cacheName);
      // Tolerate individual misses (e.g. dist built before the icons
      // existed) — a failed addAll would keep the SW from installing at all.
      await Promise.allSettled(
        DEUS_SW_POLICY.precache.map((rel) => cache.add(rel))
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter(
            (name) =>
              name.startsWith("deus-shell-") &&
              name !== DEUS_SW_POLICY.cacheName
          )
          .map((name) => caches.delete(name))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  if (deusShouldBypass(request)) {
    // Network only. No respondWith fallback to cache — banned paths must
    // never be served (or stored) from the cache.
    event.respondWith(fetch(request));
    return;
  }

  if (request.mode === "navigate") {
    // index.html carries a serve-time-injected session token / auth flags:
    // NEVER cache it. Network-only keeps auth state and tokens fresh.
    event.respondWith(fetch(request));
    return;
  }

  if (!deusIsShellAsset(request)) {
    event.respondWith(fetch(request));
    return;
  }

  // Static shell asset: cache-first, populate on miss.
  event.respondWith(
    (async () => {
      const cached = await caches.match(request);
      if (cached) return cached;

      const response = await fetch(request);
      if (response && response.ok) {
        const cache = await caches.open(DEUS_SW_POLICY.cacheName);
        await cache.put(request, response.clone());
      }
      return response;
    })()
  );
});
