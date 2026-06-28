<div align="center">

# 🎬 Kadmu

**Your own video library, in a browser tab.**

Point Kadmu at a folder of videos and watch them in your browser — with thumbnails,
resume, autoplay, and one-click **Picture-in-Picture** so an episode floats over your
work. Stream across your home network to watch on any device.

*Open source · MIT licensed · by [Pentarosa Co.](https://mezi.app) — from the makers of mezi.app*

</div>

---

## Why Kadmu?

- **It's just a Firefox tab.** Pin it next to your work; pop a video out with Picture-in-Picture and it floats over everything.
- **Dead simple.** Double-click to launch. Pick a folder in your browser — no terminal, no config files.
- **Your files stay yours.** Everything runs locally. No uploads, no account, no cloud.
- **Watch anywhere at home.** One flag turns on LAN access so your phone, tablet, or TV can watch too.
- **Lean.** A single Python file (standard library only) plus a static web page. No `pip install`, no `npm install`.

## Quick start

### Easiest — one line

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/EasternProdigy/kadmu/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/EasternProdigy/kadmu/main/install.ps1 | iex
```

This grabs the latest release — **ffmpeg included, nothing else to install** — and opens
Kadmu in your browser. Click **📂 Browse for a folder…**, pick where your shows and movies
live, and you're watching.

### Or download & double-click
Prefer not to pipe to a shell? Grab the bundle for your OS from the [Releases](../../releases)
page and **double-click**:

| OS | Double-click |
|----|--------------|
| **Linux** | `launchers/kadmu.sh` (or run `bash launchers/install-linux.sh` to add it to your app menu) |
| **macOS** | `Kadmu.command` |
| **Windows** | `Kadmu.bat` (or `Kadmu (no window).vbs` for no console) |

The release bundles include **ffmpeg**, so thumbnails work with nothing else to install.

### Try the demo (no files needed)

Want to see it first? Run the demo — Kadmu generates a few sample clips and serves
them read-only:

```bash
./scripts/demo.sh               # or: python3 src/server.py --demo
```

Double-click **`Kadmu Demo.command`** (macOS) / **`Kadmu Demo.bat`** (Windows) to do
the same. A hosted demo can be run from the included [Dockerfile](deploy/Dockerfile).

### From source
You need **Python 3.8+**. [ffmpeg](https://ffmpeg.org/) is optional (used for thumbnails & durations).

```bash
git clone https://github.com/EasternProdigy/kadmu.git
cd kadmu
python3 src/server.py ~/Videos    # or just: python3 src/server.py  (add folders in the UI)
                                  # …or use the helpers:  ./scripts/run.sh   ./scripts/dev.sh
```

Open the printed URL (default <http://127.0.0.1:8000>) in Firefox.

## Make it a desktop app

Kadmu lives in Firefox, but you can give it a real **desktop icon**. It's opt-in —
run the installer for your OS **once**:

| OS | Add a desktop + menu icon |
|----|---------------------------|
| **Linux** | `bash launchers/install-linux.sh` |
| **macOS** | `bash launchers/install-macos.sh`  *(builds a real `Kadmu.app`)* |
| **Windows** | `powershell -ExecutionPolicy Bypass -File launchers\install-windows.ps1` |

By default the icon opens Kadmu **as a new tab** in your normal Firefox (and launches
Firefox first if it's closed). Want it to feel more standalone? Add a mode:

| Mode | What you get |
|------|--------------|
| **tab** *(default)* | A new tab in your everyday Firefox |
| **app** | Its own dedicated Kadmu window — separate Firefox profile, own dock/taskbar entry |
| **kiosk** | Fullscreen, no browser chrome — TV / cinema mode |

Pass the mode to the installer, e.g. `bash launchers/install-linux.sh app` (or `kiosk`).
You can also use it ad-hoc on the command line (`--app` / `--kiosk`) or set
`KADMU_LAUNCH_MODE=app`. Launching Kadmu again while it's already running just reopens
it — no second copy, no error.

## Watch on your phone / TV (LAN)

```bash
python3 src/server.py ~/Videos --lan --password "choose-a-password"
```

Kadmu prints a `Network:` URL like `http://192.168.1.20:8000`. Open it on any device on
the same Wi-Fi (it's also listed under **Settings → Watch on other devices**).
**Use `--password` whenever you use `--lan`.**

## Picture-in-Picture (the whole point)

While a video plays in Firefox, click the **Picture-in-Picture** toggle Firefox shows on
the video (or press **Ctrl + Shift + ]**, or use Kadmu's **⧉ PiP** button / the **P** key).
The video pops out and floats over your other tabs and apps.

## Features

- 📁 Browse any layout — flat folders, season/episode nesting, multiple shows & movies
- 🖼️ Thumbnail posters (ffmpeg), duration badges, resume-progress bars
- ⏯️ Player: speed, loop, skip ±10s, volume memory, next/prev, **autoplay-next**, fullscreen
- 🔖 **Continue watching** — resume positions saved server-side, synced across devices
- 🗂️ Organize on disk — rename, move, new folder, delete (safe move-to-trash)
- 🌐 LAN streaming with optional password
- 👥 Optional **multi-user accounts** (`--accounts`) — per-person resume, My List & playlists,
  with admin/viewer roles; off by default (one shared password)
- 🔒 Read-only / kiosk mode for shared or demo instances

## Keyboard shortcuts (in the player)

`Space`/`k` play·pause · `←`/`→` skip 10s · `↑`/`↓` volume · `m` mute · `f` fullscreen ·
`l` loop · `p` PiP · `Shift+N` / `Shift+P` next/prev · `[` / `]` slower/faster · `Esc` close

## Command-line options

```
python3 src/server.py [FOLDER ...] [options]

  --demo                try it now: auto-generate sample videos, serve read-only
  --lan                 serve on your whole local network (binds 0.0.0.0)
  --password PW         require a password to access (recommended with --lan)
  --host ADDR           bind address (default 127.0.0.1; 0.0.0.0 with --lan)
  --port N              port (default 8000)
  --app                 open in a dedicated Kadmu window (its own app window, not a tab)
  --kiosk               open fullscreen with no browser chrome (TV / cinema mode)
  --read-only           disable all file management (demo / kiosk mode)
  --no-browse           disable the in-browser folder picker
  --accounts            enable multi-user accounts (sign-in, per-user data, admin/viewer roles)
  --reset-password USER reset/create USER as admin from the console, then exit
  --allowed-host HOST   extra hostname/domain allowed, repeatable (e.g. a reverse-proxy domain)
  --allow-any-host      disable Host allow-listing entirely (NOT recommended)
  --no-open             don't auto-open a browser
  --version             print the version and exit
```

Environment variables: `KADMU_PASSWORD`, `KADMU_PORT`, `KADMU_READONLY`, `KADMU_ACCOUNTS`,
`KADMU_NEW_PASSWORD` (for `--reset-password`),
`KADMU_LAUNCH_MODE` (`tab`/`app`/`kiosk`), `KADMU_CACHE_LIMIT_MB`, `KADMU_CACHE_TTL_SEC`,
`KADMU_ALLOWED_HOSTS`, `KADMU_FFMPEG`, `KADMU_FFPROBE`.

### Multi-user accounts (optional)

By default Kadmu is one shared library with one optional password. Run with `--accounts` to
give everyone their own sign-in instead:

```
python3 src/server.py ~/Videos --accounts          # add --lan to share on your network
```

The first person to open the page creates the **owner** account (an admin). Admins manage the
library and people from **Settings ▸ People** (add users, set admin/viewer roles, reset
passwords, and open/close self-sign-up); everyone gets their own resume points, My List and
playlists, and can change their name/password under **Settings ▸ Your account**. Accounts live
in an embedded SQLite database (`data/kadmu.db`) — still no `pip install`, all standard library.
Locked out? `python3 src/server.py --reset-password yourname` prints a fresh admin password.

## Security model

Kadmu is built to be safe on a home network, not as a public multi-user service. See
[SECURITY.md](docs/SECURITY.md) for the full threat model. In short:

- Binds to **localhost only** unless you pass `--lan`.
- **Host & Origin checks** on every request block CSRF and DNS-rebinding attacks from other sites.
- **Optional password** (or full **accounts** with `--accounts`) gates access; file management
  is admin-only with accounts, and disabled entirely in **read-only** mode.
- All file access is **sandboxed** to the library folders you add — no path traversal.
- **Don't** expose Kadmu directly to the public internet. If you must, put it behind a
  reverse proxy with HTTPS and a password, and use `--read-only`.

## Codecs

**Every video in your library plays and behaves the same.** Kadmu streams browser-native
containers (`.mp4`, `.m4v`, `.webm`, `.mov`) directly, and for everything else (`.mkv`,
`.avi`, `.ts`, …) it **remuxes to a seekable MP4 on the fly** with the bundled ffmpeg —
a fast stream-copy when the codecs are already browser-friendly (e.g. H.264/AAC in an
`.mkv`), transcoding only what isn't. Each file is prepared once and cached under
`cache/remux/`.

Thumbnails and durations work for all formats too, because the bundled ffmpeg can decode
HEVC/H.264/etc. (Fedora's `ffmpeg-free` strips those decoders — Kadmu ships its own in
`bin/`, or set `KADMU_FFMPEG`/`KADMU_FFPROBE`.)

> Cached remuxes are roughly the size of the source; delete `cache/remux/` to reclaim
> space. HEVC streams directly wherever your browser/GPU can decode it.

## Project layout

```
kadmu/
├─ src/            the app — server.py (stdlib only) + web/ (vanilla HTML/CSS/JS)
├─ scripts/        run.sh · dev.sh · demo.sh · make-sample-library.sh
├─ launchers/      double-click launchers for Linux / macOS / Windows
├─ deploy/         Dockerfile · docker-compose.yml · .env.example
├─ cloud/          the (optional) hosted layer — NOT needed to self-host
├─ docs/           start at docs/README.md (the doc index)
├─ install.sh      one-line installer (macOS / Linux)
└─ install.ps1     one-line installer (Windows)
```

Runtime state (your library config, thumbnail/remux caches, an optional bundled `bin/ffmpeg`)
lives at the project root in `data/` and `cache/` — both git-ignored.

## Documentation

All docs live in **[docs/](docs/README.md)** — start with the index. Highlights:
[CONTRIBUTING](docs/CONTRIBUTING.md) · [SECURITY](docs/SECURITY.md) ·
[CHANGELOG](docs/CHANGELOG.md) (what shipped) · [ROADMAP](docs/ROADMAP.md) (vision & future
plans). The optional hosted edition ("Kadmu Cloud") is documented under
[cloud/](cloud/README.md), with its go-live steps in [docs/LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md).

## License

[MIT](LICENSE) © 2026 Pentarosa Co.
