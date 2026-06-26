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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

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
    WEB_DIR = APP_DIR / "web"
    STATE_DIR = APP_DIR
DATA_DIR = STATE_DIR / "data"
CACHE_DIR = STATE_DIR / "cache" / "thumbs"

CONFIG_PATH = DATA_DIR / "config.json"
PROGRESS_PATH = DATA_DIR / "progress.json"
PLAYLISTS_PATH = DATA_DIR / "playlists.json"
META_CACHE_PATH = DATA_DIR / "meta_cache.json"

TRASH_DIRNAME = ".kinema-trash"

NATIVE_EXTS = {".mp4", ".m4v", ".webm", ".mov", ".ogv", ".ogg"}
VIDEO_EXTS = NATIVE_EXTS | {".mkv", ".avi", ".wmv", ".flv", ".ts", ".m2ts", ".mpg", ".mpeg", ".3gp"}

MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
    ".mov": "video/quicktime", ".ogv": "video/ogg", ".ogg": "video/ogg",
    ".mkv": "video/x-matroska", ".avi": "video/x-msvideo", ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv", ".ts": "video/mp2t", ".m2ts": "video/mp2t",
    ".mpg": "video/mpeg", ".mpeg": "video/mpeg", ".3gp": "video/3gpp",
}

def _find_tool(name, env_var):
    """Locate ffmpeg/ffprobe: explicit override, then bundled, then PATH."""
    override = os.environ.get(env_var)
    if override and Path(override).exists():
        return override
    exe = name + (".exe" if os.name == "nt" else "")
    search = [APP_DIR, Path(sys.executable).resolve().parent]
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
# Cap simultaneous ffmpeg processes so a flood of thumbnail requests can't
# fork-bomb the box.
_ffmpeg_sem = threading.Semaphore(2)

# --------------------------------------------------------------------------- #
# Runtime security configuration (populated in main())
# --------------------------------------------------------------------------- #
PASSWORD = None          # str | None  -- if set, login is required
READONLY = False         # disables all write/file operations (demo / kiosk)
ALLOW_BROWSE = True      # server-side directory picker enabled
LAN_MODE = False         # allow private-IP Host headers
ALLOW_ANY_HOST = False   # escape hatch: disable Host allow-listing
DEMO_ROOT = None         # when set (--demo), the only library root, served read-only
ALLOWED_HOSTS: set[str] = set()
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
    "/", "/index.html", "/app.js", "/style.css", "/favicon.svg",
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


def real_roots():
    if DEMO_ROOT is not None:
        return [DEMO_ROOT]
    roots = []
    for r in get_config().get("roots", []):
        p = Path(r).expanduser()
        try:
            p = p.resolve()
        except OSError:
            continue
        if p.is_dir():
            roots.append(p)
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
def _meta_cache_get(key):
    with _meta_lock:
        return load_json(META_CACHE_PATH, {}).get(key)


def _meta_cache_put(key, value):
    with _meta_lock:
        cache = load_json(META_CACHE_PATH, {})
        cache[key] = value
        if len(cache) > 20000:
            cache = dict(list(cache.items())[-10000:])
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


def generate_thumb(path: Path):
    out, digest = thumb_path(path)
    if out is None:
        return None
    if out.exists():
        return out
    if not FFMPEG:
        return None
    lock = _thumb_lock_for(digest)
    with lock:
        if out.exists():
            return out
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ts = 3.0
        dur = probe_meta(path).get("duration")
        if dur and dur > 2:
            ts = max(1.0, min(dur * 0.2, dur - 1.0))
        cmd = [FFMPEG, "-ss", str(ts), "-i", str(path), "-frames:v", "1",
               "-vf", "scale=480:-2", "-q:v", "4", "-y", "--", str(out)]
        with _ffmpeg_sem:
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=60)
            except (subprocess.SubprocessError, OSError):
                return None
    return out if out.exists() else None


# --------------------------------------------------------------------------- #
# Library scanning
# --------------------------------------------------------------------------- #
def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


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


def list_directory(path: Path):
    folders, videos = [], []
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
                })
            elif e.is_file() and Path(e.name).suffix.lower() in VIDEO_EXTS:
                ext = Path(e.name).suffix.lower()
                st = e.stat()
                meta = _meta_cache_get(f"{Path(e.path).resolve()}|{st.st_mtime_ns}|{st.st_size}") or {}
                videos.append({
                    "name": e.name,
                    "path": str(Path(e.path).resolve()),
                    "ext": ext,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "playable": ext in NATIVE_EXTS,
                    "duration": meta.get("duration"),
                })
        except OSError:
            continue
    folders.sort(key=lambda x: natural_key(x["name"]))
    videos.sort(key=lambda x: natural_key(x["name"]))
    return {"folders": folders, "videos": videos}


def list_roots():
    out = []
    for root in real_roots():
        out.append({
            "name": root.name or str(root),
            "path": str(root),
            "subfolders": _count_subfolders(root),
            "videos": _count_videos(root),
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


# --------------------------------------------------------------------------- #
# Built-in demo library (royalty-free ffmpeg test patterns)
# --------------------------------------------------------------------------- #
DEMO_SPECS = [
    ("Kinema Demo Show/Season 1/Episode 1 - Pilot.mp4", "testsrc=size=854x480:rate=24", 12),
    ("Kinema Demo Show/Season 1/Episode 2 - The Reveal.mp4", "testsrc2=size=854x480:rate=24", 10),
    ("Demo Movies/Fractal Voyage.mp4", "mandelbrot=size=854x480:rate=24", 15),
    ("Demo Movies/Color Bars Classic.mp4", "smptebars=size=854x480:rate=24", 8),
]


def _h264_encoder():
    if not FFMPEG:
        return None
    try:
        out = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                             capture_output=True, timeout=15).stdout.decode("utf-8", "ignore")
    except (subprocess.SubprocessError, OSError):
        return None
    for enc in ("libx264", "libopenh264"):
        if " " + enc in out:
            return enc
    return None


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
def continue_watching():
    progress = load_json(PROGRESS_PATH, {})
    items = []
    for path, rec in progress.items():
        pos = rec.get("position", 0)
        dur = rec.get("duration") or 0
        frac = (pos / dur) if dur else 0
        if dur and frac > 0.95:
            continue
        if pos < 5 and frac < 0.05:
            continue
        p = Path(path)
        if not p.exists() or owning_root(p) is None:
            continue
        items.append({
            "name": p.name, "path": str(p), "ext": p.suffix.lower(),
            "playable": p.suffix.lower() in NATIVE_EXTS,
            "position": pos, "duration": dur or rec.get("duration"),
            "updated": rec.get("updated", 0),
        })
    items.sort(key=lambda x: x["updated"], reverse=True)
    return items[:40]


# --------------------------------------------------------------------------- #
# File operations (rename / move / mkdir / delete-to-trash)
# --------------------------------------------------------------------------- #
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
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}

CSP = ("default-src 'self'; img-src 'self' data:; media-src 'self'; "
       "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"{APP_NAME}/{APP_VERSION}"

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
        if not PASSWORD:
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
        if route not in PUBLIC_ROUTES and not self._authed():
            self._send_json({"error": "Authentication required", "needAuth": True}, 401)
            return False
        return True

    def _require_writable(self):
        if READONLY:
            self._send_json({"error": "This instance is read-only."}, 403)
            return False
        return True

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
            "authRequired": bool(PASSWORD),
            "authed": self._authed(),
            "readonly": READONLY,
            "canManage": (not READONLY) and self._authed(),
            "canBrowse": ALLOW_BROWSE and (not READONLY) and self._authed(),
            "ffmpeg": bool(FFMPEG),
            "urls": SERVER_URLS,
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

        if route == "/api/session":
            return self._send_json(self._session_state())

        if route == "/api/config":
            return self._send_json(get_config())

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
            return self._serve_file_with_range(path, MIME.get(path.suffix.lower(), "application/octet-stream"))

        if route == "/api/progress":
            return self._send_json(load_json(PROGRESS_PATH, {}))

        if route == "/api/continue":
            return self._send_json(continue_watching())

        if route == "/api/playlists":
            return self._send_json(load_json(PLAYLISTS_PATH, {}))

        return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        route = urlparse(self.path).path

        if not self._guard(route, mutating=True):
            return
        body = self._read_body()

        if route == "/api/login":
            if not PASSWORD:
                return self._send_json({"ok": True, "authed": True})
            ip = self.client_address[0] if self.client_address else "?"
            allowed, retry = login_check(ip)
            if not allowed:
                return self._send_json(
                    {"ok": False, "error": f"Too many attempts. Try again in {retry}s."},
                    429, extra_headers={"Retry-After": str(retry)})
            supplied = str(body.get("password", ""))
            if hmac.compare_digest(supplied, PASSWORD):
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


def main():
    global PASSWORD, READONLY, ALLOW_BROWSE, LAN_MODE, ALLOW_ANY_HOST
    global ALLOWED_HOSTS, SERVER_URLS, DEMO_ROOT

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
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

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
    LAN_MODE = args.lan
    bind_host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    PASSWORD = args.password or None
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

    lan_ips = sorted(h for h in local_hostnames()
                     if _is_lan_ip(h)) if args.lan else []
    SERVER_URLS = [f"http://127.0.0.1:{args.port}"]
    SERVER_URLS += [f"http://{ip}:{args.port}" for ip in lan_ips]

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
    print(f"  Login:   {'password required' if PASSWORD else 'none (anyone on an allowed host)'}")
    print(f"  Mode:    {'DEMO (read-only)' if args.demo else ('READ-ONLY' if READONLY else 'full control')}")
    print(f"  ffmpeg:  {FFMPEG or 'NOT found (thumbnails disabled)'}")
    if args.lan and not PASSWORD:
        print("  NOTE: --lan without --password lets anyone on your network watch & manage.")
    print("  Press Ctrl+C to stop.")
    print("=" * 64)

    mimetypes.init()
    httpd = ThreadingHTTPServer((bind_host, args.port), Handler)
    httpd.daemon_threads = True

    if not args.no_open:
        def _open():
            time.sleep(0.6)
            url = f"http://127.0.0.1:{args.port}"
            try:
                try:
                    webbrowser.get("firefox").open(url)
                except webbrowser.Error:
                    webbrowser.open(url)
            except Exception:
                pass
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
