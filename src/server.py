#!/usr/bin/env python3
"""Kinema - a personal cinema in a browser tab.

A lean, cross-platform, self-hosted web app for browsing and watching your own
video library in the browser. Built to pair with Firefox's Picture-in-Picture so
you can pop an episode out over your other tabs, and to stream across your home
network (LAN) so you can watch from any device.

Open source, MIT licensed. Copyright (c) 2026 Pentarosa Co.
From the makers of mezi.app.

Standard library only (no pip installs). Uses ffmpeg/ffprobe (if present) for
thumbnails and metadata.

    python3 server.py ~/Videos              # local only
    python3 server.py ~/Videos --lan        # also reachable on your home network
    python3 server.py ~/Videos --lan --password hunter2   # LAN + login

Then open the printed URL in Firefox.
"""

from __future__ import annotations  # lazy annotations: 3.8+ compatible, zero runtime cost

import argparse
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

APP_NAME = "Kinema"
APP_VERSION = "1.0.0"

# --------------------------------------------------------------------------- #
# Paths & constants
# --------------------------------------------------------------------------- #
APP_DIR = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    # Running from a PyInstaller bundle: web assets live in the temp extract
    # dir, but config/cache must persist in a real user-writable location.
    WEB_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR)) / "web"
    STATE_DIR = Path.home() / ".kinema"
else:
    # Running from source: web assets sit next to this file (src/web), but
    # runtime state (config, caches, the bundled bin/ffmpeg) lives at the
    # project root, one level up from src/.
    WEB_DIR = APP_DIR / "web"
    STATE_DIR = APP_DIR.parent
DATA_DIR = STATE_DIR / "data"
CACHE_DIR = STATE_DIR / "cache" / "thumbs"
REMUX_DIR = STATE_DIR / "cache" / "remux"

# Hard ceiling on the prepared-video cache (remux + quality copies). Whenever a
# new file is cached we evict the least-recently-used ones until the folder is
# back under this size, so the cache can never grow without bound and fill the
# disk. Override with KINEMA_CACHE_LIMIT_MB (e.g. 512 for a small laptop, 0 to
# keep only the file in use). Default: 2 GiB.
try:
    CACHE_MAX_BYTES = max(0, int(os.environ.get("KINEMA_CACHE_LIMIT_MB", "2048"))) * 1024 * 1024
except ValueError:
    CACHE_MAX_BYTES = 2048 * 1024 * 1024

# A regular janitor deletes prepared files no one has touched in CACHE_TTL seconds,
# so the cache holds essentially just what you're watching now and clears the rest.
# The file currently streaming (and the most-recent one) is always kept, so pausing
# is safe. Override with KINEMA_CACHE_TTL_SEC. Default: 5 minutes; swept every 60s.
try:
    CACHE_TTL = max(0, int(os.environ.get("KINEMA_CACHE_TTL_SEC", "300")))
except ValueError:
    CACHE_TTL = 300
CACHE_SWEEP_INTERVAL = 60

CONFIG_PATH = DATA_DIR / "config.json"
PROGRESS_PATH = DATA_DIR / "progress.json"
PLAYLISTS_PATH = DATA_DIR / "playlists.json"
MYLIST_PATH = DATA_DIR / "mylist.json"
META_CACHE_PATH = DATA_DIR / "meta_cache.json"

TRASH_DIRNAME = ".kinema-trash"

NATIVE_EXTS = {".mp4", ".m4v", ".webm", ".mov", ".ogv", ".ogg"}
VIDEO_EXTS = NATIVE_EXTS | {".mkv", ".avi", ".wmv", ".flv", ".ts", ".m2ts", ".mpg", ".mpeg", ".3gp"}
# Sidecar subtitle files (next to the video) the player can show as captions.
SUBTITLE_EXTS = {".vtt", ".srt"}

# Codecs browsers can play directly inside MP4, so non-native containers holding
# them only need a fast stream-copy remux (no re-encode).
NATIVE_VCODECS = {"h264", "av1", "vp9", "vp8"}
NATIVE_ACODECS = {"aac", "mp3", "opus", "vorbis", "flac"}

# A video counts as "watched"/finished once you're at least this far through it.
WATCHED_FRAC = 0.95

MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
    ".mov": "video/quicktime", ".ogv": "video/ogg", ".ogg": "video/ogg",
    ".mkv": "video/x-matroska", ".avi": "video/x-msvideo", ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv", ".ts": "video/mp2t", ".m2ts": "video/mp2t",
    ".mpg": "video/mpeg", ".mpeg": "video/mpeg", ".3gp": "video/3gpp",
}

# On-the-fly quality ladder for the player's resolution picker: target height ->
# (video bitrate, bufsize). Only heights *below* a video's native height are ever
# offered, so we downscale but never upscale. 2160 = "4K".
TRANSCODE_LADDER = {
    240:  ("400k", "800k"),
    360:  ("700k", "1400k"),
    480:  ("1200k", "2400k"),
    720:  ("2500k", "5000k"),
    1080: ("4500k", "9000k"),
    2160: ("12000k", "24000k"),
}

def _find_tool(name, env_var):
    """Locate ffmpeg/ffprobe: explicit override, then bundled, then PATH."""
    override = os.environ.get(env_var)
    if override and Path(override).exists():
        return override
    exe = name + (".exe" if os.name == "nt" else "")
    # APP_DIR = src/ (or the bundle); STATE_DIR = project root, where a
    # downloaded static bin/ffmpeg lives when running from source.
    search = [APP_DIR, STATE_DIR, Path(sys.executable).resolve().parent]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        search.append(Path(mei))
    for base in search:
        for d in (base, base / "bin", base / "ffmpeg"):
            cand = d / exe
            if cand.exists():
                return str(cand)
    return shutil.which(name)


FFMPEG = _find_tool("ffmpeg", "KINEMA_FFMPEG")
FFPROBE = _find_tool("ffprobe", "KINEMA_FFPROBE")

_io_lock = threading.Lock()
_meta_lock = threading.Lock()
_thumb_locks: dict[str, threading.Lock] = {}
_thumb_locks_guard = threading.Lock()
_cache_prune_lock = threading.Lock()
# Prepared-cache files currently being streamed (path -> open-stream count). The
# janitor never deletes one of these, so a sweep can't pull a file out from under
# a playing video.
_cache_active: dict[str, int] = {}
_cache_active_lock = threading.Lock()
# Cap simultaneous ffmpeg processes so a flood of thumbnail requests can't
# fork-bomb the box.
_ffmpeg_sem = threading.Semaphore(2)


def _cache_acquire(p):
    with _cache_active_lock:
        _cache_active[p] = _cache_active.get(p, 0) + 1


def _cache_release(p):
    with _cache_active_lock:
        n = _cache_active.get(p, 0) - 1
        if n <= 0:
            _cache_active.pop(p, None)
        else:
            _cache_active[p] = n


def _cache_active_paths():
    with _cache_active_lock:
        return set(_cache_active)

# --------------------------------------------------------------------------- #
# Runtime security configuration (populated in main())
# --------------------------------------------------------------------------- #
# Access password, stored as a salted SHA-256 hash so it survives restarts and is
# never kept in clear. Both None => no password is required.
PW_SALT = None
PW_HASH = None
READONLY = False         # disables all write/file operations (demo / kiosk)
ALLOW_BROWSE = True      # server-side directory picker enabled
LAN_MODE = False         # allow private-IP Host headers
ALLOW_ANY_HOST = False   # escape hatch: disable Host allow-listing
DEMO_ROOT = None         # when set (--demo), the only library root, served read-only
LAUNCH_MODE = "tab"      # how to open the browser: "tab" | "app" | "kiosk"
ALLOWED_HOSTS: set[str] = set()
PORT = 8000              # port we serve on (used to build the share URLs)
BIND_HOST = "0.0.0.0"    # socket bind address
LAN_TOGGLEABLE = False   # True when the bind address can reach the LAN (wildcard bind)
SESSIONS: dict[str, float] = {}        # token -> expiry timestamp
SESSIONS_LOCK = threading.Lock()
SESSION_TTL = 30 * 24 * 3600           # 30 days, matches the cookie Max-Age
SESSION_MAX = 1000                     # hard cap so the set can't grow unbounded

# Per-IP login throttling (online brute-force protection)
LOGIN_LOCK: dict[str, dict] = {}
LOGIN_LOCK_GUARD = threading.Lock()
LOGIN_MAX_FAILS = 5

# Routes reachable WITHOUT authentication (so the login screen can load).
PUBLIC_ROUTES = {
    "/", "/index.html", "/app.js", "/qr.js", "/style.css", "/favicon.svg",
    "/api/session", "/api/login",
}


# --------------------------------------------------------------------------- #
# JSON store helpers (atomic, lock-guarded)
# --------------------------------------------------------------------------- #
def load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def get_config():
    cfg = load_json(CONFIG_PATH, {})
    cfg.setdefault("roots", [])
    return cfg


def set_config(cfg):
    with _io_lock:
        save_json(CONFIG_PATH, cfg)


# real_roots() is hit on nearly every request (via resolve_within_roots/owning_root),
# so cache the resolved list and only rebuild when config.json actually changes.
_roots_cache: list | None = None
_roots_sig = None
_roots_lock = threading.Lock()


def real_roots():
    if DEMO_ROOT is not None:
        return [DEMO_ROOT]
    global _roots_cache, _roots_sig
    try:
        st = CONFIG_PATH.stat()
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        sig = None
    with _roots_lock:
        if _roots_cache is not None and sig == _roots_sig:
            return _roots_cache
        roots = []
        for r in get_config().get("roots", []):
            p = Path(r).expanduser()
            try:
                p = p.resolve()
            except OSError:
                continue
            if p.is_dir():
                roots.append(p)
        _roots_cache, _roots_sig = roots, sig
        return roots


# --------------------------------------------------------------------------- #
# Path safety
# --------------------------------------------------------------------------- #
def resolve_within_roots(raw_path: str, must_exist=True):
    """Resolve a client path and ensure it lives inside a configured root."""
    if raw_path is None:
        return None
    try:
        target = Path(raw_path).expanduser().resolve()
    except OSError:
        return None
    for root in real_roots():
        if target == root or root in target.parents:
            if must_exist and not target.exists():
                return None
            return target
    return None


def owning_root(path: Path):
    for root in real_roots():
        if path == root or root in path.parents:
            return root
    return None


# --------------------------------------------------------------------------- #
# Host / Origin / auth helpers (CSRF + DNS-rebinding protection)
# --------------------------------------------------------------------------- #
def local_hostnames():
    names = {"localhost", "127.0.0.1", "::1"}
    try:
        host = socket.gethostname()
        names.add(host.lower())
        for info in socket.getaddrinfo(host, None):
            names.add(str(info[4][0]).lower())
    except OSError:
        pass
    # primary outbound interface IP (best-effort, no traffic actually sent)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # TEST-NET-1, unroutable
        names.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return {n for n in names if n}


def _host_part(value: str):
    """Extract a lowercase hostname from a Host/Origin/Referer value."""
    if not value:
        return ""
    v = value.strip()
    if "://" in v:                       # Origin / Referer
        v = urlparse(v).hostname or ""
        return v.lower()
    # Host header: strip port, handle [::1]:8000
    if v.startswith("["):
        return v[1:v.index("]")].lower() if "]" in v else v.lower()
    return v.rsplit(":", 1)[0].strip().lower()


def host_allowed(host_header: str):
    if ALLOW_ANY_HOST:
        return True
    h = _host_part(host_header)
    if not h:
        return False
    if h in ALLOWED_HOSTS:
        return True
    if LAN_MODE:
        try:
            ip = ipaddress.ip_address(h)
            if ip.is_loopback:
                return True
            # real private LAN addresses only — not 0.0.0.0 or link-local noise
            if ip.is_private and not ip.is_unspecified and not ip.is_link_local:
                return True
        except ValueError:
            pass
    return False


def peer_allowed(ip):
    """Network-level gate, checked at accept() time on the REAL TCP peer address
    (unspoofable, unlike the Host header). Loopback is always allowed; private-LAN
    peers only while network sharing is on; everything when Host allow-listing is
    disabled. This is what lets the in-app LAN toggle take effect without rebinding
    the socket: we always bind 0.0.0.0 and decide here who actually gets served."""
    if ALLOW_ANY_HOST:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    if LAN_MODE and addr.is_private and not addr.is_unspecified and not addr.is_link_local:
        return True
    return False


def parse_cookies(header: str):
    out = {}
    for part in (header or "").split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            out[k.strip()] = v.strip()
    return out


def new_session():
    tok = secrets.token_urlsafe(32)
    now = time.time()
    with SESSIONS_LOCK:
        # evict expired tokens, then enforce the cap
        for t in [t for t, exp in SESSIONS.items() if exp <= now]:
            SESSIONS.pop(t, None)
        if len(SESSIONS) >= SESSION_MAX:
            SESSIONS.pop(min(SESSIONS, key=SESSIONS.get), None)
        SESSIONS[tok] = now + SESSION_TTL
    return tok


def session_valid(tok):
    if not tok:
        return False
    now = time.time()
    with SESSIONS_LOCK:
        exp = SESSIONS.get(tok)
        if exp is None:
            return False
        if exp <= now:
            SESSIONS.pop(tok, None)
            return False
        return True


def login_check(ip):
    """Returns (allowed, retry_after_seconds)."""
    now = time.time()
    with LOGIN_LOCK_GUARD:
        rec = LOGIN_LOCK.get(ip)
        if rec and rec["until"] > now:
            return False, int(rec["until"] - now) + 1
    return True, 0


def login_fail(ip):
    now = time.time()
    with LOGIN_LOCK_GUARD:
        if len(LOGIN_LOCK) > 4096:
            LOGIN_LOCK.clear()
        rec = LOGIN_LOCK.get(ip) or {"fails": 0, "until": 0}
        rec["fails"] += 1
        if rec["fails"] >= LOGIN_MAX_FAILS:
            rec["until"] = now + min(2 ** (rec["fails"] - LOGIN_MAX_FAILS), 300)
        LOGIN_LOCK[ip] = rec


def login_ok(ip):
    with LOGIN_LOCK_GUARD:
        LOGIN_LOCK.pop(ip, None)


# --------------------------------------------------------------------------- #
# ffprobe metadata (cached by path + mtime + size)
# --------------------------------------------------------------------------- #
# The metadata cache is read once per file when listing a directory, so re-reading
# meta_cache.json from disk on every lookup made browsing O(videos x cache_size).
# Keep it in memory (this is the single writer) and persist on change only.
_meta_mem: dict | None = None


def _meta_all():
    global _meta_mem
    if _meta_mem is None:
        _meta_mem = load_json(META_CACHE_PATH, {})
        if not isinstance(_meta_mem, dict):
            _meta_mem = {}
    return _meta_mem


def _meta_snapshot():
    """A reference to the in-memory cache for bulk read-only lookups (browsing)."""
    with _meta_lock:
        return _meta_all()


def _meta_cache_get(key):
    with _meta_lock:
        return _meta_all().get(key)


def _meta_cache_put(key, value):
    global _meta_mem
    with _meta_lock:
        cache = _meta_all()
        cache[key] = value
        if len(cache) > 20000:
            cache = dict(list(cache.items())[-10000:])
            _meta_mem = cache
        save_json(META_CACHE_PATH, cache)


def cache_key(p: Path):
    try:
        st = p.stat()
    except OSError:
        return None
    return f"{p}|{st.st_mtime_ns}|{st.st_size}"


def probe_meta(path: Path):
    key = cache_key(path)
    if not key:
        return {}
    cached = _meta_cache_get(key)
    if cached is not None:
        return cached
    meta = {"duration": None, "width": None, "height": None, "vcodec": None, "acodec": None}
    if FFPROBE:
        cmd = [FFPROBE, "-v", "quiet", "-print_format", "json",
               "-show_format", "-show_streams", "--", str(path)]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=30)
            info = json.loads(out.stdout or b"{}")
            fmt = info.get("format", {})
            if fmt.get("duration"):
                meta["duration"] = float(fmt["duration"])
            for s in info.get("streams", []):
                if s.get("codec_type") == "video" and meta["width"] is None:
                    meta["width"] = s.get("width")
                    meta["height"] = s.get("height")
                    meta["vcodec"] = s.get("codec_name")
                elif s.get("codec_type") == "audio" and meta["acodec"] is None:
                    meta["acodec"] = s.get("codec_name")
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, ValueError):
            pass
    _meta_cache_put(key, meta)
    return meta


# --------------------------------------------------------------------------- #
# Thumbnails (generated on demand, cached on disk)
# --------------------------------------------------------------------------- #
def _thumb_lock_for(key):
    with _thumb_locks_guard:
        # Bound growth over a long session: these per-file locks are recreated
        # lazily, so dropping the table only risks a rare duplicate ffmpeg run
        # (the on-disk cache recheck makes that harmless), never corruption.
        if len(_thumb_locks) > 4096:
            _thumb_locks.clear()
        lock = _thumb_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _thumb_locks[key] = lock
        return lock


def thumb_path(path: Path):
    key = cache_key(path)
    if not key:
        return None, None
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.jpg", digest


def _ok_jpg(p):
    try:
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


def generate_thumb(path: Path):
    out, digest = thumb_path(path)
    if out is None:
        return None
    if _ok_jpg(out):
        return out
    if not FFMPEG:
        return None
    lock = _thumb_lock_for(digest)
    with lock:
        if _ok_jpg(out):
            return out
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ts = 3.0
        dur = probe_meta(path).get("duration")
        if dur and dur > 2:
            ts = max(1.0, min(dur * 0.2, dur - 1.0))
        scale = "scale=480:-2"
        # Increasingly robust strategies so any decodable container yields a frame:
        #  1) fast input-seek to ~20% (cheap, works for most files),
        #  2) the `thumbnail` filter decoded from the start (handles containers that
        #     don't fast-seek cleanly, e.g. some .ts/.avi),
        #  3) just the very first decodable frame (last resort).
        attempts = [
            [FFMPEG, "-nostdin", "-ss", str(ts), "-i", str(path), "-frames:v", "1",
             "-vf", scale, "-q:v", "4", "-an", "-y", "--", str(out)],
            [FFMPEG, "-nostdin", "-i", str(path), "-vf", f"thumbnail,{scale}",
             "-frames:v", "1", "-q:v", "4", "-an", "-y", "--", str(out)],
            [FFMPEG, "-nostdin", "-i", str(path), "-frames:v", "1",
             "-vf", scale, "-q:v", "4", "-an", "-y", "--", str(out)],
        ]
        for cmd in attempts:
            with _ffmpeg_sem:
                try:
                    subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=120)
                except (subprocess.SubprocessError, OSError):
                    continue
            if _ok_jpg(out):
                return out
        # never leave a 0-byte file cached (it'd block future attempts)
        if out.exists() and out.stat().st_size == 0:
            out.unlink(missing_ok=True)
        return None


def prune_cache(directory: Path, max_bytes: int, ttl=None):
    """Keep the prepared-video cache lean. Deletes (a) idle files older than `ttl`
    seconds — so the cache holds little more than what you're watching now — and
    (b), as a backstop, the least-recently-used files once the folder exceeds
    `max_bytes`. Files currently being streamed and the single most-recent file are
    always kept, so whatever you're watching survives (pausing included). Deleting a
    file another request is still streaming is safe on POSIX (the open handle keeps
    the data alive); on Windows a locked file is simply skipped."""
    with _cache_prune_lock:
        entries = []
        try:
            for e in os.scandir(directory):
                if not e.is_file() or e.name.endswith(".tmp.mp4"):
                    continue
                try:
                    st = e.stat()
                except OSError:
                    continue
                entries.append([st.st_mtime, st.st_size, e.path])
        except OSError:
            return
        if not entries:
            return
        entries.sort()                       # oldest first; newest is last
        keep = {entries[-1][2]} | _cache_active_paths()   # current/active video stays

        def _drop(path, size):
            try:
                os.remove(path)
                return size
            except OSError:
                return 0                     # in use / already gone — skip it

        total = sum(size for _m, size, _p in entries)
        # (a) time-based: evict anything no one has touched in a while
        if ttl is not None and ttl >= 0:
            now = time.time()
            for row in entries:
                _mtime, size, path = row
                if path in keep or now - _mtime <= ttl:
                    continue
                total -= _drop(path, size)
                row[1] = -1                  # mark removed so pass (b) skips it
        # (b) size backstop: LRU-evict until back under the cap
        if max_bytes >= 0 and total > max_bytes:
            for row in entries:
                if total <= max_bytes:
                    break
                _mtime, size, path = row
                if size < 0 or path in keep:
                    continue
                total -= _drop(path, size)


def _cache_janitor():
    """Background sweep: every CACHE_SWEEP_INTERVAL seconds, clear out prepared
    files no one is watching (idle past CACHE_TTL), keeping the cache to roughly
    just the current video."""
    while True:
        time.sleep(CACHE_SWEEP_INTERVAL)
        try:
            prune_cache(REMUX_DIR, CACHE_MAX_BYTES, CACHE_TTL)
        except Exception:
            pass


def start_cache_janitor():
    t = threading.Thread(target=_cache_janitor, name="cache-janitor", daemon=True)
    t.start()


def browser_playable(path: Path):
    """Can this file be sent to the browser untouched? True for a native container
    holding a browser-decodable video (and audio) codec. A native container with a
    codec the browser can't decode — e.g. HEVC/x265 in an .m4v or .mp4 — returns
    False so it gets remuxed/transcoded. If we can't probe, assume yes (best effort,
    matches the old behaviour)."""
    if not FFPROBE:
        return True
    meta = probe_meta(path)
    vc = (meta.get("vcodec") or "").lower()
    ac = (meta.get("acodec") or "").lower()
    if not vc:
        return True                      # couldn't identify the codec -> don't force a transcode
    if vc not in NATIVE_VCODECS:
        return False                     # e.g. hevc, mpeg4, vc1 -> needs transcoding
    if ac and ac not in NATIVE_ACODECS:
        return False                     # odd audio (ac3/dts/…) -> remux to AAC
    return True


def build_remux(path: Path):
    """Repackage a non-native container (e.g. .mkv) into a seekable MP4 the browser
    can play. Stream-copies when the codecs are already browser-friendly (fast,
    no quality loss); transcodes only what isn't. Cached. Returns the cached Path
    or None on failure."""
    key = cache_key(path)
    if not key or not FFMPEG:
        return None
    digest = hashlib.sha1(("remux:" + key).encode("utf-8")).hexdigest()
    out = REMUX_DIR / f"{digest}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out
    lock = _thumb_lock_for("remux:" + digest)
    with lock:
        if out.exists() and out.stat().st_size > 0:
            return out
        meta = probe_meta(path)
        vc = (meta.get("vcodec") or "").lower()
        ac = (meta.get("acodec") or "").lower()
        if vc in NATIVE_VCODECS:
            v_args = ["-c:v", "copy"]            # already browser-friendly: no re-encode
        else:
            enc = _h264_encoder()                # e.g. libx264, or libopenh264 where x264 is absent
            if not enc:
                return None                      # can't transcode this codec -> give up
            if enc == "libx264":
                v_args = ["-c:v", enc, "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
            else:
                # libopenh264 (and friends) want an explicit bitrate; scale it to the source height
                h = meta.get("height") or 1080
                br = next((TRANSCODE_LADDER[k][0] for k in sorted(TRANSCODE_LADDER) if h <= k),
                          TRANSCODE_LADDER[max(TRANSCODE_LADDER)][0])
                v_args = ["-c:v", enc, "-b:v", br, "-maxrate", br, "-pix_fmt", "yuv420p"]
        a_args = ["-c:a", "copy"] if ac in NATIVE_ACODECS else ["-c:a", "aac", "-b:a", "192k"]
        REMUX_DIR.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.mp4")
        cmd = [FFMPEG, "-nostdin", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0?",
               "-sn", *v_args, *a_args, "-movflags", "+faststart", "-y", "--", str(tmp)]
        with _ffmpeg_sem:
            try:
                rc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=3600).returncode
            except (subprocess.SubprocessError, OSError):
                tmp.unlink(missing_ok=True)
                return None
        if rc == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(out)
            prune_cache(REMUX_DIR, CACHE_MAX_BYTES, CACHE_TTL)
            return out
        tmp.unlink(missing_ok=True)
        return None


# Quality downscaling is no longer a whole-file transcode-then-cache step (that
# made switching wait for the entire episode to encode). It now streams live from
# the player's current position — see Handler._stream_transcode.


# --------------------------------------------------------------------------- #
# Library scanning
# --------------------------------------------------------------------------- #
def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# --------------------------------------------------------------------------- #
# Tidy display titles — strip the "slop" downloaded episodes pile up with
# (release group, resolution, codec, the repeated series name) so the library
# shows e.g. "S4E1 · The Title" instead of "The.Show.S04E01.The.Title.1080p...".
# Display only: the files on disk are never touched.
# --------------------------------------------------------------------------- #
_TITLE_STOP = {
    "1080p", "720p", "480p", "360p", "240p", "2160p", "4k", "8k", "uhd", "fhd", "hd", "sd",
    "web", "webdl", "webrip", "hdrip", "hdtv", "pdtv", "bluray", "bdrip", "brrip", "brip",
    "dvdrip", "dvdr", "dvd", "remux", "hdcam", "cam", "ts", "tc", "workprint",
    "x264", "x265", "h264", "h265", "hevc", "avc", "xvid", "divx", "av1", "vp9", "mpeg2",
    "10bit", "8bit", "hi10p", "hdr", "hdr10", "dv", "dovi", "dolby", "vision", "sdr",
    "aac", "aac2", "ac3", "eac3", "dd", "ddp", "dts", "dtshd", "truehd", "atmos", "flac", "opus", "mp3",
    "amzn", "nf", "hmax", "max", "dsnp", "hulu", "atvp", "pcok", "stan", "itunes",
    "repack", "proper", "real", "internal", "limited", "extended", "uncut", "unrated",
    "remastered", "restored", "complete", "multi", "dual", "subbed", "dubbed", "subs", "vostfr",
    "ita", "eng", "jpn", "fra", "ger", "esp", "rus", "kor",
    "yify", "yts", "rarbg", "ettv", "eztv", "ntb", "flux", "cakes",
}
_SMALL_WORDS = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "by",
                "with", "vs", "from"}
_SXEX = re.compile(r"(?i)\bs(\d{1,2})\s*e(\d{1,3})(?:\s*-?\s*e?\d{1,3})?\b")
_NXNN = re.compile(r"(?i)(?<!\w)(\d{1,2})x(\d{2,3})(?!\w)")
_YEAR = re.compile(r"(?:19|20)\d{2}")


def _is_stop(tok):
    lt = tok.lower()
    return bool(
        lt in _TITLE_STOP
        or re.fullmatch(r"\d{3,4}p", lt)
        or re.fullmatch(r"[hx]\.?26[45]", lt)
        or re.fullmatch(r"ddp?\+?\d(?:\.\d)?", lt)
        or re.fullmatch(r"\d\.\d", lt)
    )


def _titlecase(words):
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if i and lw in _SMALL_WORDS:
            out.append(lw)
        elif any(c.islower() for c in w) and any(c.isupper() for c in w):
            out.append(w)                       # already mixed (iCarly, X-Files) -> keep
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def _strip_brackets(s):
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(r"\{[^}]*\}", " ", s)
    return re.sub(r"\(([^)]*)\)",
                  lambda m: f" {m.group(1)} " if _YEAR.fullmatch(m.group(1).strip()) else " ", s)


def clean_title(name: str) -> str:
    """Best-effort tidy display name for a video file (see section header)."""
    stem = Path(name).stem
    s = _strip_brackets(stem)
    norm = re.sub(r"\s+", " ", re.sub(r"[._]+", " ", s)).strip()

    m = _SXEX.search(norm) or _NXNN.search(norm)
    if m:
        season, ep = int(m.group(1)), int(m.group(2))
        after = re.sub(r"[-–—]+", " ", norm[m.end():])
        title = []
        for tok in after.split():
            if _is_stop(tok) or _YEAR.fullmatch(tok.lower()):
                break
            title.append(tok)
        head = f"S{season}E{ep}"
        return f"{head} · {_titlecase(title)}" if title else head

    # No episode marker: only clean scene-style names (dotted, or with junk tags);
    # leave already-human names (with spaces, no junk) untouched.
    flat = re.sub(r"[-–—]+", " ", norm).split()
    has_junk = any(_is_stop(t) for t in flat)
    scene = (" " not in stem) and bool(re.search(r"[._]", stem))
    if not has_junk and not scene:
        return re.sub(r"\s+", " ", s).strip() or stem

    kept, year = [], None
    for tok in flat:
        if _YEAR.fullmatch(tok.lower()) and kept:
            year = tok
            break
        if _is_stop(tok):
            break
        kept.append(tok)
    title = _titlecase(kept) if kept else re.sub(r"\s+", " ", s).strip()
    return f"{title} ({year})" if year else title


def _count_subfolders(path):
    n = 0
    try:
        for e in os.scandir(path):
            if e.is_dir() and not e.name.startswith("."):
                n += 1
    except OSError:
        pass
    return n


def _count_videos(path):
    n = 0
    try:
        for e in os.scandir(path):
            if e.is_file() and Path(e.name).suffix.lower() in VIDEO_EXTS:
                n += 1
    except OSError:
        pass
    return n


def watched_dirs():
    """Map of directory -> number of finished (>=WATCHED_FRAC) videos directly in it.
    Read once from progress.json; lets us show watch progress while browsing without
    scanning every file on disk."""
    progress = load_json(PROGRESS_PATH, {})
    out = {}
    for path, rec in progress.items():
        dur = rec.get("duration") or 0
        pos = rec.get("position", 0)
        if dur and pos / dur >= WATCHED_FRAC:
            d = str(Path(path).parent)
            out[d] = out.get(d, 0) + 1
    return out


def watched_in_tree(folder: Path, wdirs):
    """How many finished videos live at or anywhere below `folder` (recursive),
    so a show folder reflects episodes watched across all its seasons."""
    total = 0
    for d, c in wdirs.items():
        dp = Path(d)
        if dp == folder or folder in dp.parents:
            total += c
    return total


def list_directory(path: Path):
    folders, videos = [], []
    wdirs = watched_dirs()
    meta_all = _meta_snapshot()
    try:
        entries = list(os.scandir(path))
    except OSError:
        return {"folders": [], "videos": []}
    for e in entries:
        try:
            if e.name.startswith("."):
                continue
            if e.is_dir():
                folders.append({
                    "name": e.name,
                    "path": str(Path(e.path).resolve()),
                    "subfolders": _count_subfolders(e.path),
                    "videos": _count_videos(e.path),
                    "watched": watched_in_tree(Path(e.path).resolve(), wdirs),
                })
            elif e.is_file() and Path(e.name).suffix.lower() in VIDEO_EXTS:
                ext = Path(e.name).suffix.lower()
                st = e.stat()
                meta = meta_all.get(f"{Path(e.path).resolve()}|{st.st_mtime_ns}|{st.st_size}") or {}
                videos.append({
                    "name": e.name,
                    "display": clean_title(e.name),
                    "path": str(Path(e.path).resolve()),
                    "ext": ext,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "playable": True,                 # non-native ones play via remux
                    "direct": ext in NATIVE_EXTS,     # served as-is vs. prepared on first play
                    "duration": meta.get("duration"),
                })
        except OSError:
            continue
    folders.sort(key=lambda x: natural_key(x["name"]))
    videos.sort(key=lambda x: natural_key(x["name"]))
    return {"folders": folders, "videos": videos}


def list_roots():
    out = []
    wdirs = watched_dirs()
    for root in real_roots():
        out.append({
            "name": root.name or str(root),
            "path": str(root),
            "subfolders": _count_subfolders(root),
            "videos": _count_videos(root),
            "watched": watched_in_tree(root, wdirs),
        })
    return out


# --------------------------------------------------------------------------- #
# Server-side directory picker (for first-run "choose a folder")
# --------------------------------------------------------------------------- #
def browse_dir(raw_path):
    """List subdirectories so the user can pick a library folder in-browser."""
    if raw_path:
        try:
            base = Path(raw_path).expanduser().resolve()
        except OSError:
            base = Path.home()
    else:
        base = Path.home()
    if not base.is_dir():
        base = Path.home()
    dirs = []
    try:
        for e in os.scandir(base):
            try:
                if e.is_dir() and not e.name.startswith("."):
                    dirs.append({"name": e.name, "path": str(Path(e.path).resolve()),
                                 "videos": _count_videos(e.path)})
            except OSError:
                continue
    except OSError:
        pass
    dirs.sort(key=lambda x: natural_key(x["name"]))
    parent = str(base.parent) if base.parent != base else None
    shortcuts = []
    home = Path.home()
    for name in ("Videos", "Movies", "TV", "Downloads", "Media"):
        cand = home / name
        if cand.is_dir():
            shortcuts.append({"name": f"~/{name}", "path": str(cand)})
    return {"path": str(base), "parent": parent, "dirs": dirs,
            "home": str(home), "shortcuts": shortcuts}


_PICKER_TOOL = "?"   # sentinel: not yet probed


def _picker_tool():
    """First available native folder-dialog tool (cached; probed on every /api/session)."""
    global _PICKER_TOOL
    if _PICKER_TOOL == "?":
        _PICKER_TOOL = None
        for t in ("kdialog", "zenity", "qarma", "yad"):
            p = shutil.which(t)
            if p:
                _PICKER_TOOL = (t, p)
                break
    return _PICKER_TOOL


def native_pick_folder(start=None):
    """Open the OS-native folder dialog on the server's own desktop.
    Returns a path string, "" if the user cancelled, or None if unavailable."""
    tool = _picker_tool()
    if not tool:
        return None
    name, path = tool
    start = start or str(Path.home())
    if name == "kdialog":
        cmd = [path, "--getexistingdirectory", start]
    elif name in ("zenity", "qarma"):
        cmd = [path, "--file-selection", "--directory", f"--filename={start}/"]
    elif name == "yad":
        cmd = [path, "--file", "--directory"]
    else:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=600)
    except (subprocess.SubprocessError, OSError):
        return None
    if out.returncode != 0:
        return ""  # cancelled / closed
    return out.stdout.decode("utf-8", "ignore").strip()


def _uri_to_path(u):
    """Turn a dropped 'file:///path' URI (or a plain absolute path) into a Path."""
    u = (u or "").strip()
    if not u:
        return None
    if u.startswith("file://"):
        path = unquote(urlparse(u).path)
    elif u.startswith("/") or (len(u) > 2 and u[1] == ":"):  # unix abs / windows drive
        path = unquote(u)
    else:
        return None
    if not path:
        return None
    try:
        return Path(path).expanduser()
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# Built-in demo library (royalty-free ffmpeg test patterns)
# --------------------------------------------------------------------------- #
DEMO_SPECS = [
    ("Kinema Demo Show/Season 1/Episode 1 - Pilot.mp4", "testsrc=size=854x480:rate=24", 12),
    ("Kinema Demo Show/Season 1/Episode 2 - The Reveal.mp4", "testsrc2=size=854x480:rate=24", 10),
    ("Demo Movies/Fractal Voyage.mp4", "mandelbrot=size=854x480:rate=24", 15),
    ("Demo Movies/Color Bars Classic.mp4", "smptebars=size=854x480:rate=24", 8),
]


_H264_ENCODER = "?"   # sentinel: not yet probed


def _h264_encoder():
    """Available H.264 encoder for transcoding (cached; was spawning ffmpeg per call)."""
    global _H264_ENCODER
    if _H264_ENCODER != "?":
        return _H264_ENCODER
    if not FFMPEG:
        _H264_ENCODER = None
        return None
    try:
        out = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                             capture_output=True, timeout=15).stdout.decode("utf-8", "ignore")
    except (subprocess.SubprocessError, OSError):
        return None   # transient (e.g. timeout): don't memoize, retry next call
    enc = None
    for c in ("libx264", "libopenh264"):
        if " " + c in out:
            enc = c
            break
    _H264_ENCODER = enc
    return enc


def build_demo_library(dest):
    """Generate the sample clips into `dest` (idempotent). Returns True on success."""
    dest = Path(dest)
    enc = _h264_encoder()
    if not enc:
        return False
    made = 0
    for rel, vf, dur in DEMO_SPECS:
        out = dest / rel
        if out.exists() and out.stat().st_size > 0:
            made += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [FFMPEG, "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", vf,
               "-f", "lavfi", "-i", f"sine=frequency=320:duration={dur}",
               "-t", str(dur), "-c:v", enc, "-b:v", "800k",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "--", str(out)]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=120)
            if out.exists():
                made += 1
        except (subprocess.SubprocessError, OSError):
            pass
    return made > 0


# --------------------------------------------------------------------------- #
# Continue-watching feed
# --------------------------------------------------------------------------- #
def _folder_episodes(folder: Path):
    """Video files directly in `folder`, in natural (episode) order."""
    try:
        names = [e.name for e in os.scandir(folder)
                 if e.is_file() and not e.name.startswith(".")
                 and Path(e.name).suffix.lower() in VIDEO_EXTS]
    except OSError:
        return []
    names.sort(key=natural_key)
    return [folder / n for n in names]


def continue_watching():
    """One card per series, Netflix-style: surface the episode you're mid-way
    through, or — if you just finished one — the next episode in that folder.
    Episodes are grouped by their containing folder (the "series"), so a show
    never floods the row with every watched episode."""
    progress = load_json(PROGRESS_PATH, {})

    def _frac(rec):
        pos, dur = rec.get("position", 0) or 0, rec.get("duration") or 0
        return (pos / dur) if dur else 0

    def _finished(rec):
        return bool(rec.get("duration")) and _frac(rec) >= WATCHED_FRAC

    def _started(rec):
        return (rec.get("position", 0) or 0) >= 5 or _frac(rec) >= 0.05

    # group every started/finished episode by its containing folder
    groups: dict[str, list] = {}
    for path, rec in progress.items():
        if not (_started(rec) or _finished(rec)):
            continue
        p = Path(path)
        if not p.exists() or owning_root(p) is None:
            continue
        groups.setdefault(str(p.parent), []).append((p, rec))

    def _cached_duration(p: Path):
        return (_meta_cache_get(cache_key(p) or "") or {}).get("duration")

    def _item(p: Path, position, duration, updated):
        return {
            "name": p.name, "display": clean_title(p.name), "path": str(p), "ext": p.suffix.lower(),
            "playable": True, "direct": p.suffix.lower() in NATIVE_EXTS,
            "position": position, "duration": duration, "updated": updated,
        }

    items = []
    for folder, entries in groups.items():
        # the episode this series was last engaged with
        last_p, last_rec = max(entries, key=lambda e: e[1].get("updated", 0))
        last_updated = last_rec.get("updated", 0)

        if not _finished(last_rec):
            # still mid-episode -> keep watching it
            items.append(_item(last_p, last_rec.get("position", 0) or 0,
                               last_rec.get("duration"), last_updated))
            continue

        # finished it -> show the next episode in the folder (Netflix "up next")
        eps = _folder_episodes(Path(folder))
        idx = next((k for k, e in enumerate(eps) if str(e) == str(last_p)), -1)
        if idx < 0 or idx + 1 >= len(eps):
            continue                          # last episode done -> series complete
        nxt = eps[idx + 1]
        rec = progress.get(str(nxt)) or {}
        if _started(rec) and not _finished(rec):
            pos, dur = rec.get("position", 0) or 0, rec.get("duration")
        else:                                 # fresh or already-seen (rewatch) -> start over
            pos, dur = 0, (rec.get("duration") or _cached_duration(nxt))
        items.append(_item(nxt, pos, dur, last_updated))

    items.sort(key=lambda x: x["updated"], reverse=True)
    return items[:40]


# --------------------------------------------------------------------------- #
# Search (Netflix-style: type anywhere, find shows & episodes across all roots)
# --------------------------------------------------------------------------- #
def search_library(query: str, limit: int = 80):
    """Case-insensitive substring search over folder and file names across every
    library root. Bounded by a result cap and a wall-clock deadline so it stays
    snappy and safe on huge libraries; only paths inside a root are ever returned."""
    q = (query or "").strip().lower()
    if len(q) < 1:
        return {"folders": [], "videos": []}
    folders, videos = [], []
    wdirs = watched_dirs()
    meta_all = _meta_snapshot()
    deadline = time.time() + 5.0
    cap = limit * 3                                  # gather a few extra, then sort + slice
    for root in real_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            if time.time() > deadline or (len(folders) + len(videos)) >= cap:
                break
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for d in dirnames:
                if q in d.lower():
                    p = (Path(dirpath) / d).resolve()
                    folders.append({
                        "name": d, "path": str(p),
                        "subfolders": _count_subfolders(p),
                        "videos": _count_videos(p),
                        "watched": watched_in_tree(p, wdirs),
                    })
            for fn in filenames:
                if fn.startswith(".") or Path(fn).suffix.lower() not in VIDEO_EXTS:
                    continue
                if q in fn.lower():
                    p = (Path(dirpath) / fn).resolve()
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    ext = p.suffix.lower()
                    meta = meta_all.get(f"{p}|{st.st_mtime_ns}|{st.st_size}") or {}
                    videos.append({
                        "name": fn, "path": str(p), "ext": ext, "size": st.st_size,
                        "mtime": st.st_mtime, "playable": True,
                        "direct": ext in NATIVE_EXTS, "duration": meta.get("duration"),
                    })
        if time.time() > deadline or (len(folders) + len(videos)) >= cap:
            break
    folders.sort(key=lambda x: natural_key(x["name"]))
    videos.sort(key=lambda x: natural_key(x["name"]))
    return {"folders": folders[:limit], "videos": videos[:limit]}


# --------------------------------------------------------------------------- #
# Subtitles (sidecar .srt/.vtt files next to a video; .srt converted on the fly)
# --------------------------------------------------------------------------- #
_LANG_NAMES = {
    "en": "English", "eng": "English", "es": "Español", "spa": "Español",
    "fr": "Français", "fre": "Français", "fra": "Français", "de": "Deutsch",
    "ger": "Deutsch", "deu": "Deutsch", "it": "Italiano", "ita": "Italiano",
    "pt": "Português", "por": "Português", "nl": "Nederlands", "ja": "日本語",
    "jpn": "日本語", "ko": "한국어", "kor": "한국어", "zh": "中文", "chi": "中文",
    "zho": "中文", "ru": "Русский", "rus": "Русский", "ar": "العربية",
    "hi": "हिन्दी", "pl": "Polski", "sv": "Svenska", "tr": "Türkçe",
}


def subtitle_tracks(video: Path):
    """Find sidecar subtitle files that belong to `video` — same folder, name
    starting with the video's stem (e.g. Episode.srt, Episode.en.srt,
    Episode.English.forced.vtt). Returns [{lang, label, url}] for the player."""
    out = []
    stem = video.stem.lower()
    try:
        entries = list(os.scandir(video.parent))
    except OSError:
        return out
    for e in entries:
        try:
            if not e.is_file():
                continue
            p = Path(e.name)
            if p.suffix.lower() not in SUBTITLE_EXTS:
                continue
            name_l = p.stem.lower()
            if name_l != stem and not name_l.startswith(stem + "."):
                continue
            # the bit between the video stem and the extension is the language hint
            tag = p.stem[len(video.stem):].strip(". ") if len(name_l) > len(stem) else ""
            parts = [t for t in re.split(r"[.\-_ ]+", tag) if t]
            lang, label = "", ""
            for part in parts:
                key = part.lower()
                if key in _LANG_NAMES:
                    lang = key
                    label = _LANG_NAMES[key]
                    break
            if not label:
                label = tag.replace(".", " ").strip() or "Subtitles"
            if "forced" in tag.lower():
                label += " (forced)"
            sub_path = str((video.parent / e.name).resolve())
            out.append({"lang": lang or "und", "label": label,
                        "url": "/api/sub?path=" + quote(sub_path)})
        except OSError:
            continue
    out.sort(key=lambda x: (x["label"] != "English", x["label"].lower()))
    return out


_SRT_TS = re.compile(r"(\d{1,2}:\d{2}:\d{2}),(\d{1,3})")


def srt_to_vtt(text: str):
    """Convert SubRip (.srt) text to WebVTT so the browser <track> can read it.
    The differences that matter: a `WEBVTT` header and `.`-separated millis."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    text = _SRT_TS.sub(lambda m: f"{m.group(1)}.{int(m.group(2)):03d}", text)
    return "WEBVTT\n\n" + text


def read_subtitle_as_vtt(path: Path):
    """Read a sidecar subtitle file and return WebVTT bytes, decoding common
    encodings (UTF-8 first, then Latin-1) so odd files don't break playback."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    if path.suffix.lower() == ".srt":
        text = srt_to_vtt(text)
    elif not text.lstrip().startswith("WEBVTT"):
        text = "WEBVTT\n\n" + text.lstrip("﻿")
    return text.encode("utf-8")


# --------------------------------------------------------------------------- #
# My List (Netflix-style watchlist of pinned shows / movies)
# --------------------------------------------------------------------------- #
def my_list_items():
    """Stored watchlist, filtered to entries that still exist inside a root."""
    data = load_json(MYLIST_PATH, {})
    items = []
    for path, rec in data.items():
        p = Path(path)
        if owning_root(p) is None or not p.exists():
            continue
        is_folder = p.is_dir()
        items.append({
            "path": path, "name": rec.get("name") or p.name,
            "isFolder": is_folder, "added": rec.get("added", 0),
            "ext": p.suffix.lower(), "playable": True,
            "direct": p.suffix.lower() in NATIVE_EXTS,
        })
    items.sort(key=lambda x: x["added"], reverse=True)
    return items


def my_list_set(path: str, on: bool, name: str = ""):
    """Add or remove a path from the watchlist. Returns the updated paths set."""
    with _io_lock:
        data = load_json(MYLIST_PATH, {})
        if on:
            p = resolve_within_roots(path, must_exist=True)
            if not p:
                return None
            data[str(p)] = {"name": name or p.name, "added": time.time()}
        else:
            p = resolve_within_roots(path, must_exist=False)
            data.pop(str(p) if p else path, None)
        save_json(MYLIST_PATH, data)
    return list(data.keys())


# --------------------------------------------------------------------------- #
# File operations (rename / move / mkdir / delete-to-trash)
# --------------------------------------------------------------------------- #
def _migrate_progress(old: Path, new: Path):
    """Preserve resume positions when a file or folder is renamed/moved: re-key
    every progress entry at (or under) `old` to the matching path under `new`, so
    renaming an episode (or a whole season folder) keeps your place and its
    Continue-watching card instead of orphaning it."""
    with _io_lock:
        progress = load_json(PROGRESS_PATH, {})
        if not progress:
            return
        moved = {}
        for key, rec in progress.items():
            kp = Path(key)
            if kp == old:
                moved[str(new)] = rec
            elif old in kp.parents:
                moved[str(new / kp.relative_to(old))] = rec
            else:
                moved[key] = rec
        if moved != progress:
            save_json(PROGRESS_PATH, moved)


def op_rename(src_raw, new_name):
    src = resolve_within_roots(src_raw)
    if not src:
        return False, "Source not found or outside library."
    if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        return False, "Invalid name."
    dst = src.with_name(new_name)
    if dst.exists():
        return False, "A file with that name already exists."
    try:
        src.rename(dst)
    except OSError as e:
        return False, str(e)
    _migrate_progress(src, dst)
    return True, str(dst)


def op_move(src_raw, dest_dir_raw):
    src = resolve_within_roots(src_raw)
    dest_dir = resolve_within_roots(dest_dir_raw)
    if not src:
        return False, "Source not found or outside library."
    if not dest_dir or not dest_dir.is_dir():
        return False, "Destination folder not found or outside library."
    dst = dest_dir / src.name
    if dst.exists():
        return False, "Destination already has a file with that name."
    try:
        shutil.move(str(src), str(dst))
    except OSError as e:
        return False, str(e)
    _migrate_progress(src, dst)
    return True, str(dst)


def op_mkdir(parent_raw, name):
    parent = resolve_within_roots(parent_raw)
    if not parent or not parent.is_dir():
        return False, "Parent folder not found or outside library."
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return False, "Invalid folder name."
    target = parent / name
    if target.exists():
        return False, "Folder already exists."
    try:
        target.mkdir()
    except OSError as e:
        return False, str(e)
    return True, str(target)


def op_delete(src_raw):
    src = resolve_within_roots(src_raw)
    if not src:
        return False, "Path not found or outside library."
    root = owning_root(src)
    if root is None:
        return False, "Path outside library."
    trash = root / TRASH_DIRNAME
    try:
        trash.mkdir(exist_ok=True)
        target = trash / src.name
        i = 1
        while target.exists():
            target = trash / f"{src.stem}_{i}{src.suffix}"
            i += 1
        shutil.move(str(src), str(target))
    except OSError as e:
        return False, str(e)
    return True, str(target)


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/qr.js": ("qr.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}

CSP = ("default-src 'self'; img-src 'self' data:; media-src 'self'; "
       "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
       "form-action 'self'")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"{APP_NAME}/{APP_VERSION}"
    # Reclaim idle keep-alive connections so sleeping tabs/phones can't slowly
    # accumulate handler threads across a multi-hour session. A live transfer
    # resets this on every chunk; only a truly stalled socket trips it.
    timeout = 120

    def log_message(self, fmt, *args):
        pass

    # -- inject security headers on every response -------------------------- #
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    # -- response helpers --------------------------------------------------- #
    def _send_json(self, obj, status=200, extra_headers=None):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_bytes(self, data, ctype, status=200, cache=True):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if cache:
            self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return {}
        if length <= 0 or length > 2_000_000:   # JSON bodies are tiny; cap them
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    # -- security gate ------------------------------------------------------ #
    def _authed(self):
        if not password_required():
            return True
        tok = parse_cookies(self.headers.get("Cookie", "")).get("kinema_session")
        return session_valid(tok)

    def _origin_ok(self):
        """For state-changing requests: require a positive same-site signal (CSRF)."""
        # The X-Kinema header can only be set by our same-origin JS; a cross-site
        # page cannot add a custom header without a CORS preflight we never grant.
        if self.headers.get("X-Kinema"):
            return True
        origin = self.headers.get("Origin")
        if origin is not None:
            return host_allowed(origin)
        ref = self.headers.get("Referer")
        if ref:
            return host_allowed(ref)
        # No same-site signal at all -> treat as cross-site and reject.
        return False

    def _guard(self, route, mutating):
        """Returns True if the request may proceed; else sends an error."""
        if not host_allowed(self.headers.get("Host", "")):
            self._send_json({"error": "Host not allowed"}, 403)
            return False
        if mutating and not self._origin_ok():
            self._send_json({"error": "Cross-site request blocked"}, 403)
            return False
        is_public = route in PUBLIC_ROUTES or route.startswith("/fonts/")
        if not is_public and not self._authed():
            self._send_json({"error": "Authentication required", "needAuth": True}, 401)
            return False
        return True

    def _require_writable(self):
        if READONLY:
            self._send_json({"error": "This instance is read-only."}, 403)
            return False
        return True

    # -- serve a prepared-cache file ---------------------------------------- #
    def _serve_prepared(self, cached: Path, ctype):
        """Stream a file from the prepared-video cache. Marks it as freshly watched
        (so the janitor keeps it) and shields it from eviction while it streams."""
        sp = str(cached)
        try:
            os.utime(cached, None)           # 'last watched' = now
        except OSError:
            pass
        _cache_acquire(sp)
        try:
            return self._serve_file_with_range(cached, ctype)
        finally:
            _cache_release(sp)

    # -- on-the-fly quality downscale, streamed live ------------------------ #
    def _stream_transcode(self, path: Path, height: int, start: float):
        """Downscale `path` to `height` lines and pipe it to the client live as a
        fragmented MP4, beginning at `start` seconds. Playback starts in ~1-2s
        instead of waiting for a whole-file transcode. The stream isn't seekable
        (Accept-Ranges: none); the player re-requests with a new `t` to seek."""
        enc = _h264_encoder()
        if not FFMPEG or not enc or height not in TRANSCODE_LADDER:
            return self._send_json({"error": "unsupported quality"}, 400)
        bitrate, bufsize = TRANSCODE_LADDER[height]
        v_args = ["-c:v", enc, "-vf", f"scale=-2:{height}",
                  "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", bufsize, "-pix_fmt", "yuv420p"]
        if enc == "libx264":
            v_args += ["-preset", "veryfast", "-tune", "zerolatency"]
        # -ss before -i = fast keyframe seek; fragmented mp4 = streamable without
        # rewriting the moov, so the first bytes flow almost immediately.
        cmd = [FFMPEG, "-nostdin", "-ss", f"{max(0.0, start):.3f}", "-i", str(path),
               "-map", "0:v:0", "-map", "0:a:0?", "-sn",
               *v_args, "-c:a", "aac", "-b:a", "160k", "-ac", "2",
               "-movflags", "frag_keyframe+empty_moov+default_base_moof",
               "-f", "mp4", "pipe:1"]
        self.close_connection = True           # no Content-Length -> read until close
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Accept-Ranges", "none")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError:
            return
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                                # client switched quality / closed the tab
        finally:
            try: proc.stdout.close()
            except OSError: pass
            try: proc.kill()
            except OSError: pass
            try: proc.wait(timeout=5)
            except (subprocess.SubprocessError, OSError): pass

    # -- range-aware file streaming ----------------------------------------- #
    def _serve_file_with_range(self, filepath: Path, ctype):
        try:
            file_size = filepath.stat().st_size
        except OSError:
            self._send_json({"error": "not found"}, 404)
            return
        range_header = self.headers.get("Range")
        start, end, status = 0, file_size - 1, 200
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
                if not m.group(1) and m.group(2):       # suffix: bytes=-N
                    start = max(0, file_size - int(m.group(2)))
                    end = file_size - 1
                end = min(end, file_size - 1)
                if start > end or start >= file_size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        self._stream(filepath, start, length)

    def _stream(self, filepath: Path, start, length):
        chunk, remaining = 256 * 1024, length
        try:
            with open(filepath, "rb") as f:
                f.seek(start)
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _serve_static(self, route):
        name, ctype = STATIC_FILES[route]
        fp = WEB_DIR / name
        if not fp.exists():
            self._send_json({"error": "missing asset"}, 404)
            return
        data = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        if route in ("/", "/index.html"):
            self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _placeholder_thumb(self):
        gif = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00!"
               b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
               b"\x00\x00\x02\x02D\x01\x00;")
        self._send_bytes(gif, "image/gif", cache=False)

    def _breadcrumb(self, path: Path):
        root = owning_root(path)
        if root is None:
            return []
        crumbs = [{"name": root.name or str(root), "path": str(root)}]
        cur = root
        for part in path.relative_to(root).parts:
            cur = cur / part
            crumbs.append({"name": part, "path": str(cur)})
        return crumbs

    def _session_state(self):
        return {
            "app": APP_NAME, "version": APP_VERSION,
            "authRequired": password_required(),
            "authed": self._authed(),
            "readonly": READONLY,
            "canManage": (not READONLY) and self._authed(),
            "canBrowse": ALLOW_BROWSE and (not READONLY) and self._authed(),
            "nativePicker": bool(_picker_tool()) and (not READONLY) and self._authed(),
            "ffmpeg": bool(FFMPEG),
            "urls": SERVER_URLS,
            "lan": LAN_MODE,
            "canToggleLan": LAN_TOGGLEABLE and (not READONLY) and self._authed(),
            "canSetPassword": (not READONLY) and self._authed(),
        }

    # -- verbs -------------------------------------------------------------- #
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        route, qs = parsed.path, parse_qs(parsed.query)

        if not self._guard(route, mutating=False):
            return

        if route in STATIC_FILES:
            return self._serve_static(route)

        if route.startswith("/fonts/") and route.endswith(".woff2"):
            name = route[len("/fonts/"):]
            if "/" in name or ".." in name:
                return self._send_json({"error": "not found"}, 404)
            fp = WEB_DIR / "fonts" / name
            if fp.is_file():
                return self._send_bytes(fp.read_bytes(), "font/woff2")
            return self._send_json({"error": "not found"}, 404)

        if route == "/api/session":
            return self._send_json(self._session_state())

        if route == "/api/config":
            cfg = get_config()
            cfg.pop("auth", None)        # never expose the password hash to the client
            return self._send_json(cfg)

        if route == "/api/library":
            raw = qs.get("path", [None])[0]
            if not raw:
                return self._send_json({"path": None, "isRoot": True,
                                        "folders": list_roots(), "videos": [],
                                        "breadcrumb": []})
            path = resolve_within_roots(unquote(raw))
            if not path or not path.is_dir():
                return self._send_json({"error": "Folder not found or outside library."}, 404)
            data = list_directory(path)
            data.update(path=str(path), isRoot=False, breadcrumb=self._breadcrumb(path))
            return self._send_json(data)

        if route == "/api/browse":
            if not (ALLOW_BROWSE and not READONLY):
                return self._send_json({"error": "Browsing disabled."}, 403)
            return self._send_json(browse_dir(unquote(qs.get("path", [""])[0])))

        if route == "/api/meta":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            return self._send_json(probe_meta(path))

        if route == "/api/thumb":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._placeholder_thumb()
            t = generate_thumb(path)
            if t and t.exists():
                return self._send_bytes(t.read_bytes(), "image/jpeg")
            return self._placeholder_thumb()

        if route == "/api/stream":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            ext = path.suffix.lower()
            if ext in NATIVE_EXTS and browser_playable(path):
                return self._serve_file_with_range(path, MIME.get(ext, "application/octet-stream"))
            # non-native container (.mkv …) OR a native container whose codec the
            # browser can't decode (e.g. HEVC/x265 inside an .m4v): remux/transcode it
            playable = build_remux(path)
            if playable and playable.exists():
                return self._serve_prepared(playable, "video/mp4")
            return self._send_json({"error": "Could not prepare this video for playback."}, 415)

        if route == "/api/transcode":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json({"error": "not found"}, 404)
            try:
                height = int(qs.get("height", ["0"])[0])
            except (TypeError, ValueError):
                return self._send_json({"error": "bad height"}, 400)
            if height not in TRANSCODE_LADDER:
                return self._send_json({"error": "unsupported quality"}, 400)
            try:
                start = float(qs.get("t", ["0"])[0])
            except (TypeError, ValueError):
                start = 0.0
            return self._stream_transcode(path, height, start)

        if route == "/api/progress":
            return self._send_json(load_json(PROGRESS_PATH, {}))

        if route == "/api/continue":
            return self._send_json(continue_watching())

        if route == "/api/search":
            return self._send_json(search_library(unquote(qs.get("q", [""])[0])))

        if route == "/api/mylist":
            return self._send_json(my_list_items())

        if route == "/api/subs":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file():
                return self._send_json([])
            return self._send_json(subtitle_tracks(path))

        if route == "/api/sub":
            path = resolve_within_roots(unquote(qs.get("path", [""])[0]))
            if not path or not path.is_file() or path.suffix.lower() not in SUBTITLE_EXTS:
                return self._send_json({"error": "not found"}, 404)
            try:
                return self._send_bytes(read_subtitle_as_vtt(path), "text/vtt; charset=utf-8")
            except OSError:
                return self._send_json({"error": "could not read subtitle"}, 500)

        if route == "/api/playlists":
            return self._send_json(load_json(PLAYLISTS_PATH, {}))

        return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        route = urlparse(self.path).path

        if not self._guard(route, mutating=True):
            return
        body = self._read_body()

        if route == "/api/login":
            if not password_required():
                return self._send_json({"ok": True, "authed": True})
            ip = self.client_address[0] if self.client_address else "?"
            allowed, retry = login_check(ip)
            if not allowed:
                return self._send_json(
                    {"ok": False, "error": f"Too many attempts. Try again in {retry}s."},
                    429, extra_headers={"Retry-After": str(retry)})
            supplied = str(body.get("password", ""))
            if verify_password(supplied):
                login_ok(ip)
                tok = new_session()
                cookie = (f"kinema_session={tok}; HttpOnly; SameSite=Strict; "
                          f"Path=/; Max-Age=2592000")
                return self._send_json({"ok": True, "authed": True},
                                       extra_headers={"Set-Cookie": cookie})
            login_fail(ip)
            return self._send_json({"ok": False, "error": "Wrong password."}, 401)

        if route == "/api/logout":
            tok = parse_cookies(self.headers.get("Cookie", "")).get("kinema_session")
            if tok:
                with SESSIONS_LOCK:
                    SESSIONS.pop(tok, None)
            clear = "kinema_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
            return self._send_json({"ok": True}, extra_headers={"Set-Cookie": clear})

        if route == "/api/progress":
            p = resolve_within_roots(body.get("path"), must_exist=False)
            if not p:
                return self._send_json({"error": "outside library"}, 400)
            try:
                pos = float(body.get("position", 0))
                dur = float(body.get("duration", 0) or 0)
            except (TypeError, ValueError):
                return self._send_json({"error": "bad payload"}, 400)
            with _io_lock:
                progress = load_json(PROGRESS_PATH, {})
                progress[str(p)] = {"position": pos, "duration": dur, "updated": time.time()}
                save_json(PROGRESS_PATH, progress)
            return self._send_json({"ok": True})

        if route == "/api/progress/clear":
            with _io_lock:
                progress = load_json(PROGRESS_PATH, {})
                path = body.get("path")
                if path:
                    p = resolve_within_roots(path, must_exist=False)
                    progress.pop(str(p) if p else path, None)
                else:
                    progress = {}
                save_json(PROGRESS_PATH, progress)
            return self._send_json({"ok": True})

        if route == "/api/mylist":
            # personal watchlist state — like progress, allowed even in read-only
            keys = my_list_set(body.get("path"), bool(body.get("on", True)),
                               str(body.get("name", "")))
            if keys is None:
                return self._send_json({"error": "outside library"}, 400)
            return self._send_json({"ok": True, "paths": keys})

        if route == "/api/lan":
            # network-sharing toggle: a server setting, not a library write, but we
            # still gate it behind management rights so a read-only/demo instance
            # can never be flipped open by a visitor.
            if not self._require_writable():
                return
            if not LAN_TOGGLEABLE:
                return self._send_json(
                    {"ok": False, "error": "Network sharing isn't available for this "
                     "bind address. Start Kinema without an explicit --host (or with "
                     "--lan) to enable it."}, 400)
            set_lan_mode(bool(body.get("on")))
            return self._send_json({"ok": True, "lan": LAN_MODE, "urls": SERVER_URLS})

        if route == "/api/password":
            # Set / change / clear the access password at runtime (persisted, hashed).
            # Gated like the LAN toggle so a read-only/demo instance can't be locked.
            # _guard already required a valid session when a password is currently set,
            # so only someone already signed in can change or remove it.
            if not self._require_writable():
                return
            new_pw = str(body.get("password", ""))
            if len(new_pw) > 256:
                return self._send_json({"ok": False, "error": "That password is too long."}, 400)
            set_password(new_pw)
            extra = {}
            if password_required():
                tok = new_session()          # keep whoever just set it signed in on this device
                extra["Set-Cookie"] = (f"kinema_session={tok}; HttpOnly; SameSite=Strict; "
                                       f"Path=/; Max-Age=2592000")
            else:
                extra["Set-Cookie"] = "kinema_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
            return self._send_json({"ok": True, "authRequired": password_required()},
                                   extra_headers=extra)

        # ---- everything below mutates the library: require writable ------- #
        if route == "/api/config":
            if not self._require_writable():
                return
            cfg = get_config()
            roots = body.get("roots")
            if isinstance(roots, list):
                clean = []
                for r in roots[:64]:
                    try:
                        p = Path(str(r)).expanduser().resolve()
                    except OSError:
                        continue
                    if p.is_dir() and str(p) not in clean:
                        clean.append(str(p))
                cfg["roots"] = clean
                set_config(cfg)
            return self._send_json(get_config())

        if route == "/api/playlists":
            if not self._require_writable():
                return
            with _io_lock:
                save_json(PLAYLISTS_PATH, body.get("playlists", {}))
            return self._send_json({"ok": True})

        if route == "/api/pick-folder":
            if not self._require_writable():
                return
            if not _picker_tool():
                return self._send_json({"ok": False, "error": "No native folder picker on this machine."})
            sel = native_pick_folder(body.get("start"))
            if sel is None:
                return self._send_json({"ok": False, "error": "The folder picker could not open."})
            if sel == "":
                return self._send_json({"ok": False, "cancelled": True})
            p = Path(sel).expanduser()
            if not p.is_dir():
                return self._send_json({"ok": False, "error": "That isn't a folder."})
            return self._send_json({"ok": True, "path": str(p.resolve())})

        if route == "/api/add-paths":
            if not self._require_writable():
                return
            cfg = get_config()
            roots = list(cfg.get("roots", []))
            added = []
            for u in (body.get("paths") or [])[:64]:
                p = _uri_to_path(u)
                if not p:
                    continue
                if p.is_file():
                    p = p.parent
                if p.is_dir():
                    sp = str(p.resolve())
                    if sp not in roots:
                        roots.append(sp)
                        added.append(sp)
            cfg["roots"] = roots
            set_config(cfg)
            return self._send_json({"ok": True, "added": added, "roots": roots})

        if route == "/api/op":
            if not self._require_writable():
                return
            action = body.get("action")
            if action == "rename":
                ok, msg = op_rename(body.get("path"), body.get("name"))
            elif action == "move":
                ok, msg = op_move(body.get("path"), body.get("dest"))
            elif action == "mkdir":
                ok, msg = op_mkdir(body.get("path"), body.get("name"))
            elif action == "delete":
                ok, msg = op_delete(body.get("path"))
            else:
                ok, msg = False, "Unknown action."
            return self._send_json({"ok": ok, "message": msg}, 200 if ok else 400)

        return self._send_json({"error": "not found"}, 404)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
SERVER_URLS = []


def compute_server_urls():
    """The URLs shown in Settings, reflecting the current network-sharing state."""
    urls = [f"http://127.0.0.1:{PORT}"]
    if LAN_MODE:
        for ip in sorted(h for h in local_hostnames() if _is_lan_ip(h)):
            urls.append(f"http://{ip}:{PORT}")
    return urls


def set_lan_mode(on):
    """Flip network sharing at runtime (no restart) and remember the choice so the
    next launch keeps it. The socket is already bound to 0.0.0.0; peer_allowed()
    reads LAN_MODE on every new connection, so this takes effect immediately."""
    global LAN_MODE, SERVER_URLS
    LAN_MODE = bool(on)
    SERVER_URLS = compute_server_urls()
    cfg = get_config()
    cfg["lan"] = LAN_MODE
    set_config(cfg)


def _hash_pw(salt, pw):
    return hashlib.sha256(("kinema$" + salt + "$" + pw).encode("utf-8")).hexdigest()


def password_required():
    return PW_HASH is not None


def verify_password(pw):
    if PW_HASH is None:
        return True
    return hmac.compare_digest(_hash_pw(PW_SALT, str(pw or "")), PW_HASH)


def set_password(pw, persist=True):
    """Set, change, or (with an empty value) clear the access password at runtime.
    Stored salted + hashed in config.json so it survives restarts; takes effect for
    new requests immediately. CLI/env passwords pass persist=False (in-memory only)."""
    global PW_SALT, PW_HASH
    pw = pw or ""
    if not pw:
        PW_SALT, PW_HASH = None, None
    else:
        PW_SALT = secrets.token_hex(16)
        PW_HASH = _hash_pw(PW_SALT, pw)
    if persist:
        cfg = get_config()
        if PW_HASH:
            cfg["auth"] = {"salt": PW_SALT, "hash": PW_HASH}
        else:
            cfg.pop("auth", None)
        set_config(cfg)


class KinemaServer(ThreadingHTTPServer):
    """Threading server built to stay up no matter what a client does. A dropped
    or misbehaving connection must never crash the process or spam tracebacks
    during a long-running session — that's the whole point of running for hours."""
    daemon_threads = True          # handler threads never block shutdown
    allow_reuse_address = True
    request_queue_size = 128       # absorb short connection bursts instead of refusing

    def verify_request(self, request, client_address):
        # Decided at accept() time, before any HTTP is read — a rejected peer's
        # connection is closed immediately. Uses the real peer IP, so it can't be
        # bypassed with a forged Host header.
        return peer_allowed(client_address[0] if client_address else "")

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        # client went away mid-request (closed tab, sleeping phone, paused
        # stream) — completely expected; stay silent and keep serving.
        if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                            ConnectionAbortedError, TimeoutError, socket.timeout)):
            return
        # anything else: a one-line note, but the server stays up.
        try:
            who = client_address[0] if client_address else "?"
            print(f"  (handled request error from {who}: {type(exc).__name__})")
        except Exception:
            pass


def _probe_kinema(port):
    """True if a Kinema instance is already answering on this port (so a second
    launch can just open a tab instead of crashing on a port clash)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/session", timeout=1.5) as r:
            return json.loads(r.read() or b"{}").get("app") == APP_NAME
    except Exception:
        return False


def _firefox_path():
    """Locate the Firefox executable (used by the app/kiosk window modes)."""
    for name in ("firefox", "firefox-esr"):
        p = shutil.which(name)
        if p:
            return p
    guesses = []
    if sys.platform == "darwin":
        guesses = ["/Applications/Firefox.app/Contents/MacOS/firefox",
                   str(Path.home() / "Applications/Firefox.app/Contents/MacOS/firefox")]
    elif os.name == "nt":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                guesses.append(str(Path(base) / "Mozilla Firefox" / "firefox.exe"))
    for g in guesses:
        if Path(g).exists():
            return g
    return None


def _launch_browser(port):
    """Open Kinema in the browser according to LAUNCH_MODE:
      tab    - a new tab in your normal browser (Firefox preferred) [default]
      app    - a dedicated Kinema window (its own Firefox profile, not a tab)
      kiosk  - fullscreen with no browser chrome (TV / cinema mode)
    app/kiosk fall back to a normal tab if Firefox can't be located."""
    url = f"http://127.0.0.1:{port}"
    if LAUNCH_MODE in ("app", "kiosk"):
        ff = _firefox_path()
        if ff:
            try:
                profile = STATE_DIR / "app-profile"
                profile.mkdir(parents=True, exist_ok=True)
                cmd = [ff, "--no-remote", "--profile", str(profile),
                       "--kiosk" if LAUNCH_MODE == "kiosk" else "--new-window", url]
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass  # fall back to a normal tab below
    try:
        try:
            webbrowser.get("firefox").open_new_tab(url)
        except webbrowser.Error:
            webbrowser.open_new_tab(url)
    except Exception:
        pass


def main():
    global READONLY, ALLOW_BROWSE, LAN_MODE, ALLOW_ANY_HOST
    global ALLOWED_HOSTS, SERVER_URLS, DEMO_ROOT, LAUNCH_MODE
    global PORT, BIND_HOST, LAN_TOGGLEABLE, PW_SALT, PW_HASH

    parser = argparse.ArgumentParser(
        prog="kinema", description=f"{APP_NAME} - a personal cinema in a browser tab")
    parser.add_argument("roots", nargs="*", help="library folder(s) to add")
    parser.add_argument("--host", default=None, help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("KINEMA_PORT", 8000)))
    parser.add_argument("--lan", action="store_true",
                        help="serve on your whole local network (binds 0.0.0.0)")
    parser.add_argument("--password", default=os.environ.get("KINEMA_PASSWORD"),
                        help="require this password to access (recommended with --lan)")
    parser.add_argument("--read-only", action="store_true",
                        default=os.environ.get("KINEMA_READONLY") in ("1", "true", "yes"),
                        help="disable all file management (demo / kiosk mode)")
    parser.add_argument("--demo", action="store_true",
                        help="try Kinema instantly: auto-generate sample videos, serve read-only")
    parser.add_argument("--no-browse", action="store_true",
                        help="disable the server-side folder picker")
    parser.add_argument("--allowed-host", action="append", default=[],
                        help="extra hostname/domain allowed in the Host header (repeatable)")
    parser.add_argument("--allow-any-host", action="store_true",
                        help="disable Host allow-listing (NOT recommended)")
    parser.add_argument("--app", action="store_true",
                        help="open in a dedicated Kinema window (its own app window, not a browser tab)")
    parser.add_argument("--kiosk", action="store_true",
                        help="open fullscreen with no browser chrome (TV / cinema mode)")
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args()

    mode_env = os.environ.get("KINEMA_LAUNCH_MODE", "").strip().lower()
    LAUNCH_MODE = ("kiosk" if (args.kiosk or mode_env == "kiosk")
                   else "app" if (args.app or mode_env == "app")
                   else "tab")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    start_cache_janitor()   # regularly clears prepared files you're no longer watching

    # Already running? Act like a normal desktop app: just open a new tab and
    # exit, instead of crashing trying to re-bind the port. This makes every
    # entry point (the .exe, the `kinema` command, double-clicking a launcher
    # twice) idempotent.
    if _probe_kinema(args.port):
        print(f"  {APP_NAME} is already running at http://127.0.0.1:{args.port}")
        if not args.no_open:
            print("  Opening it in your browser...")
            _launch_browser(args.port)
        return

    # roots from CLI -> config (skipped in demo mode, which uses its own root)
    if args.roots and not args.demo:
        cfg = get_config()
        existing = list(cfg.get("roots", []))
        for r in args.roots:
            try:
                p = Path(r).expanduser().resolve()
            except OSError:
                continue
            if p.is_dir() and str(p) not in existing:
                existing.append(str(p))
            elif not p.is_dir():
                print(f"  (skipping '{r}': not a folder)")
        cfg["roots"] = existing
        set_config(cfg)

    # security config
    PORT = args.port
    # Always bind 0.0.0.0 so network sharing can be switched on from the app
    # without a restart; peer_allowed() (via KinemaServer.verify_request) keeps it
    # loopback-only until sharing is actually on. An explicit --host is still honoured.
    LAN_MODE = bool(args.lan) or bool(get_config().get("lan"))
    bind_host = args.host or "0.0.0.0"
    BIND_HOST = bind_host
    try:
        LAN_TOGGLEABLE = ipaddress.ip_address(_host_part(bind_host) or bind_host).is_unspecified
    except ValueError:
        LAN_TOGGLEABLE = False
    # CLI/env --password wins for this run (in-memory only); otherwise restore a
    # password set earlier from the app itself (persisted, hashed, in config.json).
    if args.password:
        set_password(args.password, persist=False)
    else:
        _saved = get_config().get("auth")
        if isinstance(_saved, dict) and _saved.get("salt") and _saved.get("hash"):
            PW_SALT, PW_HASH = _saved["salt"], _saved["hash"]
    READONLY = bool(args.read_only)
    ALLOW_BROWSE = not args.no_browse
    ALLOW_ANY_HOST = args.allow_any_host

    if args.demo:
        demo_dir = STATE_DIR / "demo-library"
        print("  Preparing demo library (generating sample clips, one moment)...")
        if not build_demo_library(demo_dir):
            print("  WARNING: couldn't generate demo clips (is ffmpeg available?).")
        DEMO_ROOT = demo_dir.resolve()
        READONLY = True
        ALLOW_BROWSE = False

    env_hosts = os.environ.get("KINEMA_ALLOWED_HOSTS", "")
    extra = set(args.allowed_host) | {h.strip() for h in env_hosts.split(",") if h.strip()}
    ALLOWED_HOSTS = {h.lower() for h in (local_hostnames() | extra)}
    bh = _host_part(bind_host) or bind_host
    try:
        # never allow-list a wildcard bind address (0.0.0.0 / ::)
        if not ipaddress.ip_address(bh).is_unspecified:
            ALLOWED_HOSTS.add(bh)
    except ValueError:
        ALLOWED_HOSTS.add(bh)

    SERVER_URLS = compute_server_urls()
    lan_ips = sorted(h for h in local_hostnames() if _is_lan_ip(h)) if LAN_MODE else []

    print("=" * 64)
    print(f"  {APP_NAME} {APP_VERSION}  -  a personal cinema in a browser tab")
    print("  by Pentarosa Co.  -  MIT licensed")
    print("=" * 64)
    print(f"  Local:   http://127.0.0.1:{args.port}")
    for ip in lan_ips:
        print(f"  Network: http://{ip}:{args.port}   (open this on your phone/TV)")
    roots = real_roots()
    if roots:
        print("  Library:")
        for r in roots:
            print(f"    - {r}")
    else:
        print("  No library folders yet - add one in Settings (gear icon).")
    print(f"  Login:   {'password required' if password_required() else 'none (anyone on an allowed host)'}")
    print(f"  Mode:    {'DEMO (read-only)' if args.demo else ('READ-ONLY' if READONLY else 'full control')}")
    print(f"  ffmpeg:  {FFMPEG or 'NOT found (thumbnails disabled)'}")
    if LAN_MODE and not password_required():
        print("  NOTE: sharing is on with no password — anyone on your network can watch & manage. Set one in Settings.")
    print("  Press Ctrl+C to stop.")
    print("=" * 64)

    mimetypes.init()
    try:
        httpd = KinemaServer((bind_host, args.port), Handler)
    except OSError as e:
        print(f"  Couldn't start on port {args.port}: {e}")
        print("  Another program may be using it — try a different --port.")
        sys.exit(1)
    httpd.daemon_threads = True

    if not args.no_open:
        def _open():
            time.sleep(0.6)
            _launch_browser(args.port)
        threading.Thread(target=_open, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  {APP_NAME} stopped. Bye!")
    finally:
        httpd.server_close()


def _is_lan_ip(h):
    try:
        ip = ipaddress.ip_address(h)
        return ip.version == 4 and ip.is_private and not ip.is_loopback
    except ValueError:
        return False


if __name__ == "__main__":
    main()
