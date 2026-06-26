# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Kinema** — a self-hosted "personal cinema in a browser tab." Point it at folders of
videos and watch them in the browser with thumbnails, resume, autoplay, and Firefox
Picture-in-Picture; optionally stream across the LAN. MIT licensed, by Pentarosa Co.

The whole app is **two moving parts**: a single-file Python backend
([src/server.py](src/server.py), standard library only) and a static vanilla-JS frontend
([src/web/](src/web/)). No framework, no build step, no `pip install`. ffmpeg/ffprobe are
used for thumbnails, duration/codec metadata, and on-the-fly remux/transcode of non-native
containers — the app still runs (minus those features) without them.

## Repository layout

```
kinema/
├─ src/            server.py + web/  (the entire application)
├─ scripts/        run.sh · dev.sh · demo.sh · make-sample-library.sh
├─ launchers/      double-click launchers (Linux/macOS/Windows) + install-linux.sh
├─ deploy/         Dockerfile · docker-compose.yml · .env.example
├─ docs/           CONTRIBUTING · SECURITY · CHANGELOG · NOTICE · BRAND.md + brand/ (deck)
├─ install.sh / install.ps1   one-line installers (curl|bash / irm|iex)
├─ CLAUDE.md · README.md · LICENSE
└─ (runtime, git-ignored) data/  cache/  bin/    ← at the PROJECT ROOT, not in src/
```

**Path invariant worth knowing up front:** `src/server.py` keeps its runtime state at the
*project root* (one level up), not next to itself. In source mode `STATE_DIR = APP_DIR.parent`,
so `data/`, `cache/` (thumbs + remux), and a downloaded static `bin/ffmpeg` all live at the
repo root. The Docker image mirrors the `src/` layout so this resolves to `/app` in-container.
If you move `server.py` or change `APP_DIR`/`STATE_DIR`, re-check `_find_tool`, the Dockerfile,
and all the launcher/script paths together.

## Commands

```bash
# Run from source (Python 3.8+)
python3 src/server.py ~/Videos      # add a folder and start; or just `python3 src/server.py`
./scripts/run.sh [args...]          # same, passes args through to src/server.py

# Develop — auto-restarts the backend when src/server.py changes.
# Frontend (src/web/*) needs no restart: edit and refresh the browser tab.
./scripts/dev.sh                    # http://127.0.0.1:8000, --no-open
./scripts/dev.sh --lan              # any extra args pass through to src/server.py

# Try it with generated sample clips (read-only, needs ffmpeg)
./scripts/demo.sh                   # == python3 src/server.py --demo
bash scripts/make-sample-library.sh [out-dir]   # just generate the sample tree

# Checks (this is the entire CI gate — see .github/workflows/ci.yml)
python3 -m py_compile src/server.py # backend syntax
node --check src/web/app.js         # frontend syntax
# CI also boots the server and asserts GET /api/session returns "app": "Kinema"

# Release bundles (normally only via tag push, see .github/workflows/release.yml)
pyinstaller --onefile --name kinema --add-data "src/web:web" \
  --add-binary "<ffmpeg>:." --add-binary "<ffprobe>:." src/server.py

# Public read-only demo image (build context MUST be the project root)
docker compose -f deploy/docker-compose.yml up --build
```

There is **no test suite, linter config, or formatter** — the CI gate above (compile-check +
boot smoke test) is the whole bar. Keep contributions passing it and manually exercise the
relevant flows (browse, play, resume, PiP, and `--lan`/`--password`/`--read-only` when touched).

## Architecture

### Backend — [src/server.py](src/server.py) (one file)

A `ThreadingHTTPServer` with a single `BaseHTTPRequestHandler` subclass (`Handler`). There is
no router abstraction — `do_GET`/`do_POST` are long `if route == ...` chains. Every request
passes through one **security gate** before any work happens:

`Handler._guard(route, mutating)` enforces, in order:
1. **Host allow-listing** (`host_allowed`) — blocks DNS-rebinding. Only localhost + the
   machine's own names/IPs are allowed; real private LAN IPs are allowed only in `--lan` mode.
2. **CSRF check** for mutating requests (`_origin_ok`) — requires a positive same-site signal:
   the custom `X-Kinema` header (which the frontend sets on every `api()` call and a cross-site
   page cannot add without a CORS preflight the server never grants), or a same-site
   `Origin`/`Referer`.
3. **Auth** (`_authed`) — if a password is set, all routes except `PUBLIC_ROUTES` require a
   valid `kinema_session` cookie.

Mutating library routes additionally call `_require_writable()` (rejects in `--read-only`).

**Path safety is the other load-bearing invariant.** Any filesystem path coming from the
client must go through `resolve_within_roots()` (resolves symlinks/`..` and confirms the
target is inside a configured root) before use. `owning_root()` finds which root a path
belongs to. Never touch a client-supplied path without one of these — this is what prevents
path traversal. File mutations live in `op_rename` / `op_move` / `op_mkdir` / `op_delete`
(delete is a reversible move into a per-root `.kinema-trash`, never `rm`).

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

The cache key for thumbnails/metadata/remux is `path | mtime_ns | size`, so edits/replacements
auto-invalidate. Concurrency is guarded by module-level locks (`_io_lock`, `_meta_lock`,
per-key locks) and a `Semaphore` cap on simultaneous ffmpeg processes (anti fork-bomb).

**ffmpeg discovery** (`_find_tool`): explicit env override (`KINEMA_FFMPEG`/`KINEMA_FFPROBE`)
→ bundled binary near the executable or at the project root (`./`, `./bin`, `./ffmpeg`, plus
the PyInstaller `_MEIPASS` dir) → `PATH`. Everything ffmpeg-dependent degrades gracefully.

**Frozen vs. source mode.** When running as a PyInstaller bundle (`sys.frozen`), web assets
are read from the temp extract dir (`_MEIPASS`) and `STATE_DIR` is `~/.kinema`. From source,
`WEB_DIR = src/web` and `STATE_DIR = APP_DIR.parent` (the repo root) — see the path invariant
above.

### Frontend — [src/web/](src/web/) (no build step)

- [src/web/index.html](src/web/index.html) — the entire DOM up front (library view, player
  overlay, settings modal, generic dialog, login overlay), toggled via `.hidden`. Single-page app.
- [src/web/app.js](src/web/app.js) — vanilla JS, one `state` object, no framework. All server
  calls go through the `api()` helper (injects the `X-Kinema` CSRF header; on 401 with `needAuth`
  it pops the login overlay). The UI is gated by `/api/session` flags (`canManage`, `canBrowse`,
  `readonly`, `nativePicker`, `ffmpeg`) from `_session_state()` — the backend is the authority
  on capabilities; the frontend only reflects them. Thumbnails load lazily via an
  `IntersectionObserver`. Last folder and volume persist in `localStorage`.
- [src/web/style.css](src/web/style.css) — hand-written; bundled fonts in `src/web/fonts/`,
  served via the `/fonts/*.woff2` route.

### API surface (all under `/api/`)

GET: `session`, `config`, `library?path=`, `browse?path=`, `meta?path=`, `thumb?path=`,
`stream?path=` (Range + remux), `progress`, `continue`, `playlists`.
POST: `login`, `logout`, `progress`, `progress/clear`, `config`, `playlists`, `pick-folder`
(native OS dialog on the server desktop), `add-paths` (drag-and-drop), `op` (rename/move/
mkdir/delete). Static files (`/`, `/app.js`, `/style.css`, `/favicon.svg`) are served by
`_serve_static`; the app shell also carries the strict `CSP`.

## Conventions & constraints

- **Backend: Python standard library only.** No third-party runtime dependencies, ever.
- **Frontend: vanilla HTML/CSS/JS.** No framework, no bundler, no transpile.
- **Brand is the source of truth for anything visual.** Colors, gradient, fonts, radii,
  shadows, wordmark, voice — all come from [docs/BRAND.md](docs/BRAND.md) (visual deck:
  [docs/brand/kinema-brand-guidelines.html](docs/brand/kinema-brand-guidelines.html)), which
  mirrors the CSS tokens in [src/web/style.css](src/web/style.css). Don't introduce a value
  that isn't in the brand; if you change one, update `BRAND.md` and `style.css` together.
- **ffmpeg is optional** — guard every use behind a `FFMPEG`/`FFPROBE` check.
- **Security is non-negotiable**: new client-path handling goes through `resolve_within_roots`;
  new mutating routes go through `_guard(..., mutating=True)` and `_require_writable()`; any
  user/file-derived string rendered in the frontend is run through `escapeHtml`. See
  [docs/SECURITY.md](docs/SECURITY.md) for the full threat model.
- The app is built for **localhost + trusted LAN**, not a public multi-tenant service. No TLS
  and a single shared password by design.
- `APP_VERSION` in [src/server.py](src/server.py) and [docs/CHANGELOG.md](docs/CHANGELOG.md)
  are kept in sync on release; the `Release` workflow triggers on `v*` tags and builds
  per-OS PyInstaller bundles with ffmpeg baked in. `install.sh`/`install.ps1` download those
  release assets (falling back to a source run if none exist).

## Configuration (CLI flags / env vars)

Flags: `[FOLDER ...]`, `--host`, `--port`, `--lan`, `--password`, `--read-only`, `--demo`,
`--no-browse`, `--allowed-host` (repeatable), `--allow-any-host`, `--app`, `--kiosk`,
`--no-open`, `--version`.
Env equivalents read at startup: `KINEMA_PASSWORD`, `KINEMA_PORT`, `KINEMA_READONLY`,
`KINEMA_LAUNCH_MODE` (`tab`/`app`/`kiosk`), `KINEMA_CACHE_LIMIT_MB`, `KINEMA_CACHE_TTL_SEC`,
`KINEMA_ALLOWED_HOSTS`, `KINEMA_FFMPEG`, `KINEMA_FFPROBE`.

## Launchers & desktop icons

`launchers/kinema.sh` and the `.bat` files auto-detect the layout: a source checkout runs
`python3 src/server.py`; a release bundle runs the self-contained `kinema`/`kinema.exe`. They
pass all args through, so the launch mode flows in via `--app`/`--kiosk`.

`LAUNCH_MODE` (set in `main()` from `--app`/`--kiosk`/`KINEMA_LAUNCH_MODE`) drives
`_launch_browser()`: `tab` opens a normal Firefox tab (default), `app` opens a dedicated
window using a separate Firefox profile at `STATE_DIR/app-profile`, `kiosk` adds `--kiosk`.
The opt-in desktop-icon installers (`launchers/install-{linux.sh,macos.sh,windows.ps1}`) take
a `tab|app|kiosk` argument and wire the icon (logo: `launchers/kinema.png`/`.ico`, generated
from `src/web/favicon.svg`) to the launcher with that mode. macOS builds a real `Kinema.app`.
