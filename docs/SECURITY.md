# Security policy

## Reporting a vulnerability

Please email **security@mezi.app** (or open a private security advisory on GitHub).
We aim to respond within a few days. Please don't open public issues for vulnerabilities.

## Threat model

Kadmu is a **self-hosted personal media app**. It is designed to be safe when run:

1. on your own machine (localhost), and
2. on a trusted home network (LAN) behind an optional password — sharing to the LAN can
   be switched on or off from inside the app (Settings ▸ Watch on other devices), or started
   with `--lan`.

It is **not** designed to be a public, multi-tenant service exposed directly to the
internet. If you expose it publicly, do so behind a reverse proxy with HTTPS, set a strong
`--password`, and prefer `--read-only`.

## Protections built in

| Risk | Mitigation |
|------|-----------|
| **Path traversal** | Every file path from the client is resolved (`realpath`) and must fall inside a configured library root, or it's rejected. |
| **Network exposure** | The listening socket binds `0.0.0.0`, but a connection-time gate (`KadmuServer.verify_request` ▸ `peer_allowed`) inspects the **real TCP peer address** — which, unlike a `Host` header, cannot be forged. Loopback is always served; private-LAN peers are served only while **network sharing is on** (the Settings toggle, or `--lan`); public addresses are never served unless `--allow-any-host` is set. This is what lets sharing be toggled from the app instantly, with no socket rebind, while keeping the default **loopback-only**. The toggle is a management action — it requires auth (when a password is set) and is refused in `--read-only`/demo mode. |
| **CSRF / DNS-rebinding** | The `Host` header is checked against an allow-list (localhost + the machine's own LAN IPs; real private IPs only while network sharing is on). State-changing requests also require a positive same-site signal — a custom `X-Kadmu` header that cross-site pages cannot set without a CORS preflight we never grant, or a same-site `Origin`/`Referer`. This blocks malicious websites from driving the local server. |
| **Unauthenticated access** | Optional password (`--password`). When set, all non-login routes require a `HttpOnly`, `SameSite=Strict` session cookie. Sessions expire (30 days) and are capped in number; wrong-password attempts are throttled per source IP with exponential backoff/lockout, and the password compare is constant-time. |
| **Accounts mode** (`--accounts`) | Per-user sign-in backed by SQLite. Passwords are hashed with **PBKDF2-HMAC-SHA256** (per-user salt, ~240k iterations), never stored or returned in clear. Sessions are server-side rows (persist across restarts, 30-day expiry, reaped on a timer); login/registration are IP-throttled like the shared-password path. Roles are `admin`/`viewer`: library and instance management require an admin (`_require_admin`), while per-user data (resume/My-List/playlists/prefs) is isolated by `user_id`. Self-sign-up is **off by default** (admins create accounts); the last admin can't be demoted or deleted. Console recovery via `--reset-password`. |
| **Destructive file ops** | Rename/move/delete/mkdir and config changes are disabled entirely in `--read-only` mode and require auth otherwise. Deletes move to a `.kadmu-trash` folder (reversible), never `rm`. |
| **Server-side folder browser** | The `/api/browse` picker (which can see directory names outside the library) is disabled in read-only mode and requires auth. |
| **XSS** | All user/file-derived strings are HTML-escaped before rendering, and a strict `Content-Security-Policy` (`script-src 'self'`, no inline scripts) is sent with the app. |
| **Resource exhaustion** | Concurrent `ffmpeg` thumbnail jobs are capped; request bodies are size-limited; video is streamed in bounded chunks with proper HTTP Range handling. |
| **Request flooding** | A per-IP **token-bucket rate limiter** applies to every route (not just login), defanging floods meant to peg the CPU (e.g. hammering search to force re-indexing). Loopback is always exempt; tune with `KADMU_RATE_RPS`/`KADMU_RATE_BURST`, or disable with `--no-rate-limit`. Behind a same-host reverse proxy, rate-limit at the proxy (Kadmu sees only the loopback proxy). |
| **Stream abuse / quotas** | Beyond the global live-encode cap, each identity (signed-in user in accounts mode, else IP) is limited to `KADMU_USER_MAX_STREAMS` simultaneous live transcode/remux streams, so one viewer can't tie up every core. A bandwidth meter tracks bytes served per identity. |
| **Slow-loris / idle sockets** | A per-request socket timeout (`KADMU_REQUEST_TIMEOUT`, default 120s) reclaims stalled connections; a live transfer resets it on every chunk. |
| **Transport security (TLS)** | Optional **built-in HTTPS** (`--tls CERT KEY`, or `KADMU_TLS_CERT`/`KADMU_TLS_KEY`) for direct LAN serving, or terminate TLS at a reverse proxy (recommended for public exposure — see [`deploy/Caddyfile`](../deploy/Caddyfile)). Built-in TLS sends no HSTS so a self-signed cert can't lock a browser out of the host. |
| **Clickjacking / sniffing** | `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. |
| **Command injection** | `ffmpeg`/`ffprobe` are invoked as argument vectors (never a shell) with `--` before filenames. |

## What Kadmu does NOT do

- No automatic certificate management — built-in TLS (`--tls`) takes a cert/key you supply; for
  auto-HTTPS on a public domain, terminate TLS at a reverse proxy (see [`deploy/`](../deploy/)).
- No per-user *libraries* — everyone who can sign in sees the same configured folders. Accounts
  (opt-in, `--accounts`) isolate per-user *data* (resume points, My List, playlists, prefs) and
  add admin/viewer roles, but they share one library. The default is still a single shared password.
- No outbound network calls — it never phones home.
