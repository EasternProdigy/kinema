# Changelog

All notable changes to Kadmu are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
