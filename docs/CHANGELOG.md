# Changelog

All notable changes to Kadmu are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Reclaim disk — Archive a finished title.** A one-click background re-encode that shrinks a
  watched show/movie to a smaller, still-watchable copy, kept in your library. Re-encodes to a
  more efficient codec at full resolution (**visually-lossless** — honest about it: truly
  *lossless* video can't be smaller, so this is imperceptible-loss, not bit-exact), default
  **AV1** (plays natively), falling back to HEVC/H.264 by what your ffmpeg has. One bounded
  background worker (one encode at a time), live progress + Cancel on the title page, and a
  "ready to archive" flag on watched posters (auto-suggest; never compresses without your
  click). Each file is verified valid + actually smaller before the original is moved to
  `.kadmu-trash` (recoverable) and the smaller copy swapped in under the same name, so resume
  and grouping survive; already-efficient files are skipped. Tunable via `KADMU_ARCHIVE_*`.
- **Stream from cloud / remote storage.** Point Kadmu at media on Dropbox, Google Drive, MEGA,
  S3/B2, a NAS, or your own server — mount it as a folder (provider app or rclone) and add it
  in *Settings → Add cloud / remote storage…*. Your video still streams through your node, never
  our servers. Full guide in [REMOTE_STORAGE.md](REMOTE_STORAGE.md).
- **Native remote sources (no mounting).** Connect an **HTTP** (directory-listing) or **WebDAV**
  server directly in *Settings → Remote sources → Connect a server…* (with Test). Kadmu lists it
  and **range-proxies playback through your node** — stdlib `urllib` only, no new deps, with an
  anti-SSRF guard (no cross-host redirects). Native containers play directly; the bytes never
  touch our servers. S3-compatible + Drive/Dropbox (OAuth) and remote remux are the next steps.
- **A VLC-grade "Tune" sheet in the player (`T`).** One tidy tray gathers the new power-user
  controls so the bar stays clean: **video** — brightness / contrast / saturation, rotate,
  flip, zoom and a Fit/Crop/Stretch aspect mode (all non-destructive CSS); **audio** — a
  5-band **equalizer** with presets, **volume boost up to 300%**, **normalize** (level loud &
  quiet parts), **mono** downmix and an **audio delay** for lip-sync; **tools** — frame-step,
  **A-B loop**, and **screenshot**. Audio runs through the Web Audio API and degrades to a
  no-op where it isn't available.
- **More player power:** frame-step (`,`/`.` while paused), **A-B loop** (`B`), **screenshot**
  (`I`, saves the current frame as a PNG), and a **free-typed playback speed** box (0.1–4×).
- **Per-file memory.** Kadmu remembers the audio track, subtitle, speed and subtitle-sync you
  chose for each clip and restores them next time — in every mode.
- **Command palette (`Ctrl`/`⌘`+`K`).** One box to run any action or jump to anything in your
  library, with fuzzy matching and live search results folded in.
- **A real home page.** The library root now opens on a hero (resume what you were watching, or
  the freshest addition) over a **Recently added** rail, alongside Continue watching and My
  List. Built entirely from local data — no metadata service, no outbound calls.
- **Skip intro & hover previews.** A **Skip intro** button appears during an intro/recap
  chapter; hovering a video card plays a quick **storyboard preview**.
- **Install Kadmu as an app (PWA).** A web manifest + an offline app-shell service worker let
  you install Kadmu to your dock/home screen and launch it in its own window.
- **Watch party / synced playback (LAN).** Start a room, share the 4-character code (or invite
  link), and everyone stays in lockstep — play, pause, seek and episode changes mirror to the
  whole room over Server-Sent Events. One click, free, and the server brokers only the play
  *state* — never the video.
- **Public-hardening & ops (Phase 3).** Optional **built-in HTTPS** — point Kadmu at a cert and
  key with `--tls CERT KEY` (or `KADMU_TLS_CERT`/`KADMU_TLS_KEY`) and every URL it serves becomes
  `https://`; for public exposure a reverse proxy with automatic certs is still recommended
  (a ready-made [`deploy/Caddyfile`](../deploy/Caddyfile) + [`deploy/README.md`](../deploy/README.md)
  are included). **Per-IP rate limiting** (a token bucket; loopback always exempt) now defends
  every route — not just login — against floods, tunable via `KADMU_RATE_RPS`/`KADMU_RATE_BURST`
  or off with `--no-rate-limit`. **Observability:** a `GET /healthz` liveness probe, a Prometheus
  `GET /metrics` endpoint (requests, response classes, bytes served, errors, active streams,
  per-user bandwidth in accounts mode), optional **structured per-request JSON logging**
  (`--log-requests`, or `KADMU_ACCESS_LOG` to a file), and clean 500s with error capture instead
  of dropped connections. **Quotas/accounting:** a per-user (or per-IP) cap on simultaneous live
  transcode/remux streams (`KADMU_USER_MAX_STREAMS`, default 3) plus a bandwidth meter — the
  groundwork for paid tiers. All standard-library only; defaults are tuned so a normal browser
  never trips the limiter.
- **Kadmu Cloud — control-plane + cloud-attach (Phase 4a, scaffolded).** A new, separate
  hosted layer under [`cloud/`](../cloud/README.md) — **not shipped to self-hosters** and
  never needed to run the node. It's stdlib-only like the core (Stripe is reached over REST
  with `urllib`, no SDK) and runs **end-to-end in MOCK mode with zero Stripe keys**:
  marketing/landing + pricing + donate pages, **pay-first signup** (Stripe Checkout →
  entitlement → access), the customer portal, **signature-verified webhooks** that keep
  subscription state in sync, a subscriber **dashboard** (status + node connection details),
  and a machine-to-machine **`/api/license`** endpoint that issues short-lived, **HS256-signed**
  license tokens. The node can now run **cloud-attached** (`--cloud URL` / `--tenant ID` +
  `KADMU_CLOUD_SECRET`, or the `KADMU_CLOUD_*` env vars): it fetches and verifies a license,
  caches it on disk for an **offline-grace** window (survives brief cloud outages and even a
  restart during one), and — only when cloud-attached and the subscription is inactive —
  gates the instance with **HTTP 402** while still serving the app shell + `/api/session`, so
  the UI shows a "Manage billing" notice and you can still sign in. **Default self-host is
  completely unchanged and fully unlocked** (the gate is a no-op). Donations for the OSS side
  are wired separately (one-time Checkout, no account needed).
- **Remote-from-anywhere over P2P (Phase 4b, built).** A new `cloud/` peer-to-peer layer —
  **not shipped to self-hosters** — that lets you reach your home library from anywhere with the
  **video streaming browser↔node directly, so our egress stays ≈ $0** (see ROADMAP.md — Cost model). The cloud is
  only a **handshake broker**: a stdlib **signaling server** passes one WebRTC offer/answer
  between a guest browser and the home **connector**, then gets out of the way. From there
  [`cloud/wire.py`](../cloud/wire.py) tunnels the node's HTTP — the `api()` calls *and* the
  byte-range video — over the data channel (with an `ABORT` frame on every seek so scrubbing
  stays responsive); `src/web/js/remote.js` is the browser end, inert unless a remote session is
  configured. The framing codec is unit-tested (8 tests) and the broker smoke-tested; the live
  aiortc transport, the real-channel handshake, **share-a-link**, and an **MSE fragmented-MP4**
  path for remote video are the integration follow-ups (see [cloud/README.md](../cloud/README.md)).
  The open-source core stays **stdlib-only** — the lone WebRTC dependency (`aiortc`) is
  quarantined to the connector in `cloud/`, and the core needs zero changes to be reachable.
- **Scale & cost control (Phase 5, built).** The whole [Phase 5 design](ROADMAP.md) is now
  implemented as code + config-as-code under `cloud/` (the open-source core is untouched bar one
  opt-in flag). The heart is the **cost guardrail**: a stdlib **`cloud/metering/`** package
  (21 unit tests) that meters relay bytes per tenant per month, enforces a per-plan cap, and
  mints coturn's standard ephemeral TURN credentials — so an over-budget or unsubscribed tenant
  simply never gets a credential and can't open a relay allocation (the cap is enforced *before*
  bytes flow). The control-plane gains **`GET /api/relay-credentials`** (entitlement- + cap-gated;
  returns short-TTL ICE servers or refuses to STUN-only) and a Prometheus **`/metrics`** endpoint.
  A capped **`cloud/relay/`** coturn config ships the relay 4b lacked — ≤720p / ~3 Mbps ceilings,
  private-range SSRF denial, and a metrics collector that attributes bytes to tenants. The
  signaling broker gains a sticky **`X-Kadmu-Node`** routing key, env-tunable TTLs and a
  `/metrics` endpoint (scale out behind a sticky LB with zero shared state); the connector and
  `remote.js` fetch entitlement-bound ICE servers and clamp quality on relay. The static app
  shell can be served behind a **CDN** (`--cdn`/`KADMU_CDN`): immutable long-cache headers +
  build-free `?v=APP_VERSION` cache-busting — **off by default, so self-host is byte-identical**.
  Finally **`cloud/infra/`** ships the deploy stack: a Caddy sticky LB, `docker-compose.scale.yml`,
  Cloudflare-Free CDN notes, and a Prometheus + Grafana observability stack (dashboards + the
  fleet relay-egress budget alert). All standard-library Python + config; the only operated (not
  authored) binaries are coturn and, optionally, Prometheus/Grafana. Standing up the live
  infrastructure (VPS, DNS, Cloudflare, real Stripe/TURN secrets) is the remaining deploy step.
- **Multi-user accounts (opt-in, `--accounts`).** Real sign-in for households and shared
  boxes, backed by an embedded **SQLite** database (`sqlite3`, still standard-library only —
  no `pip`). Each person gets their **own** resume points, My List, playlists and display
  preferences; admins manage the library and people, viewers just watch. Passwords are hashed
  with **PBKDF2-HMAC-SHA256**, sessions **persist across restarts**, and the first account
  created becomes the owner (admin) — inheriting any existing single-password watch history.
  Manage everyone from **Settings ▸ People** (add users, set roles, reset passwords, open or
  close self-sign-up); change your own name/password in **Settings ▸ Your account**; the
  top-bar avatar opens an account menu with sign-out. Locked out? `--reset-password USERNAME`
  resets it from the console. The default (no `--accounts`) is unchanged: one optional shared
  password, one shared library.
- **Plays every format.** Non-native containers (`.mkv`, `.avi`, `.ts`, …) now stream as a
  seekable MP4 via on-the-fly remux — a fast stream-copy when the codecs are already
  browser-friendly, transcoding only what isn't — cached under `cache/remux/`. This now
  also covers **native containers holding a codec the browser can't decode** — e.g. an
  HEVC/x265 `.m4v` or `.mp4` — which are transcoded to H.264 instead of failing to play.
  (Requires an ffmpeg with the relevant decoder; the release-bundled ffmpeg includes HEVC.)
  Transcoding uses whatever H.264 encoder ffmpeg offers (`libx264`, or `libopenh264`).
- **Quality selector** in the player: a polished resolution menu (tier badges +
  "best quality" / "data saver" hints) to switch a video's resolution on the fly
  (240p / 360p / 480p / 720p / 1080p / 4K). Only resolutions below the source's
  native height are offered, so it downscales but never upscales. The chosen
  quality is transcoded with ffmpeg and cached, so switched-to qualities stay
  fully seekable and playback resumes at the same spot.
- **Self-cleaning cache.** A background janitor sweeps the prepared-video cache
  (remux + quality copies) every minute, deleting files you're no longer watching
  so it stays to roughly just the current video — the file streaming now (and the
  most recent one) is always kept, so pausing is safe. A size cap is the backstop.
  Tune with `KADMU_CACHE_TTL_SEC` (idle seconds before cleanup, default 300) and
  `KADMU_CACHE_LIMIT_MB` (hard size cap, default 2048; `512` for a small laptop).
- **One-line installers**: `install.sh` (macOS/Linux, `curl | bash`) and `install.ps1`
  (Windows, `irm | iex`) fetch the latest release (ffmpeg bundled) and launch it, with a
  source fallback when no release binary exists.
- **Idempotent launch.** Starting Kadmu while it's already running just opens a new browser
  tab (preferring Firefox) instead of erroring on the busy port — so double-clicking the app
  again, or re-running the `kadmu` command, always Just Works.
- **Desktop app, your way.** Opt-in desktop-icon installers for Linux / macOS / Windows
  (`launchers/install-linux.sh`, `install-macos.sh` which builds a real `Kadmu.app`, and
  `install-windows.ps1`). The icon opens a normal Firefox tab by default, or a dedicated
  **app window** (`--app`) or fullscreen **kiosk** (`--kiosk`) — also via `KADMU_LAUNCH_MODE`.
  Launchers now work from either a source checkout or a release binary.

### Changed
- **Codebase split for maintainability** (no behaviour change). The single big
  `server.py` is now the `src/kadmu/` package (modules: const · rt · accounts ·
  media · store · security · library · handler · app), with `src/server.py` kept as
  a thin launcher; the single big `app.js` is now ordered classic scripts under
  `src/web/js/`. Still pure standard library, no build step, no bundler, no `pip`.
- **Continue watching is now one card per series.** Instead of every part-watched
  episode, the row shows a single tile per show — the episode you're mid-way
  through, or the next one when you've just finished one (it advances and starts the
  next from the beginning, rewatches included). A finished series drops off the row.
- **Repo reorganized** for clarity: application code in `src/`, helper scripts in `scripts/`,
  deployment files in `deploy/`, and contributor docs in `docs/`. Runtime state (`data/`,
  `cache/`, optional `bin/ffmpeg`) stays at the project root.

## [1.0.0] - 2026-06-26

First public release. 🎬

### Added
- Browse any folder layout (flat, season/episode, multiple shows & movies).
- ffmpeg thumbnail posters with duration badges and resume-progress bars.
- Player: speed, loop, skip ±10s, volume memory, next/prev, autoplay-next, fullscreen.
- One-click **Picture-in-Picture** with Firefox coaching, plus keyboard shortcuts.
- **Continue watching** with server-side resume positions, synced across devices.
- On-disk organizing: rename, move, new folder, delete (safe move-to-trash).
- In-browser **folder picker** for first-run setup — no path typing needed.
- **LAN streaming** (`--lan`) with an optional **password** (`--password`).
- **Read-only / kiosk mode** (`--read-only`) for shared and demo instances.
- Cross-platform double-click launchers (Linux/macOS/Windows) + Linux menu installer.
- **`--demo` mode**: auto-generates royalty-free sample videos and serves them
  read-only — try Kadmu instantly with no files. One-click `demo.sh` /
  `Kadmu Demo.command` / `Kadmu Demo.bat`, and a ready-to-host Docker demo.
- **Bundled ffmpeg**: release builds ship a static ffmpeg/ffprobe so thumbnails work
  with zero install. From source, Kadmu finds ffmpeg on `PATH` or via
  `KADMU_FFMPEG`/`KADMU_FFPROBE`. See [NOTICE.md](NOTICE.md).

### Security
- Host allow-listing + Origin/Referer checks (CSRF & DNS-rebinding protection).
- Optional password auth with `HttpOnly`, `SameSite=Strict` session cookies.
- Strict Content-Security-Policy; consistent HTML escaping.
- All filesystem access sandboxed to configured library roots.
- ffmpeg concurrency cap and request-size limits.
- Security headers: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`.
