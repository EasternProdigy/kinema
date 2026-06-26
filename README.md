<div align="center">

# 🎬 Kinema

**Your own video library, in a browser tab.**

Point Kinema at a folder of videos and watch them in your browser — with thumbnails,
resume, autoplay, and one-click **Picture-in-Picture** so an episode floats over your
work. Stream across your home network to watch on any device.

*Open source · MIT licensed · by [Pentarosa Co.](https://mezi.app) — from the makers of mezi.app*

</div>

---

## Why Kinema?

- **It's just a Firefox tab.** Pin it next to your work; pop a video out with Picture-in-Picture and it floats over everything.
- **Dead simple.** Double-click to launch. Pick a folder in your browser — no terminal, no config files.
- **Your files stay yours.** Everything runs locally. No uploads, no account, no cloud.
- **Watch anywhere at home.** One flag turns on LAN access so your phone, tablet, or TV can watch too.
- **Lean.** A single Python file (standard library only) plus a static web page. No `pip install`, no `npm install`.

## Quick start

### Easiest — one line

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/EasternProdigy/kinema/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/EasternProdigy/kinema/main/install.ps1 | iex
```

This grabs the latest release — **ffmpeg included, nothing else to install** — and opens
Kinema in your browser. Click **📂 Browse for a folder…**, pick where your shows and movies
live, and you're watching.

### Or download & double-click
Prefer not to pipe to a shell? Grab the bundle for your OS from the [Releases](../../releases)
page and **double-click**:

| OS | Double-click |
|----|--------------|
| **Linux** | `launchers/kinema.sh` (or run `bash launchers/install-linux.sh` to add it to your app menu) |
| **macOS** | `Kinema.command` |
| **Windows** | `Kinema.bat` (or `Kinema (no window).vbs` for no console) |

The release bundles include **ffmpeg**, so thumbnails work with nothing else to install.

### Try the demo (no files needed)

Want to see it first? Run the demo — Kinema generates a few sample clips and serves
them read-only:

```bash
./scripts/demo.sh               # or: python3 src/server.py --demo
```

Double-click **`Kinema Demo.command`** (macOS) / **`Kinema Demo.bat`** (Windows) to do
the same. A hosted demo can be run from the included [Dockerfile](deploy/Dockerfile).

### From source
You need **Python 3.8+**. [ffmpeg](https://ffmpeg.org/) is optional (used for thumbnails & durations).

```bash
git clone https://github.com/EasternProdigy/kinema.git
cd kinema
python3 src/server.py ~/Videos    # or just: python3 src/server.py  (add folders in the UI)
                                  # …or use the helpers:  ./scripts/run.sh   ./scripts/dev.sh
```

Open the printed URL (default <http://127.0.0.1:8000>) in Firefox.

## Make it a desktop app

Kinema lives in Firefox, but you can give it a real **desktop icon**. It's opt-in —
run the installer for your OS **once**:

| OS | Add a desktop + menu icon |
|----|---------------------------|
| **Linux** | `bash launchers/install-linux.sh` |
| **macOS** | `bash launchers/install-macos.sh`  *(builds a real `Kinema.app`)* |
| **Windows** | `powershell -ExecutionPolicy Bypass -File launchers\install-windows.ps1` |

By default the icon opens Kinema **as a new tab** in your normal Firefox (and launches
Firefox first if it's closed). Want it to feel more standalone? Add a mode:

| Mode | What you get |
|------|--------------|
| **tab** *(default)* | A new tab in your everyday Firefox |
| **app** | Its own dedicated Kinema window — separate Firefox profile, own dock/taskbar entry |
| **kiosk** | Fullscreen, no browser chrome — TV / cinema mode |

Pass the mode to the installer, e.g. `bash launchers/install-linux.sh app` (or `kiosk`).
You can also use it ad-hoc on the command line (`--app` / `--kiosk`) or set
`KINEMA_LAUNCH_MODE=app`. Launching Kinema again while it's already running just reopens
it — no second copy, no error.

## Watch on your phone / TV (LAN)

```bash
python3 src/server.py ~/Videos --lan --password "choose-a-password"
```

Kinema prints a `Network:` URL like `http://192.168.1.20:8000`. Open it on any device on
the same Wi-Fi (it's also listed under **Settings → Watch on other devices**).
**Use `--password` whenever you use `--lan`.**

## Picture-in-Picture (the whole point)

While a video plays in Firefox, click the **Picture-in-Picture** toggle Firefox shows on
the video (or press **Ctrl + Shift + ]**, or use Kinema's **⧉ PiP** button / the **P** key).
The video pops out and floats over your other tabs and apps.

## Features

- 📁 Browse any layout — flat folders, season/episode nesting, multiple shows & movies
- 🖼️ Thumbnail posters (ffmpeg), duration badges, resume-progress bars
- ⏯️ Player: speed, loop, skip ±10s, volume memory, next/prev, **autoplay-next**, fullscreen
- 🔖 **Continue watching** — resume positions saved server-side, synced across devices
- 🗂️ Organize on disk — rename, move, new folder, delete (safe move-to-trash)
- 🌐 LAN streaming with optional password
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
  --app                 open in a dedicated Kinema window (its own app window, not a tab)
  --kiosk               open fullscreen with no browser chrome (TV / cinema mode)
  --read-only           disable all file management (demo / kiosk mode)
  --no-browse           disable the in-browser folder picker
  --allowed-host HOST   extra hostname/domain allowed, repeatable (e.g. a reverse-proxy domain)
  --allow-any-host      disable Host allow-listing entirely (NOT recommended)
  --no-open             don't auto-open a browser
  --version             print the version and exit
```

Environment variables: `KINEMA_PASSWORD`, `KINEMA_PORT`, `KINEMA_READONLY`,
`KINEMA_LAUNCH_MODE` (`tab`/`app`/`kiosk`), `KINEMA_CACHE_LIMIT_MB`, `KINEMA_CACHE_TTL_SEC`,
`KINEMA_ALLOWED_HOSTS`, `KINEMA_FFMPEG`, `KINEMA_FFPROBE`.

## Security model

Kinema is built to be safe on a home network, not as a public multi-user service. See
[SECURITY.md](docs/SECURITY.md) for the full threat model. In short:

- Binds to **localhost only** unless you pass `--lan`.
- **Host & Origin checks** on every request block CSRF and DNS-rebinding attacks from other sites.
- **Optional password** gates access; file management is also disabled in **read-only** mode.
- All file access is **sandboxed** to the library folders you add — no path traversal.
- **Don't** expose Kinema directly to the public internet. If you must, put it behind a
  reverse proxy with HTTPS and a password, and use `--read-only`.

## Codecs

**Every video in your library plays and behaves the same.** Kinema streams browser-native
containers (`.mp4`, `.m4v`, `.webm`, `.mov`) directly, and for everything else (`.mkv`,
`.avi`, `.ts`, …) it **remuxes to a seekable MP4 on the fly** with the bundled ffmpeg —
a fast stream-copy when the codecs are already browser-friendly (e.g. H.264/AAC in an
`.mkv`), transcoding only what isn't. Each file is prepared once and cached under
`cache/remux/`.

Thumbnails and durations work for all formats too, because the bundled ffmpeg can decode
HEVC/H.264/etc. (Fedora's `ffmpeg-free` strips those decoders — Kinema ships its own in
`bin/`, or set `KINEMA_FFMPEG`/`KINEMA_FFPROBE`.)

> Cached remuxes are roughly the size of the source; delete `cache/remux/` to reclaim
> space. HEVC streams directly wherever your browser/GPU can decode it.

## Project layout

```
kinema/
├─ src/            the app — server.py (stdlib only) + web/ (vanilla HTML/CSS/JS)
├─ scripts/        run.sh · dev.sh · demo.sh · make-sample-library.sh
├─ launchers/      double-click launchers for Linux / macOS / Windows
├─ deploy/         Dockerfile · docker-compose.yml · .env.example
├─ docs/           CONTRIBUTING · SECURITY · CHANGELOG · NOTICE
├─ install.sh      one-line installer (macOS / Linux)
└─ install.ps1     one-line installer (Windows)
```

Runtime state (your library config, thumbnail/remux caches, an optional bundled `bin/ffmpeg`)
lives at the project root in `data/` and `cache/` — both git-ignored. Want to help out? See
[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md); release history is in [docs/CHANGELOG.md](docs/CHANGELOG.md).

## License

[MIT](LICENSE) © 2026 Pentarosa Co.
