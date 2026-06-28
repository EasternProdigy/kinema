# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Kadmu** — a self-hosted "personal cinema in a browser tab." Point it at folders of
videos and watch them in the browser with thumbnails, resume, autoplay, and Firefox
Picture-in-Picture; optionally stream across the LAN. MIT licensed, by Pentarosa Co.

The whole app is **two moving parts**: a Python backend — the **`src/kadmu/` package**
(standard library only), launched by the thin shim [src/server.py](src/server.py) — and a
static vanilla-JS frontend ([src/web/](src/web/), a set of **ordered classic scripts** under
`src/web/js/`). No framework, no build step, no bundler, no `pip install`. ffmpeg/ffprobe are
used for thumbnails, duration/codec metadata, and on-the-fly remux/transcode of non-native
containers — the app still runs (minus those features) without them.

> It used to be one giant `server.py` and one giant `app.js`; both were split by concern into
> the layout below. The *promises* are unchanged (stdlib-only, no build, no bundler); only the
> file count changed.

## Repository layout

```
kadmu/
├─ src/
│  ├─ server.py     thin launcher → kadmu.app.main()  (the entry point everything targets)
│  ├─ kadmu/        the backend package (see "Architecture › Backend")
│  └─ web/          the frontend: index.html · style.css · qr.js · js/*.js · fonts/
├─ scripts/        run.sh · dev.sh · demo.sh · make-sample-library.sh
├─ launchers/      double-click launchers (Linux/macOS/Windows) + install-linux.sh
├─ cloud/          the HOSTED layer — NOT shipped to self-hosters (Phase 4–5: control-plane,
│                  signaling, connector, metering, relay, infra; see cloud/README.md)
├─ deploy/         Dockerfile · docker-compose.yml · .env.example
├─ docs/           CONTRIBUTING · SECURITY · CHANGELOG · NOTICE · ROADMAP · BRAND.md + brand/
├─ install.sh / install.ps1   one-line installers (curl|bash / irm|iex)
├─ CLAUDE.md · README.md · LICENSE
└─ (runtime, git-ignored) data/  cache/  bin/    ← at the PROJECT ROOT, not in src/
```

**Path invariant worth knowing up front:** the app keeps its runtime state at the *project
root*, not next to the code. Paths are computed in [src/kadmu/const.py](src/kadmu/const.py):
`APP_DIR` is the `src/` dir (this is why const.py uses `Path(__file__).resolve().parent.parent`
— it lives one level deeper than the old `server.py`), `WEB_DIR = src/web`, and in source mode
`STATE_DIR = APP_DIR.parent` (the repo root), so `data/`, `cache/` (thumbs + remux), and a
downloaded static `bin/ffmpeg` all live there. The Docker image mirrors the `src/` layout so
this resolves to `/app` in-container. If you move the package or change `APP_DIR`/`STATE_DIR`,
re-check `_find_tool`, the Dockerfile, and the launcher/script paths together.

## Commands

```bash
# Run from source (Python 3.8+)
python3 src/server.py ~/Videos      # add a folder and start; or just `python3 src/server.py`
./scripts/run.sh [args...]          # same, passes args through to src/server.py

# Develop — auto-restarts the backend when src/server.py or src/kadmu/* changes.
# Frontend (src/web/*) needs no restart: edit and refresh the browser tab.
./scripts/dev.sh                    # http://127.0.0.1:8000, --no-open
./scripts/dev.sh --lan              # any extra args pass through to src/server.py

# Try it with generated sample clips (read-only, needs ffmpeg)
./scripts/demo.sh                   # == python3 src/server.py --demo
bash scripts/make-sample-library.sh [out-dir]   # just generate the sample tree

# Checks (this is the entire CI gate — see .github/workflows/ci.yml)
python3 -m py_compile src/server.py src/kadmu/*.py     # backend syntax (whole package)
for f in src/web/*.js src/web/js/*.js; do node --check "$f"; done  # frontend syntax
# CI also boots the server and asserts GET /api/session returns "app": "Kadmu"

# Release bundles (normally only via tag push, see .github/workflows/release.yml)
# --paths src lets PyInstaller find the `kadmu` package from the server.py shim.
pyinstaller --onefile --name kadmu --paths src --add-data "src/web:web" \
  --add-binary "<ffmpeg>:." --add-binary "<ffprobe>:." src/server.py

# Public read-only demo image (build context MUST be the project root)
docker compose -f deploy/docker-compose.yml up --build
```

There is **no test suite, linter config, or formatter** — the CI gate above (compile-check +
boot smoke test) is the whole bar. Keep contributions passing it and manually exercise the
relevant flows (browse, play, resume, PiP, and `--lan`/`--password`/`--read-only` when touched).

## Architecture

### Backend — the [src/kadmu/](src/kadmu/) package

[src/server.py](src/server.py) is a thin launcher; the backend lives in `src/kadmu/`, split by
concern into modules whose dependencies point downward (no import cycles):

| module | responsibility |
|---|---|
| `const` | constants, paths, locks, the JSON helpers (`load_json`/`save_json`) — the foundation, no intra-package deps |
| `rt` | the mutable runtime flags set in `main()` (`READONLY`, `LAN_MODE`, `ACCOUNTS_ENABLED`, `PW_*`, …) — always read as `rt.NAME` so values stay live |
| `accounts` | the SQLite store: users, persistent sessions, per-user data, the legacy-JSON importer |
| `media` | ffmpeg: `probe_meta`, thumbnails, covers, subtitles→VTT, storyboards, the demo generator, cache pruning |
| `store` | library config/roots, resume progress, My List, viewer profiles, `resolve_within_roots`/`owning_root` |
| `security` | Host/CSRF/auth, the legacy shared-password sessions + login throttle, password hashing, the LAN toggle |
| `library` | directory listing, the folder browser, search + background index, the **home feed** (hero + recently-added), file ops (rename/move/delete-to-trash) |
| `ops` | public-hardening & ops: in-memory metrics, structured request/error logging, the per-IP rate limiter, per-identity concurrent-stream accounting + the bandwidth meter (depends only on `const`/`rt`) |
| `cloud` | **cloud-attach** (Phase 4a): poll the hosted control-plane for a signed license, verify it, cache it with offline grace, expose `entitlement_state()`/`entitlement_active()` for the gate. No-op unless run as a Kadmu Cloud tenant |
| `party` | in-memory **watch-party** rooms — the SSE subscriber registry + broadcast fan-out of play/pause/seek/load state (stdlib only; rooms evaporate when empty) |
| `handler` | the one `BaseHTTPRequestHandler` subclass and its route chains (incl. the watch-party SSE stream loop) |
| `app` | the threaded server (optional built-in TLS), the cache/trash/session janitor, browser launch, and `main()` |

> **The two load-bearing rules when editing across modules:** (1) the mutable runtime flags live
> only in `rt` and are referenced as `rt.NAME` (a bare `from .rt import READONLY` would capture a
> stale value); (2) everything else is imported by name (`from .store import load_progress`), so
> cross-module calls read like the old flat namespace. There's no third-party linter — a quick
> `python3 -m py_compile src/kadmu/*.py` plus actually importing `kadmu.app` catches mistakes.

A `ThreadingHTTPServer` (in `app`) drives a single `BaseHTTPRequestHandler` subclass (`Handler`,
in `handler`). There is no router abstraction — `_route_get`/`_route_post` are long
`if route == ...` chains, wrapped by `do_GET`/`do_POST` which run a small **request lifecycle**:
`_begin` (reset per-thread state) → `_pre` (health-check shortcut + per-IP **rate limiting**,
loopback exempt — see `ops.rate_ok`) → the route → `_finish` (record metrics + emit the optional
structured access log), with `_on_route_error` turning an unhandled exception into a clean 500
(and a counted/logged error) instead of a dropped connection. `/healthz` and `/metrics` are
handled here, before the gate (`/healthz` bypasses it entirely; `/metrics` does its own
host-check + loopback-or-admin auth). Every other request passes through one **security gate**
before any work happens:

`Handler._guard(route, mutating)` enforces, in order:
1. **Host allow-listing** (`host_allowed`) — blocks DNS-rebinding. Only localhost + the
   machine's own names/IPs are allowed; real private LAN IPs are allowed only in `--lan` mode.
2. **CSRF check** for mutating requests (`_origin_ok`) — requires a positive same-site signal:
   the custom `X-Kadmu` header (which the frontend sets on every `api()` call and a cross-site
   page cannot add without a CORS preflight the server never grants), or a same-site
   `Origin`/`Referer`.
3. **Auth** (`_authed`) — if a password is set (or accounts mode is on), all routes except
   `PUBLIC_ROUTES` require a valid `kadmu_session` cookie. In **accounts mode** the cookie maps
   to a SQLite session row → a user; `_resolve_user()` stashes that user on the request thread
   (`current_user()`), and `_is_admin()` reads its role.

Mutating library routes additionally call `_require_writable()` (rejects in `--read-only`) and,
in accounts mode, `_require_admin()` (library/instance management is admins-only; per-user data
like progress/My-List/playlists is not).

**Accounts mode (opt-in, `--accounts`).** A second auth model layered on the same gate:
real multi-user accounts backed by an embedded **SQLite** DB (`sqlite3`, stdlib) at
`data/kadmu.db`. The whole accounts subsystem lives in one section of `server.py` (schema +
`create_user`/`auth_user`/`set_user_*`/`delete_user`, persistent `db_*_session`, and per-user
`db_progress_*`/`db_mylist_*`/`db_playlists_*`/`db_prefs_*`). Passwords are **PBKDF2-HMAC-SHA256**
(per-user salt), sessions persist across restarts, roles are `admin`/`viewer`, the first account
created becomes the owner (admin) and inherits the old single-password JSON state via
`_import_legacy_into()`. Default (no `--accounts`) is byte-for-byte the original single shared
password — every data helper branches on `ACCOUNTS_ENABLED`. `--reset-password USERNAME` is the
console recovery hatch. Accounts and `--profiles` are mutually exclusive (accounts subsume profiles).

**Public-hardening & ops (Phase 3), all in `ops`.** *TLS:* optional built-in HTTPS
(`--tls CERT KEY` / `KADMU_TLS_CERT`+`KADMU_TLS_KEY`) wraps the listening socket in `app.main()`
and flips `rt.SCHEME`/`rt.TLS` so every URL we build reads `https://`; for public exposure a
reverse proxy (see [deploy/Caddyfile](deploy/Caddyfile)) stays the recommended path. *Abuse
protection:* a per-IP token-bucket limiter (`ops.rate_ok`, `KADMU_RATE_RPS`/`KADMU_RATE_BURST`,
`--no-rate-limit`) runs in `_pre` for every request — **loopback is always exempt**, so behind a
same-host proxy it sees only loopback and you should rate-limit at the proxy instead. *Observability:*
`GET /healthz` (unauthenticated liveness, bypasses the gate), `GET /metrics` (Prometheus text;
loopback-readable, else admin/auth), structured per-request JSON logging (`--log-requests` /
`KADMU_ACCESS_LOG`), and `_on_route_error` for 500 capture. *Quotas/accounting:* a per-identity
(user in accounts mode, else IP) cap on simultaneous **live** transcode/remux streams
(`ops.stream_acquire`, `KADMU_USER_MAX_STREAMS`; native direct playback isn't counted) layered on
the global `_stream_sem`, plus a bandwidth meter (`ops.add_bytes`, fed from every response-body write).

**Path safety is the other load-bearing invariant.** Any filesystem path coming from the
client must go through `resolve_within_roots()` (resolves symlinks/`..` and confirms the
target is inside a configured root) before use. `owning_root()` finds which root a path
belongs to. Never touch a client-supplied path without one of these — this is what prevents
path traversal. File mutations live in `op_rename` / `op_move` / `op_mkdir` / `op_delete`
(delete is a reversible move into a per-root `.kadmu-trash`, never `rm`).

**Playback pipeline.** Native containers (`NATIVE_EXTS`: mp4/webm/mov/…) are range-streamed
directly by `_serve_file_with_range` — manual HTTP Range (status 206, `Content-Range`, suffix
ranges) in 256 KB chunks, which is what makes seeking work and keeps memory flat. Non-native
containers (`.mkv`, `.avi`, …) are made playable via **on-the-fly remux** (`build_remux`):
a fast stream-copy to MP4 when the codecs are already browser-friendly
(`NATIVE_VCODECS`/`NATIVE_ACODECS`), transcoding only what isn't. The player's resolution
picker uses `TRANSCODE_LADDER` (height → bitrate/bufsize, downscale-only). Remuxes are cached
under `cache/remux/`.

**State & storage.** Runtime state is JSON files written atomically (`save_json` → temp +
`os.replace`) under `DATA_DIR`, with caches under `CACHE_DIR`/`REMUX_DIR`:
- `config.json` — library roots (the source of truth for `real_roots()`)
- `progress.json` — resume positions, keyed by absolute path; drives "Continue watching"
- `playlists.json`, `meta_cache.json` — playlists and the ffprobe metadata cache
- `cache/thumbs/<sha1>.jpg`, `cache/remux/…` — generated media
- `kadmu.db` — **accounts mode only** (`--accounts`): SQLite holding users, persistent
  sessions, and per-user progress/My-List/playlists/prefs. The JSON files above stay the store
  for the default single-password mode (and are imported once into the first account).

The cache key for thumbnails/metadata/remux is `path | mtime_ns | size`, so edits/replacements
auto-invalidate. Concurrency is guarded by module-level locks (`_io_lock`, `_meta_lock`,
per-key locks) and a `Semaphore` cap on simultaneous ffmpeg processes (anti fork-bomb).

**ffmpeg discovery** (`_find_tool`): explicit env override (`KADMU_FFMPEG`/`KADMU_FFPROBE`)
→ bundled binary near the executable or at the project root (`./`, `./bin`, `./ffmpeg`, plus
the PyInstaller `_MEIPASS` dir) → `PATH`. Everything ffmpeg-dependent degrades gracefully.

**Frozen vs. source mode.** When running as a PyInstaller bundle (`sys.frozen`), web assets
are read from the temp extract dir (`_MEIPASS`) and `STATE_DIR` is `~/.kadmu`. From source,
`WEB_DIR = src/web` and `STATE_DIR = APP_DIR.parent` (the repo root) — see the path invariant
above.

### Frontend — [src/web/](src/web/) (no build step, no bundler)

- [src/web/index.html](src/web/index.html) — the entire DOM up front (home hero, library view,
  player overlay + the **Tune** sheet and **watch-party** panel, settings modal, command
  palette, generic dialog, login overlay), toggled via `.hidden`. Single-page app. Also links
  the PWA manifest.
- [src/web/js/](src/web/js/) — vanilla JS, **one `state` object, no framework, no modules**. The
  old `app.js` was split into **ordered classic `<script>` files** that share the global scope;
  `index.html` loads them in a fixed order and `main.js` boots last:
  `util → remote → icons → state → routing → library → home → manage → settings → accounts →
  cloud → player → audio → filters → tune → playerui → party → palette → keys → main`.
  (`audio`/`filters` = the Web-Audio graph + CSS video adjustments; `tune` = the player Tune
  sheet that drives them; `party` = watch-party SSE client; `palette` = the `Ctrl/⌘+K` command
  palette; `home` = the hero + recently-added rail + storyboard hover-preview; `cloud` = the
  Phase-4a inactive-subscription overlay + `api()` 402 hook, a no-op unless cloud-attached;
  `remote` = the Phase-4b P2P fetch proxy — loaded right after `util.js` so it can wrap `api()`
  before any call, and inert unless a remote session is configured.) Because they're classic scripts,
  top-level `const`/`function` in one file are visible to the others, so cross-file calls work
  unchanged — **the only constraints are load order (`util.js` defines `$` first; `main.js`'s
  init IIFE runs last) and declaring each name once.** If you add a file, add a `<script>` tag
  in the right spot. All server calls go through
  the `api()` helper (`util.js`; injects the `X-Kadmu` CSRF header; on 401 `needAuth` it pops the
  login overlay). The UI is gated by `/api/session` flags (`canManage`, `canBrowse`, `readonly`,
  `accounts`, `role`, …) from `_session_state()` — the backend is the authority on capabilities.
  Thumbnails load lazily via an `IntersectionObserver`; last folder/volume persist in `localStorage`.
- [src/web/style.css](src/web/style.css) — hand-written; bundled fonts in `src/web/fonts/`,
  served via the `/fonts/*.woff2` route. The split scripts are served via the `/js/*.js` route.

### API surface (all under `/api/`)

GET: `session`, `config`, `library?path=`, `browse?path=`, `meta?path=` (also returns the
file's `audios`/`subs`/`chapters`), `thumb?path=`, `stream?path=` (Range + remux; optional
`audio=` ordinal selects an audio track), `transcode?path=&height=` (optional `audio=`),
`progress`, `continue`, `home` (hero + recently-added rail, all local data), `search?q=`
(served from the background index — see below), `storyboard?path=` / `storyboard.jpg?path=`
(scrub + hover previews), `subs?path=` (sidecar + embedded subtitle tracks), `sub?path=`
(sidecar VTT, or `&track=N` to extract an embedded text track), `mylist`, `playlists`,
`trash` (item count + bytes), `party/state?code=` and `party/events?code=` (watch-party
**SSE** stream). POST: `login`, `logout`, `progress`, `progress/clear`, `mylist`,
`party/create` · `party/join` · `party/update` (synced playback; allowed even read-only —
not a library write), `lan`, `password`, `config`, `playlists`, `pick-folder` (native OS
dialog on the server desktop), `add-paths` (drag-and-drop), `op`
(rename/move/mkdir/delete/empty-trash), plus `register`, `account`, `users` (admin), `prefs`
(accounts mode). Static files (`/`, `/style.css`, `/qr.js`, `/favicon.svg`,
`/manifest.webmanifest`, `/sw.js` — the PWA shell) are served by `_serve_static`; the split
frontend scripts via the `/js/*.js` route and fonts via `/fonts/*.woff2`. The app shell also
carries the strict `CSP`.
**Ops routes (not under `/api/`, handled in the request lifecycle before the gate):** `GET
/healthz` (unauthenticated liveness) and `GET /metrics` (Prometheus text; loopback-readable,
else admin/auth).

**Background library index.** A daemon thread (`start_indexer` → `_indexer_loop`) walks every
root and builds an in-memory catalog of folders + video files; `search_library` ranks against
it (`_search_indexed`) for instant, complete results, falling back to a bounded live walk
(`_search_live`) only until the first build finishes. It re-walks every `INDEX_REFRESH` seconds
(picks up files added outside the app) and rebuilds immediately on any library mutation
(`request_reindex`, called from the `config`/`add-paths`/`op` routes). Resume positions live in
an in-memory single-writer cache too (`load_progress`/`set_progress`/`clear_progress`), not
re-read from disk per request. Reversible deletes (`.kadmu-trash`) are reaped by the cache
janitor (`purge_trash(TRASH_TTL)`) and on demand via the `empty-trash` op.

## Conventions & constraints

- **Never do anything that could crash or hang the user's computer.** Don't spawn unbounded or
  runaway work — no fork bombs, no fork/spawn loops, no `while True` that launches processes, no
  spawning many ffmpeg/transcode jobs at once, no fillers that exhaust RAM/CPU/disk, no commands
  that can wedge the machine. Keep concurrency capped (the existing `Semaphore`s / stream caps),
  prefer small bounded test runs, always set timeouts on subprocesses, and clean up every
  background process/server you start. When in doubt about resource cost, do the cheap thing or
  ask first.
- **Backend: Python standard library only.** No third-party runtime dependencies, ever.
- **Frontend: vanilla HTML/CSS/JS.** No framework, no bundler, no transpile.
- **Brand is the source of truth for anything visual.** Colors, gradient, fonts, radii,
  shadows, wordmark, voice — all come from [docs/BRAND.md](docs/BRAND.md) (visual deck:
  [docs/brand/kadmu-brand-guidelines.html](docs/brand/kadmu-brand-guidelines.html)), which
  mirrors the CSS tokens in [src/web/style.css](src/web/style.css). Don't introduce a value
  that isn't in the brand; if you change one, update `BRAND.md` and `style.css` together.
- **ffmpeg is optional** — guard every use behind a `FFMPEG`/`FFPROBE` check.
- **Security is non-negotiable**: new client-path handling goes through `resolve_within_roots`;
  new mutating routes go through `_guard(..., mutating=True)` and `_require_writable()` (plus
  `_require_admin()` if it's library/instance management, so viewers can't manage in accounts
  mode); any user/file-derived string rendered in the frontend is run through `escapeHtml`;
  never return a password hash to the client. See [docs/SECURITY.md](docs/SECURITY.md).
- The app is built for **localhost + trusted LAN**, not a public multi-tenant service. TLS is
  optional (built-in `--tls`, or terminate at a reverse proxy — [deploy/Caddyfile](deploy/Caddyfile));
  one shared password by default, optional real accounts via `--accounts`.
- `APP_VERSION` in [src/server.py](src/server.py) and [docs/CHANGELOG.md](docs/CHANGELOG.md)
  are kept in sync on release; the `Release` workflow triggers on `v*` tags and builds
  per-OS PyInstaller bundles with ffmpeg baked in. `install.sh`/`install.ps1` download those
  release assets (falling back to a source run if none exist).

## Configuration (CLI flags / env vars)

Flags: `[FOLDER ...]`, `--host`, `--port`, `--lan`, `--password`, `--read-only`, `--demo`,
`--no-browse`, `--allowed-host` (repeatable), `--allow-any-host`, `--app`, `--kiosk`,
`--no-open`, `--profiles`, `--accounts`, `--reset-password USERNAME`, `--tls CERT KEY`,
`--log-requests`, `--no-rate-limit`, `--cloud URL`, `--tenant ID`, `--cdn`, `--version`.
`--accounts` turns on multi-user accounts (SQLite); `--reset-password USERNAME` resets/creates
that account as admin (using `KADMU_NEW_PASSWORD`, else a printed random one) and exits.
`--tls CERT KEY` serves built-in HTTPS; `--log-requests` emits structured per-request JSON logs;
`--no-rate-limit` disables the per-IP limiter.
`--cloud URL` + `--tenant ID` (+ the secret in `KADMU_CLOUD_SECRET`) run the node **cloud-attached**
as a Kadmu Cloud tenant — subscription-gated via `kadmu.cloud` (Phase 4a); all three absent ⇒
plain self-host, fully unlocked.
`--cdn` (or `KADMU_CDN=1`) makes the static app-shell routes (`/js`, `/fonts`, `/style.css`) emit
immutable long-cache headers + `?v=APP_VERSION` cache-busting for serving behind a CDN (Phase 5);
**off by default**, so the self-host experience (edit a file, refresh) is unchanged. The hosted
`cloud/` layer has its own env (Stripe, TURN secret/URLs, relay caps) documented under `cloud/`.
Env equivalents read at startup: `KADMU_PASSWORD`, `KADMU_PORT`, `KADMU_READONLY`,
`KADMU_PROFILES`, `KADMU_ACCOUNTS`, `KADMU_NEW_PASSWORD` (for `--reset-password`),
`KADMU_CLOUD_URL` / `KADMU_CLOUD_TENANT` / `KADMU_CLOUD_SECRET` (cloud-attach; the secret is
**env-only**, never a CLI arg), `KADMU_LAUNCH_MODE` (`tab`/`app`/`kiosk`), `KADMU_CACHE_LIMIT_MB`,
`KADMU_CACHE_TTL_SEC`, `KADMU_TRASH_TTL_DAYS` (auto-purge trash after N days; default 14),
`KADMU_MAX_STREAMS` (concurrent live ffmpeg streams; default 5), `KADMU_INDEX_REFRESH_SEC`
(background re-walk interval; default 300), `KADMU_ALLOWED_HOSTS`, `KADMU_FFMPEG`, `KADMU_FFPROBE`.
**Phase 3 ops:** `KADMU_TLS_CERT`/`KADMU_TLS_KEY` (built-in HTTPS), `KADMU_RATE_LIMIT` (0 to
disable), `KADMU_RATE_RPS`/`KADMU_RATE_BURST` (per-IP token bucket; default 50/200),
`KADMU_USER_MAX_STREAMS` (per-user/IP live-stream cap; default 3), `KADMU_REQUEST_TIMEOUT`
(idle-socket timeout; default 120), `KADMU_LOG_REQUESTS`, `KADMU_ACCESS_LOG` (log file; default stdout).

## Launchers & desktop icons

`launchers/kadmu.sh` and the `.bat` files auto-detect the layout: a source checkout runs
`python3 src/server.py`; a release bundle runs the self-contained `kadmu`/`kadmu.exe`. They
pass all args through, so the launch mode flows in via `--app`/`--kiosk`.

`LAUNCH_MODE` (set in `main()` from `--app`/`--kiosk`/`KADMU_LAUNCH_MODE`) drives
`_launch_browser()`: `tab` opens a normal Firefox tab (default), `app` opens a dedicated
window using a separate Firefox profile at `STATE_DIR/app-profile`, `kiosk` adds `--kiosk`.
The opt-in desktop-icon installers (`launchers/install-{linux.sh,macos.sh,windows.ps1}`) take
a `tab|app|kiosk` argument and wire the icon (logo: `launchers/kadmu.png`/`.ico`, generated
from `src/web/favicon.svg`) to the launcher with that mode. macOS builds a real `Kadmu.app`.
