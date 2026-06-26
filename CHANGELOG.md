# Changelog

All notable changes to Kinema are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

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
  read-only — try Kinema instantly with no files. One-click `demo.sh` /
  `Kinema Demo.command` / `Kinema Demo.bat`, and a ready-to-host Docker demo.
- **Bundled ffmpeg**: release builds ship a static ffmpeg/ffprobe so thumbnails work
  with zero install. From source, Kinema finds ffmpeg on `PATH` or via
  `KINEMA_FFMPEG`/`KINEMA_FFPROBE`. See [NOTICE.md](NOTICE.md).

### Security
- Host allow-listing + Origin/Referer checks (CSRF & DNS-rebinding protection).
- Optional password auth with `HttpOnly`, `SameSite=Strict` session cookies.
- Strict Content-Security-Policy; consistent HTML escaping.
- All filesystem access sandboxed to configured library roots.
- ffmpeg concurrency cap and request-size limits.
- Security headers: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`.
