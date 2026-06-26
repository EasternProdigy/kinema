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

### Easiest — download a release
Grab the bundle for your OS from the [Releases](../../releases) page and **double-click**:

| OS | Double-click |
|----|--------------|
| **Linux** | `launchers/kinema.sh` (or run `bash launchers/install-linux.sh` to add it to your app menu) |
| **macOS** | `Kinema.command` |
| **Windows** | `Kinema.bat` (or `Kinema (no window).vbs` for no console) |

Kinema opens in your browser. Click **📂 Browse for a folder…**, pick where your shows
and movies live, and you're watching. The release bundles include **ffmpeg**, so
thumbnails work with nothing else to install.

### Try the demo (no files needed)

Want to see it first? Run the demo — Kinema generates a few sample clips and serves
them read-only:

```bash
./demo.sh                       # or: python3 server.py --demo
```

Double-click **`Kinema Demo.command`** (macOS) / **`Kinema Demo.bat`** (Windows) to do
the same. A hosted demo can be run from the included [Dockerfile](Dockerfile).

### From source
You need **Python 3.8+**. [ffmpeg](https://ffmpeg.org/) is optional (used for thumbnails & durations).

```bash
git clone https://github.com/EasternProdigy/kinema.git
cd kinema
python3 server.py ~/Videos        # or just: python3 server.py  (add folders in the UI)
```

Open the printed URL (default <http://127.0.0.1:8000>) in Firefox.

## Watch on your phone / TV (LAN)

```bash
python3 server.py ~/Videos --lan --password "choose-a-password"
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
python3 server.py [FOLDER ...] [options]

  --demo                try it now: auto-generate sample videos, serve read-only
  --lan                 serve on your whole local network (binds 0.0.0.0)
  --password PW         require a password to access (recommended with --lan)
  --port N              port (default 8000)
  --read-only           disable all file management (demo / kiosk mode)
  --no-browse           disable the in-browser folder picker
  --allowed-host HOST   extra hostname/domain allowed (e.g. a reverse-proxy domain)
  --no-open             don't auto-open a browser
```

Environment variables: `KINEMA_PASSWORD`, `KINEMA_PORT`, `KINEMA_READONLY`,
`KINEMA_ALLOWED_HOSTS`, `KINEMA_FFMPEG`, `KINEMA_FFPROBE`.

## Security model

Kinema is built to be safe on a home network, not as a public multi-user service. See
[SECURITY.md](SECURITY.md) for the full threat model. In short:

- Binds to **localhost only** unless you pass `--lan`.
- **Host & Origin checks** on every request block CSRF and DNS-rebinding attacks from other sites.
- **Optional password** gates access; file management is also disabled in **read-only** mode.
- All file access is **sandboxed** to the library folders you add — no path traversal.
- **Don't** expose Kinema directly to the public internet. If you must, put it behind a
  reverse proxy with HTTPS and a password, and use `--read-only`.

## Codecs

Browsers play **MP4 (H.264/AAC)** and **WebM** natively. Other containers (`.mkv`, `.avi`, …)
are listed and flagged but may not play. Convert if needed:

```bash
ffmpeg -i input.mkv -c:v libx264 -c:a aac output.mp4
# (no libx264? use -c:v libopenh264 -b:v 2M)
```

## License

[MIT](LICENSE) © 2026 Pentarosa Co.
