# Remote & cloud storage — stream media you keep elsewhere

Kadmu is a **streaming front-end for the media you already own** — and "own" doesn't
have to mean "on this disk." You can keep your shows and movies on Dropbox, Google
Drive, MEGA, an S3 bucket (Backblaze B2 / Wasabi / Cloudflare R2), a NAS, or your own
server, and still browse and watch them through Kadmu.

This keeps the project's promise intact: **your video never touches anyone else's
servers.** The Kadmu node (the machine running `python3 src/server.py`) pulls the bytes
from your storage and streams them straight to your browser — or peer-to-peer over Kadmu
Cloud. No middle-man, no egress bill, no DMCA-storage liability.

There are two ways to attach remote storage. **Tier 1 (this guide) works today on any
release** and covers every provider. **Tier 2** (a native "remote source" you configure
inside Kadmu, no mounting) is on the roadmap — see [ROADMAP.md](ROADMAP.md).

---

## Tier 1 — mount it as a folder, then point Kadmu at it

Kadmu watches **local folders**. So the universal recipe is:

1. **Surface** the remote storage as a folder on the Kadmu machine (with the provider's
   desktop app, or [rclone](https://rclone.org)).
2. **Add that folder** in Kadmu → *Settings → Library folders → Add cloud / remote
   storage…* (or just paste the path under "type a path manually").

That's it. From Kadmu's point of view it's an ordinary folder, so thumbnails, resume,
search, the Netflix-style catalog, transcoding — everything works.

> **Why mounting (and not a built-in connector for each app)?** It's what mature
> self-hosted players (Jellyfin, Plex) recommend, for good reasons: Kadmu's playback
> needs *random access* (HTTP byte-ranges, ffmpeg seeking, thumbnail/storyboard frames).
> A mount with a local cache gives ffmpeg exactly that. It also keeps the backend
> **standard-library-only** — no per-provider SDKs to install or maintain.

### The fastest path per provider

| Provider | Easiest mount | Notes |
|---|---|---|
| **Google Drive** | "Google Drive for desktop" app | Appears as a drive/folder. Mark media **Available offline** for smooth seeking. |
| **Dropbox** | Dropbox desktop app | Creates a `Dropbox` folder. Use **Make available offline** on your media folder. |
| **MEGA** | MEGAsync app, **or** `rclone mount mega:` | MEGA is end-to-end encrypted — there is **no** app-less native link (see below). |
| **S3 / B2 / Wasabi / R2** | `rclone mount` with `--vfs-cache-mode full` | The cache is what makes seeking/transcoding feel local. |
| **Your own server** | SMB/NFS network drive, `sshfs`, WebDAV, or `rclone` | A LAN NAS is near-local speed. |
| **OneDrive, pCloud, Box, Proton Drive, …** | `rclone` (70+ backends) | If it can be a folder, Kadmu can stream it. |

### rclone in three commands (covers almost everything)

```bash
# 1. one-time: add your remote (interactive)
rclone config

# 2. mount it as a folder, with a cache so seeking/transcoding is smooth
rclone mount myremote:Media ~/kadmu-media --vfs-cache-mode full

# 3. in Kadmu, add  ~/kadmu-media  as a library folder.  Done.
```

To survive reboots, run the mount as a service (a systemd unit on Linux, a Launch Agent
on macOS, or `rclone` + WinFsp as a Windows service). See rclone's docs for the snippets.

### Tips for a good experience over the network

- **Cache aggressively.** rclone's `--vfs-cache-mode full` (plus a generous
  `--vfs-cache-max-size`) means the first watch fills the cache and re-watches/seeks are
  instant. Desktop apps: use their "available offline" toggle on the media folder.
- **First play has fetch latency.** Streaming a title that isn't cached yet pulls it on
  demand — expect a short buffer at the start and on big seeks. LAN/NAS shares barely
  notice; far-away cloud benefits most from the cache.
- **Watch provider limits.** Google Drive has daily download quotas; some APIs
  rate-limit. rclone backs off automatically, but heavy first-time scanning of a huge
  library can be throttled.
- **Pair with archiving.** Combine remote storage (*offload* the bytes off your local
  disk) with the planned **Archive** feature (*shrink* finished shows) for a complete
  "stop letting media eat my disk" story.

---

## Why MEGA (and any E2E-encrypted store) needs a mount

MEGA encrypts your files end-to-end, so a client must **decrypt** them to play them.
Python's standard library has **no symmetric cipher (no AES)**, and Kadmu's backend is
standard-library-only by design — so a built-in, app-less MEGA reader isn't possible
without violating that rule. MEGAsync (or `rclone`, which bundles the crypto) does the
decryption and hands Kadmu a plain folder. That's the supported path, and the UI says so.

---

## Tier 2 — native remote sources (roadmap)

A future increment lets you add a **remote source inside Kadmu** — no mounting — for the
storage that speaks plain HTTP:

- **Your own server** (HTTP with byte-range, or WebDAV)
- **S3-compatible** object storage (R2 / B2 / Wasabi / MinIO)
- **Google Drive / Dropbox** (their REST APIs + OAuth)

These are all "HTTP with range requests," which the backend can do with `urllib` +
`hmac`/`hashlib` — **still no third-party dependencies**. Kadmu would list the source,
range-proxy playback through the node, and feed ffmpeg the (signed) URL directly, with a
small local cache for thumbnails and seeking. MEGA stays Tier-1-only, for the reason
above. Tracked in [ROADMAP.md](ROADMAP.md).
