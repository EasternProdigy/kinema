# Kadmu Cloud — CDN for the static app shell (`cloud/infra/cdn/`)

Phase 5 ([docs/ROADMAP.md](../../../docs/ROADMAP.md)). Put
**Cloudflare Free** in front of the app-shell origin so the only KB the cloud serves on the
hot path — the HTML/CSS/`js/*.js`/fonts — are edge-cached globally at **$0**. Video never
touches the cloud (that's the whole egress model), so this CDN only ever caches the shell.

There is **no asset pipeline and no bundler** — cache-busting is done with a query string,
preserving the project's no-build promise.

## The architecture

```
   browser ──▶ Cloudflare Free (edge cache) ──▶ Caddy app.kadmu.app ──▶ core node (KADMU_CDN=1)
                 caches /js/* /fonts/* /style.css   long-cache headers + ?v=APP_VERSION refs
                 NEVER caches /, /index.html, /api/*
```

The `app.kadmu.app` vhost in [`../Caddyfile`](../Caddyfile) is the **origin behind the
CDN**: it emits `Cache-Control: public, max-age=31536000, immutable` on `/js/*`, `/fonts/*`,
`/style.css`, `no-cache` on `/` and `/index.html`, and `no-store` on `/api/*`. Cloudflare's
cache rule (below) must agree.

## Cloudflare Free setup

1. **Add the zone** `kadmu.app` to a free Cloudflare account; point the nameservers there.
2. **DNS:** an `A`/`AAAA` (or `CNAME`) record for `app.kadmu.app` → the origin box, with the
   **orange cloud (proxied)** on so traffic flows through Cloudflare's edge. Keep
   `cloud.kadmu.app` and `signal.kadmu.app` **DNS-only (grey cloud)** — they are dynamic /
   long-poll / WebRTC-handshake and should not be edge-cached.
3. **SSL/TLS mode: Full (strict).** Caddy already serves a valid Let's Encrypt cert on the
   origin, so the edge↔origin hop is verified TLS end to end.
4. **Cache rule** (Caching → Cache Rules → *Create*): **cache everything EXCEPT the shell
   and the API.**
   - Rule: *Cache Everything* (Edge TTL: *Respect origin* — the origin's `immutable`
     long-cache header drives it).
   - Expression — **bypass cache** for the dynamic paths (so only the immutable assets are
     cached):
     ```
     (http.request.uri.path eq "/") or
     (http.request.uri.path eq "/index.html") or
     (starts_with(http.request.uri.path, "/api/"))
     ```
     Set those to **Bypass cache**; everything else (i.e. `/js/*`, `/fonts/*`, `/style.css`,
     `/favicon.svg`, `/manifest.webmanifest`, `/sw.js`) is cached. Equivalent phrasing:
     **cache everything except `/`, `/index.html`, `/api/*`.**
5. (Optional) **Browser Cache TTL: Respect Existing Headers** so Cloudflare honors the
   origin's `max-age=31536000, immutable` for clients too.

## Build-free cache-busting (the `?v=APP_VERSION` trick)

We can't fingerprint filenames without a build step, so we version by **query string**:

- When the origin core node runs with **`KADMU_CDN=1`** (a flag being added to the core by
  the parent — documented here, not implemented in this directory), its static handler:
  1. Emits `Cache-Control: public, max-age=31536000, immutable` on `/js/*`, `/fonts/*`,
     `/style.css` (so the edge + browsers hold them ~forever), and
  2. Rewrites the app-shell references to those assets as
     `…/js/main.js?v=<APP_VERSION>` (and likewise for every script/style/font).
- `index.html` stays **short-cached / revalidated** (`no-cache`), so a browser always
  re-fetches it.

**How a release busts the edge with zero manual purge:**

1. A new release bumps `APP_VERSION` (already part of the release process —
   [`const.py`](../../../src/kadmu/const.py)).
2. The next request fetches the **short-cached `index.html`**, which now references
   `…/js/main.js?v=<NEW_VERSION>`.
3. `?v=<NEW_VERSION>` is a **new cache key** at the edge → a cache miss → Cloudflare pulls
   the new asset from the origin once and caches it for everyone. The old `?v=` entries
   simply age out, never served again.

No `--purge`, no API call, no bundler — the version bump on the (uncached) `index.html`
cascades to bust every immutable asset at the edge.

> **Self-host default is unchanged.** `KADMU_CDN` is **off by default**, so a self-hoster
> still gets `no-cache` everywhere (edit a `.js`/`.css` file and refresh — no stale cache).
> The CDN long-cache + `?v=` behavior is opt-in for the hosted origin only.

## Cost

**$0.** Cloudflare Free gives unlimited cached static egress; the origin serves each asset
version exactly once per edge PoP per release, then goes nearly silent. The dynamic paths
(`/`, `/index.html`, `/api/*`) are tiny. Combined with P2P video (never on our servers),
the hosted shell's bandwidth bill rounds to nothing.
