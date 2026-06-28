"""ffmpeg-powered media: ffprobe metadata cache, thumbnails, folder covers, the
prepared-cache pruner, subtitle extraction (→ WebVTT), storyboard sprite sheets,
the demo-library generator, and the H.264 encoder probe. Everything degrades
gracefully when ffmpeg/ffprobe are absent. Depends only on const."""
from __future__ import annotations
import hashlib
import json
import os
import threading
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

from .const import (
    FFMPEG, FFPROBE, MIME, META_CACHE_PATH, CACHE_DIR, REMUX_DIR, STORYBOARD_DIR,
    SUBS_DIR, CACHE_MAX_BYTES, CACHE_TTL, NATIVE_EXTS, VIDEO_EXTS, SUBTITLE_EXTS,
    TEXT_SUB_CODECS, NATIVE_VCODECS, NATIVE_ACODECS, TRANSCODE_LADDER, WATCHED_FRAC,
    MP4_COPY_VCODECS, MP4_COPY_ACODECS,
    _meta_lock, _thumb_locks, _thumb_locks_guard, _cache_prune_lock,
    _cache_active, _cache_active_lock, _ffmpeg_sem, _cache_active_paths,
    load_json, save_json, natural_key,
)
from .store import resolve_within_roots

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


def _lang_display(code):
    return _LANG_NAMES.get((code or "").lower(), "")


def _audio_label(stream, ordinal):
    """Human label for an audio track: its title, else its language, else a number;
    with a channel hint (Stereo / 5.1 / …) appended when it adds information."""
    tags = stream.get("tags") or {}
    name = (tags.get("title") or "").strip() or _lang_display(tags.get("language")) \
        or f"Track {ordinal + 1}"
    ch, layout = stream.get("channels"), (stream.get("channel_layout") or "").strip()
    if layout in ("mono", "stereo"):
        hint = layout.capitalize()
    elif ch == 6:
        hint = "5.1"
    elif ch == 8:
        hint = "7.1"
    elif ch:
        hint = f"{ch}ch"
    else:
        hint = ""
    if hint and hint.lower() not in name.lower():
        name = f"{name} · {hint}"
    return name


def _sub_label(stream, ordinal):
    tags = stream.get("tags") or {}
    name = (tags.get("title") or "").strip() or _lang_display(tags.get("language")) \
        or f"Subtitles {ordinal + 1}"
    if (stream.get("disposition") or {}).get("forced"):
        name += " (forced)"
    return name


def probe_meta(path: Path):
    key = cache_key(path)
    if not key:
        return {}
    cached = _meta_cache_get(key)
    if cached is not None and cached.get("schema") == 4:   # current schema marker
        return cached                                       # (older entries fall through + re-probe)
    meta = {"schema": 4, "tracks": True, "duration": None, "width": None,
            "height": None, "vcodec": None, "acodec": None,
            "audios": [], "subs": [], "chapters": []}
    if FFPROBE:
        cmd = [FFPROBE, "-v", "quiet", "-print_format", "json",
               "-show_format", "-show_streams", "-show_chapters", "--", str(path)]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=30)
            info = json.loads(out.stdout or b"{}")
            fmt = info.get("format", {})
            if fmt.get("duration"):
                meta["duration"] = float(fmt["duration"])
            for c in info.get("chapters", []):
                try:
                    start = float(c.get("start_time"))
                except (TypeError, ValueError):
                    continue
                try:
                    end = float(c.get("end_time"))
                except (TypeError, ValueError):
                    end = None
                meta["chapters"].append({
                    "start": start, "end": end,
                    "title": (c.get("tags") or {}).get("title") or "",
                })
            a_ord = s_ord = 0
            for s in info.get("streams", []):
                ctype = s.get("codec_type")
                if ctype == "video" and meta["width"] is None:
                    meta["width"] = s.get("width")
                    meta["height"] = s.get("height")
                    meta["vcodec"] = s.get("codec_name")
                elif ctype == "audio":
                    if meta["acodec"] is None:
                        meta["acodec"] = s.get("codec_name")
                    lang = ((s.get("tags") or {}).get("language") or "").lower()
                    meta["audios"].append({
                        "ord": a_ord, "codec": (s.get("codec_name") or "").lower(),
                        "lang": lang or "und", "label": _audio_label(s, a_ord),
                        "default": bool((s.get("disposition") or {}).get("default")),
                    })
                    a_ord += 1
                elif ctype == "subtitle":
                    lang = ((s.get("tags") or {}).get("language") or "").lower()
                    meta["subs"].append({
                        "ord": s_ord, "codec": (s.get("codec_name") or "").lower(),
                        "lang": lang or "und", "label": _sub_label(s, s_ord),
                        "forced": bool((s.get("disposition") or {}).get("forced")),
                    })
                    s_ord += 1
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


# --------------------------------------------------------------------------- #
# Folder cover art — a poster/folder/cover image, else the first episode's thumb
# --------------------------------------------------------------------------- #
COVER_NAMES = ("poster", "folder", "cover", "fanart", "show", "default", "thumb")
COVER_IMAGE_EXTS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp"}


def _first_video(folder: Path, depth=2):
    """First video at or just below `folder`, in natural order. Bounded depth so a
    season-style tree (Show -> Season 1 -> episodes) still yields a cover without
    walking everything."""
    try:
        entries = sorted(os.scandir(folder), key=lambda e: natural_key(e.name))
    except OSError:
        return None
    subdirs = []
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            if e.is_file() and Path(e.name).suffix.lower() in VIDEO_EXTS:
                return Path(e.path)
            if e.is_dir():
                subdirs.append(Path(e.path))
        except OSError:
            continue
    if depth > 1:
        for d in subdirs:
            hit = _first_video(d, depth - 1)
            if hit:
                return hit
    return None


def folder_cover(folder: Path):
    """Return (image_path, mime) for a folder's cover: a poster/folder/cover image
    file if present, else a generated thumbnail of the first video found. Discovered
    paths are re-validated inside the library roots so a symlinked image can't leak a
    file from outside. Returns (None, None) when there's nothing to show."""
    try:
        files = {e.name.lower(): e.path for e in os.scandir(folder) if e.is_file()}
    except OSError:
        return None, None
    for base in COVER_NAMES:
        for ext, mime in COVER_IMAGE_EXTS.items():
            hit = files.get(base + ext)
            if hit:
                safe = resolve_within_roots(hit)
                if safe and safe.is_file():
                    return safe, mime
    vid = _first_video(folder)
    if vid:
        safe = resolve_within_roots(str(vid))
        if safe and safe.is_file():
            t = generate_thumb(safe)
            if t and t.exists():
                return t, "image/jpeg"
    return None, None


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


# Browser-native vs. non-native playback decisions live in browser_playable() above;
# the actual bytes are produced live by Handler._stream_remux / _stream_transcode,
# which pipe a fragmented MP4 straight to the client (playback starts in ~1-2s) rather
# than converting the whole file up front. MP4 can carry these codecs by stream-copy;
# anything else is transcoded to H.264/AAC on the fly.
# --------------------------------------------------------------------------- #
DEMO_SPECS = [
    ("Kadmu Demo Show/Season 1/Episode 1 - Pilot.mp4", "testsrc=size=854x480:rate=24", 12),
    ("Kadmu Demo Show/Season 1/Episode 2 - The Reveal.mp4", "testsrc2=size=854x480:rate=24", 10),
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
                        "url": "/api/sub?path=" + quote(sub_path), "embedded": False})
        except OSError:
            continue
    # text subtitle tracks carried *inside* the container (.mkv, .mp4 …) — extracted
    # to WebVTT on demand by /api/sub?track=N (see embedded_subtitle_vtt).
    for sub in (probe_meta(video).get("subs") or []):
        if sub.get("codec") not in TEXT_SUB_CODECS:
            continue
        label = sub.get("label") or _lang_display(sub.get("lang")) or "Embedded"
        out.append({"lang": sub.get("lang") or "und", "label": label,
                    "url": f"/api/sub?path={quote(str(video))}&track={sub['ord']}",
                    "embedded": True})
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


def embedded_subtitle_vtt(video: Path, ordinal: int):
    """Extract the Nth embedded *text* subtitle stream from `video` to WebVTT,
    caching the result on disk (keyed by path+mtime+size, like thumbnails). Returns
    VTT bytes, or None if unavailable. Image-based formats (PGS/VOBSUB) are filtered
    out before we ever get here — they can't become a text track."""
    if not FFMPEG:
        return None
    ck = cache_key(video)
    if ck is None or ordinal < 0:
        return None
    digest = hashlib.sha1(f"{ck}|s{ordinal}".encode("utf-8")).hexdigest()
    out = SUBS_DIR / f"{digest}.vtt"
    try:
        if out.exists() and out.stat().st_size > 0:
            return out.read_bytes()
    except OSError:
        pass
    SUBS_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, "-nostdin", "-v", "quiet", "-i", str(video),
           "-map", f"0:s:{ordinal}", "-f", "webvtt", "pipe:1"]
    with _ffmpeg_sem:
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            return None
    data = res.stdout or b""
    if not data.strip():
        return None
    if not data.lstrip().startswith(b"WEBVTT"):
        data = b"WEBVTT\n\n" + data
    try:
        out.write_bytes(data)
    except OSError:
        pass
    return data


# --------------------------------------------------------------------------- #
# Storyboard scrub previews (one sprite sheet of evenly-spaced frames per video)
# --------------------------------------------------------------------------- #
def _storyboard_paths(video: Path):
    ck = cache_key(video)
    if not ck:
        return None, None, None
    digest = hashlib.sha1(f"{ck}|sb".encode("utf-8")).hexdigest()
    return STORYBOARD_DIR / f"{digest}.jpg", STORYBOARD_DIR / f"{digest}.json", digest


def build_storyboard(video: Path):
    """Generate (once, cached) a sprite sheet of evenly-spaced thumbnails for the
    seek-bar scrub preview. Each frame is grabbed with a *fast input-seek* — no full
    decode — so this stays cheap even on a two-hour film, then the frames are
    montaged into a single JPEG via ffmpeg's tile filter. Returns
    {ok, cols, rows, count, interval, duration} so the player can slice the sprite."""
    sprite, meta_path, digest = _storyboard_paths(video)
    if sprite is None:
        return {"ok": False}
    try:
        if sprite.exists() and sprite.stat().st_size > 0 and meta_path.exists():
            return json.loads(meta_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    if not FFMPEG:
        return {"ok": False}
    duration = probe_meta(video).get("duration")
    if not duration or duration < 1:
        return {"ok": False}
    lock = _thumb_lock_for("sb-" + digest)
    with lock:
        try:                                   # another request may have just built it
            if sprite.exists() and sprite.stat().st_size > 0 and meta_path.exists():
                return json.loads(meta_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        # one tile every ~6s, but never fewer than 12 or more than 60 (caps the work)
        count = max(12, min(60, round(duration / 6)))
        interval = duration / count
        STORYBOARD_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STORYBOARD_DIR / f".tmp-{digest}"
        seq = STORYBOARD_DIR / f".seq-{digest}"
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(seq, ignore_errors=True)
        try:
            tmp.mkdir(parents=True, exist_ok=True)
        except OSError:
            return {"ok": False}
        made = []
        for i in range(count):
            t = min(duration - 0.1, (i + 0.5) * interval)
            frame = tmp / f"{i:05d}.jpg"
            cmd = [FFMPEG, "-nostdin", "-v", "quiet", "-ss", f"{max(0.0, t):.3f}",
                   "-i", str(video), "-frames:v", "1", "-an",
                   "-vf", "scale=160:-2", "-q:v", "5", "-y", "--", str(frame)]
            with _ffmpeg_sem:
                try:
                    subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=30)
                except (subprocess.SubprocessError, OSError):
                    pass
            if frame.exists() and frame.stat().st_size > 0:
                made.append(frame)
        if not made:
            shutil.rmtree(tmp, ignore_errors=True)
            return {"ok": False}
        # renumber the survivors into a contiguous sequence so the tiler has no gaps
        seq.mkdir(parents=True, exist_ok=True)
        for idx, f in enumerate(sorted(made)):
            try:
                f.replace(seq / f"{idx:05d}.jpg")
            except OSError:
                pass
        actual = len(list(seq.glob("*.jpg")))
        cols = min(10, actual) or 1
        rows = (actual + cols - 1) // cols
        tile_cmd = [FFMPEG, "-nostdin", "-v", "quiet", "-framerate", "1",
                    "-i", str(seq / "%05d.jpg"), "-frames:v", "1",
                    "-vf", f"tile={cols}x{rows}", "-q:v", "4", "-y", "--", str(sprite)]
        with _ffmpeg_sem:
            try:
                subprocess.run(tile_cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=60)
            except (subprocess.SubprocessError, OSError):
                pass
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(seq, ignore_errors=True)
        if not (sprite.exists() and sprite.stat().st_size > 0):
            return {"ok": False}
        info = {"ok": True, "cols": cols, "rows": rows, "count": actual,
                "interval": interval, "duration": duration}
        try:
            meta_path.write_text(json.dumps(info), "utf-8")
        except OSError:
            pass
        return info


def storyboard_image(video: Path):
    """Cached sprite-sheet JPEG bytes for `video` (building it if needed), or None."""
    info = build_storyboard(video)
    if not info or not info.get("ok"):
        return None
    sprite, _meta, _d = _storyboard_paths(video)
    try:
        if sprite and sprite.exists() and sprite.stat().st_size > 0:
            return sprite.read_bytes()
    except OSError:
        pass
    return None


