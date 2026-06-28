"""Constants, paths, locks, and small JSON helpers — the foundation module.

Everything here is immutable after import (or a lock/namespace/dict that is only
ever mutated in place, never rebound), so other modules can safely do
``from .const import NAME``. Rebindable runtime flags live in rt.py instead.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import sys
import threading
from pathlib import Path

APP_NAME = "Kadmu"
APP_VERSION = "1.0.0"

# --------------------------------------------------------------------------- #
# Paths & constants
# --------------------------------------------------------------------------- #
# This file is src/kadmu/const.py, so APP_DIR (the `src/` dir) is two levels up —
# preserving the original layout where web assets are src/web and runtime state
# lives at the project root, one level above src/.
APP_DIR = Path(__file__).resolve().parent.parent
if getattr(sys, "frozen", False):
    # Running from a PyInstaller bundle: web assets live in the temp extract
    # dir, but config/cache must persist in a real user-writable location.
    WEB_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR)) / "web"
    STATE_DIR = Path.home() / ".kadmu"
else:
    # Running from source: web assets sit in src/web (next to this package), but
    # runtime state (config, caches, the bundled bin/ffmpeg) lives at the
    # project root, one level up from src/.
    WEB_DIR = APP_DIR / "web"
    STATE_DIR = APP_DIR.parent
DATA_DIR = STATE_DIR / "data"
CACHE_DIR = STATE_DIR / "cache" / "thumbs"
REMUX_DIR = STATE_DIR / "cache" / "remux"
STORYBOARD_DIR = STATE_DIR / "cache" / "storyboard"   # seek-bar scrub sprite sheets
SUBS_DIR = STATE_DIR / "cache" / "subs"   # extracted embedded subtitle tracks (.vtt)

# Hard ceiling on the prepared-video cache (remux + quality copies). Whenever a
# new file is cached we evict the least-recently-used ones until the folder is
# back under this size, so the cache can never grow without bound and fill the
# disk. Override with KADMU_CACHE_LIMIT_MB (e.g. 512 for a small laptop, 0 to
# keep only the file in use). Default: 2 GiB.
try:
    CACHE_MAX_BYTES = max(0, int(os.environ.get("KADMU_CACHE_LIMIT_MB", "2048"))) * 1024 * 1024
except ValueError:
    CACHE_MAX_BYTES = 2048 * 1024 * 1024

# A regular janitor deletes prepared files no one has touched in CACHE_TTL seconds,
# so the cache holds essentially just what you're watching now and clears the rest.
# The file currently streaming (and the most-recent one) is always kept, so pausing
# is safe. Override with KADMU_CACHE_TTL_SEC. Default: 5 minutes; swept every 60s.
try:
    CACHE_TTL = max(0, int(os.environ.get("KADMU_CACHE_TTL_SEC", "300")))
except ValueError:
    CACHE_TTL = 300
CACHE_SWEEP_INTERVAL = 60

# Trashed files (reversible deletes live in each root's .kadmu-trash) are purged
# for good once they've sat unwanted this long, so deleting can't slowly fill the
# disk. The same janitor that sweeps the cache handles it. Override with
# KADMU_TRASH_TTL_DAYS (0 = purge on the next sweep; default 14 days).
try:
    TRASH_TTL = max(0, int(os.environ.get("KADMU_TRASH_TTL_DAYS", "14"))) * 86400
except ValueError:
    TRASH_TTL = 14 * 86400

# Cap simultaneous live ffmpeg streams (remux/transcode of non-native files) so a
# handful of LAN viewers can't peg every core. Native files stream straight off
# disk and don't count. Override with KADMU_MAX_STREAMS. Default: 5.
try:
    MAX_STREAMS = max(1, int(os.environ.get("KADMU_MAX_STREAMS", "5")))
except ValueError:
    MAX_STREAMS = 5

# How often the background indexer re-walks the library so externally-added files
# show up in search without restarting. Mutations through the app trigger an
# immediate rebuild regardless. Override with KADMU_INDEX_REFRESH_SEC. Default: 5 min.
try:
    INDEX_REFRESH = max(10, int(os.environ.get("KADMU_INDEX_REFRESH_SEC", "300")))
except ValueError:
    INDEX_REFRESH = 300
# Safety cap so a pathologically huge tree can't exhaust memory building the index.
INDEX_MAX_VIDEOS = 200000

CONFIG_PATH = DATA_DIR / "config.json"
PROGRESS_PATH = DATA_DIR / "progress.json"
PLAYLISTS_PATH = DATA_DIR / "playlists.json"
MYLIST_PATH = DATA_DIR / "mylist.json"
META_CACHE_PATH = DATA_DIR / "meta_cache.json"
PROFILES_PATH = DATA_DIR / "profiles.json"   # opt-in per-viewer id -> {"name"}
DB_PATH = DATA_DIR / "kadmu.db"              # accounts mode (--accounts): users + per-user state

TRASH_DIRNAME = ".kadmu-trash"

NATIVE_EXTS = {".mp4", ".m4v", ".webm", ".mov", ".ogv", ".ogg"}
VIDEO_EXTS = NATIVE_EXTS | {".mkv", ".avi", ".wmv", ".flv", ".ts", ".m2ts", ".mpg", ".mpeg", ".3gp"}
# Sidecar subtitle files (next to the video) the player can show as captions.
SUBTITLE_EXTS = {".vtt", ".srt"}
# Embedded subtitle codecs that are *text* and so can be converted to WebVTT on the
# fly. Image-based tracks (PGS/VOBSUB/DVB) are bitmaps and can't become a <track>.
TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt",
                   "text", "subviewer", "stl", "microdvd"}

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


FFMPEG = _find_tool("ffmpeg", "KADMU_FFMPEG")
FFPROBE = _find_tool("ffprobe", "KADMU_FFPROBE")

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
# Per-request state (each request runs on its own thread): the active viewer profile.
_REQ = threading.local()
# Separate, larger cap for live playback streams (remux/transcode). These are
# long-lived (they run for as long as the video plays), so they get their own
# pool rather than competing with the short-lived thumbnail jobs above.
_stream_sem = threading.Semaphore(MAX_STREAMS)


def _cache_active_paths():
    with _cache_active_lock:
        return set(_cache_active)

# --------------------------------------------------------------------------- #
# Sessions (legacy shared-password), login throttle, public routes
# --------------------------------------------------------------------------- #
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
    "/", "/index.html", "/qr.js", "/style.css", "/favicon.svg",
    "/api/session", "/api/login", "/api/register",
}

# Codecs MP4 can carry by stream-copy (no re-encode); anything else is transcoded.
MP4_COPY_VCODECS = {"h264", "av1"}
MP4_COPY_ACODECS = {"aac", "mp3"}

# --------------------------------------------------------------------------- #
# JSON store helpers (atomic, used across modules)
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


def _json_obj(s):
    """Parse a JSON blob, always returning a dict ({} on anything unexpected)."""
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def natural_key(s: str):
    """Sort key that orders embedded numbers numerically (so 'ep2' < 'ep10')."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
