"""Archive — reclaim disk by re-encoding a finished show/movie to a more efficient
codec, kept fully watchable. The honest framing: truly *lossless* re-encoding of
already-compressed video makes it bigger, so this is "visually lossless" — a
high-quality setting at full resolution (imperceptible loss, real savings), to AV1
by default (plays natively), else HEVC/H.264 depending on what ffmpeg has.

One bounded background worker, **one encode at a time** (no fork-bombing the box —
see CLAUDE.md). Each file: probe → skip if already efficient/tiny → encode to a temp
file with a generous timeout + cancel → verify it's valid and actually smaller →
move the original to .kadmu-trash (recoverable) and swap the smaller file in under
the same name (so resume positions and catalog grouping survive). On any failure the
original is left untouched.

Sits above store/media/library, below handler (nothing here imports handler)."""
from __future__ import annotations
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .const import (
    FFMPEG, VIDEO_EXTS, TEXT_SUB_CODECS, TRASH_DIRNAME,
    ARCHIVE_PATH, ARCHIVE_CODEC, ARCHIVE_CRF, ARCHIVE_PRESET, ARCHIVE_KEEP_ORIGINAL,
    ARCHIVE_MIN_SAVING, ARCHIVE_SKIP_VCODECS, ARCHIVE_MIN_BYTES,
    load_json, save_json,
)
from .media import probe_meta, av1_encoder, hevc_encoder, _h264_encoder
from .store import resolve_within_roots, _migrate_progress
from .library import op_delete, request_reindex

_MAX_TITLE_FILES = 5000     # safety cap when expanding a show folder

# --------------------------------------------------------------------------- #
# Encoder selection — predictable software encoders that take -crf. (Hardware
# encoders vary too much per-vendor to drive reliably here; a future enhancement.)
# --------------------------------------------------------------------------- #
def _pick_encoder():
    """(codec_label, ffmpeg_encoder) honouring ARCHIVE_CODEC, falling back to
    whatever the local ffmpeg actually offers. (None, None) if nothing works."""
    order = {
        "av1":  ("av1", "hevc", "h264"),
        "hevc": ("hevc", "av1", "h264"),
        "h264": ("h264", "hevc", "av1"),
    }.get(ARCHIVE_CODEC, ("av1", "hevc", "h264"))
    pick = {"av1": av1_encoder, "hevc": hevc_encoder, "h264": _h264_encoder}
    for codec in order:
        enc = pick[codec]()
        if enc:
            return codec, enc
    return None, None


def encoder_available():
    return _pick_encoder()[1] is not None


def _default_crf(enc):
    # Quality-leaning defaults (lower = better/larger). "Visually lossless" territory.
    return {"libsvtav1": 28, "libaom-av1": 28, "libx265": 22,
            "libx264": 20, "libopenh264": 23}.get(enc, 24)


def _video_args(enc):
    crf = ARCHIVE_CRF or _default_crf(enc)
    if enc == "libsvtav1":
        return ["-c:v", "libsvtav1", "-crf", str(crf), "-preset", (ARCHIVE_PRESET or "6")]
    if enc == "libaom-av1":
        return ["-c:v", "libaom-av1", "-crf", str(crf), "-b:v", "0", "-cpu-used", "6", "-row-mt", "1"]
    if enc == "libx265":
        # hvc1 tag so the resulting MP4 is widely playable; full source bit-depth kept.
        return ["-c:v", "libx265", "-crf", str(crf), "-preset", (ARCHIVE_PRESET or "medium"), "-tag:v", "hvc1"]
    if enc == "libx264":
        return ["-c:v", "libx264", "-crf", str(crf), "-preset", (ARCHIVE_PRESET or "medium"), "-pix_fmt", "yuv420p"]
    if enc == "libopenh264":
        return ["-c:v", "libopenh264", "-q", str(crf), "-pix_fmt", "yuv420p"]
    return ["-c:v", enc]


def _attempts(src: Path, out: Path, varargs, sub_ords):
    """ffmpeg commands, most-preserving first: (1) copy every audio track + carry
    text subtitles, (2) copy audio, drop subs, (3) re-encode audio to AAC, drop subs.
    A later attempt only runs if the earlier one failed (some containers/codecs can't
    be copied into MP4) — so we keep quality where we can, but always finish."""
    head = [FFMPEG, "-nostdin", "-v", "error", "-y", "-i", str(src)]
    vmap = ["-map", "0:v:0"]
    amap = ["-map", "0:a?"]
    smap = []
    for o in sub_ords:
        smap += ["-map", f"0:s:{o}?"]
    meta = ["-map_metadata", "0", "-map_chapters", "0"]
    prog = ["-progress", "pipe:1", "-nostats"]
    tail = ["--", str(out)]
    a1 = head + vmap + amap + smap + varargs + ["-c:a", "copy", "-c:s", "mov_text"] + meta + prog + tail
    a2 = head + vmap + amap + varargs + ["-c:a", "copy", "-sn"] + meta + prog + tail
    a3 = head + vmap + amap + varargs + ["-c:a", "aac", "-b:a", "256k", "-sn"] + meta + prog + tail
    return [a1, a2, a3] if sub_ords else [a2, a3]


# --------------------------------------------------------------------------- #
# The persistent result store (data/archive.json): {final_path: {...savings...}}
# --------------------------------------------------------------------------- #
_store_mem: dict | None = None
_store_lock = threading.Lock()


def _store():
    global _store_mem
    if _store_mem is None:
        d = load_json(ARCHIVE_PATH, {})
        _store_mem = d if isinstance(d, dict) else {}
    return _store_mem


def _load_store():
    with _store_lock:
        return dict(_store())


def archived_keys():
    """The set of library paths that ARE archived results — cheap (a dict-key set, no
    probing), so the catalog can flag archived/suggestible titles per request."""
    with _store_lock:
        return set(_store().keys())


def _record(final: Path, src: Path, codec, oldb, newb, saved):
    with _store_lock:
        _store()[str(final)] = {
            "status": "done", "codec": codec, "originalPath": str(src),
            "originalBytes": oldb, "newBytes": newb, "saved": saved,
            "when": time.time(), "kept": ARCHIVE_KEEP_ORIGINAL,
        }
        save_json(ARCHIVE_PATH, _store_mem)


# --------------------------------------------------------------------------- #
# Job queue + single background worker
# --------------------------------------------------------------------------- #
_cond = threading.Condition()        # guards _queue / _active / _active_proc
_queue: list = []
_active: dict | None = None
_active_proc = None
_cancel = threading.Event()
_worker: threading.Thread | None = None


def _safe_kill(proc):
    try:
        proc.kill()
    except OSError:
        pass


def _safe_unlink(p: Path):
    try:
        p.unlink()
    except OSError:
        pass


def _unique(p: Path):
    if not p.exists():
        return p
    i = 1
    while True:
        cand = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not cand.exists():
            return cand
        i += 1


def _title_files(target: Path):
    """Every video file at/under a title (a show folder or a single movie file)."""
    if target.is_file():
        return [target] if target.suffix.lower() in VIDEO_EXTS else []
    out = []
    for dp, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != TRASH_DIRNAME]
        for fn in sorted(files):
            if fn.startswith("."):
                continue
            if Path(fn).suffix.lower() in VIDEO_EXTS:
                out.append(Path(dp) / fn)
                if len(out) >= _MAX_TITLE_FILES:
                    return out
    return out


def _kept_name(src: Path):
    """Where the 'keep both' policy writes the archived copy."""
    return src.parent / f"{src.stem} (archived).mp4"


def _retire(src: Path, keep: str):
    """Remove the original after a verified re-encode, per policy. Returns True on success."""
    if keep == "delete":
        try:
            src.unlink()
            return True
        except OSError:
            return False
    ok, _msg = op_delete(str(src))     # move into the root's .kadmu-trash (recoverable)
    return ok


def _place_result(src: Path, tmp: Path):
    """Put the finished temp encode where it belongs (per ARCHIVE_KEEP_ORIGINAL) and
    retire the original. Returns the final Path, or None if it couldn't be placed."""
    keep = ARCHIVE_KEEP_ORIGINAL
    if keep == "keep":
        final = _unique(_kept_name(src))
        try:
            tmp.replace(final)
            return final
        except OSError:
            return None
    # trash / delete: the smaller file takes the original's place
    final = src.with_suffix(".mp4")
    if final == src:
        if not _retire(src, keep):          # free the path first
            return None
        try:
            tmp.replace(final)
            return final
        except OSError:
            return None
    if final.exists():                       # a same-stem .mp4 already sits alongside
        final = _unique(final)
    try:
        tmp.replace(final)
    except OSError:
        return None
    if _retire(src, keep):
        try:
            _migrate_progress(src, final)    # keep resume positions across the rename
        except Exception:
            pass
    return final


def _verify(src_size: int, dur, tmp: Path):
    """A re-encode is only accepted if it exists, is meaningfully smaller, and probes
    as a complete, valid video (full duration). Otherwise we keep the original."""
    try:
        ns = tmp.stat().st_size
    except OSError:
        return False
    if ns <= 0 or ns > src_size * (1 - ARCHIVE_MIN_SAVING):
        return False
    meta = probe_meta(tmp)
    if not meta.get("vcodec"):
        return False
    nd = meta.get("duration") or 0
    if dur and nd and abs(nd - dur) / dur > 0.02:
        return False
    return True


def _run_one(cmd, total_dur, job):
    """Run one ffmpeg encode, streaming progress into `job`, killable via _cancel and
    bounded by a duration-proportional watchdog. Returns 'ok' | 'cancelled' | 'error'."""
    global _active_proc
    timeout = max(1800.0, (total_dur or 0) * 40.0)     # generous; long encodes are legit
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, text=True)
    except OSError:
        return "error"
    with _cond:
        _active_proc = proc
    killer = threading.Timer(timeout, _safe_kill, args=(proc,))
    killer.daemon = True
    killer.start()
    try:
        for line in proc.stdout:
            if _cancel.is_set():
                _safe_kill(proc)
                break
            line = line.strip()
            if line.startswith("out_time_us=") and total_dur:
                try:
                    us = int(line.split("=", 1)[1])
                    job["percent"] = max(0, min(99, int(us / 10000.0 / total_dur)))
                except (ValueError, ZeroDivisionError):
                    pass
    except (OSError, ValueError):
        pass
    finally:
        killer.cancel()
        try:
            proc.stdout.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except (subprocess.SubprocessError, OSError):
            _safe_kill(proc)
        with _cond:
            _active_proc = None
    if _cancel.is_set():
        return "cancelled"
    return "ok" if proc.returncode == 0 else "error"


def _archive_file(src: Path, job):
    """Encode one file end-to-end. Returns (status, message, bytes_saved) where status
    is 'ok' | 'skip' | 'cancelled' | 'error'."""
    try:
        size = src.stat().st_size
    except OSError:
        return "error", "file is gone", 0
    if size < ARCHIVE_MIN_BYTES:
        return "skip", "too small to bother", 0
    meta = probe_meta(src)
    if (meta.get("vcodec") or "").lower() in ARCHIVE_SKIP_VCODECS:
        return "skip", "already an efficient codec", 0
    dur = meta.get("duration") or 0
    codec, enc = _pick_encoder()
    if not enc:
        return "error", "no encoder available", 0
    try:                                    # need headroom for the temp output
        if shutil.disk_usage(src.parent).free < size + 64 * 1024 * 1024:
            return "error", "not enough free space", 0
    except OSError:
        pass
    sub_ords = [s["ord"] for s in (meta.get("subs") or []) if s.get("codec") in TEXT_SUB_CODECS]
    varargs = _video_args(enc)
    tmp = src.parent / f".kadmu-archiving-{os.getpid()}-{abs(hash(str(src))) % 100000}.tmp.mp4"
    _safe_unlink(tmp)
    status = "error"
    for cmd in _attempts(src, tmp, varargs, sub_ords):
        _safe_unlink(tmp)
        status = _run_one(cmd, dur, job)
        if status in ("ok", "cancelled"):
            break
    if status == "cancelled":
        _safe_unlink(tmp)
        return "cancelled", "", 0
    if status != "ok" or not _verify(size, dur, tmp):
        _safe_unlink(tmp)
        return "error", "encode failed or no real saving", 0
    newsize = tmp.stat().st_size
    final = _place_result(src, tmp)
    if final is None:
        _safe_unlink(tmp)
        return "error", "could not replace the original", 0
    saved = size - newsize
    _record(final, src, codec, size, newsize, saved)
    return "ok", "", saved


def _process_job(job):
    any_change = False
    for src in list(job["files"]):
        if _cancel.is_set():
            with _cond:
                job["state"] = "cancelled"
            break
        with _cond:
            job["current"] = src.name
            job["percent"] = 0
        status, msg, saved = _archive_file(src, job)
        with _cond:
            job["doneCount"] += 1
            job["current"] = None
            job["percent"] = 0
            if status == "ok":
                job["okCount"] += 1
                job["saved"] += saved
                any_change = True
            elif status == "skip":
                job["skipCount"] += 1
            elif status == "cancelled":
                job["state"] = "cancelled"
            else:
                job["failCount"] += 1
            if msg and status in ("skip", "error"):
                job["messages"] = (job["messages"] + [f"{src.name}: {msg}"])[-12:]
        if job["state"] == "cancelled":
            break
    if job["state"] != "cancelled":
        with _cond:
            job["state"] = "done"
    if any_change:
        try:
            request_reindex()       # files changed on disk -> refresh the catalog
        except Exception:
            pass


def _worker_loop():
    global _active
    while True:
        with _cond:
            while not _queue:
                _cond.wait()
            job = _queue.pop(0)
            _active = job
            _cancel.clear()
            job["state"] = "running"
        try:
            _process_job(job)
        except Exception as e:        # never let the worker thread die
            with _cond:
                job["state"] = "error"
                job["messages"] = (job.get("messages", []) + [str(e)[:200]])[-12:]
        finally:
            with _cond:
                _active = None


def _ensure_worker():
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_worker_loop, name="kadmu-archive", daemon=True)
        _worker.start()


# --------------------------------------------------------------------------- #
# Public API (called from handler routes)
# --------------------------------------------------------------------------- #
def enqueue(title_id: str):
    """Queue a title (show folder or movie file) for archiving. Returns a small status
    dict; skips files already archived or already queued/running."""
    target = resolve_within_roots(title_id, must_exist=True)
    if target is None:
        return {"ok": False, "error": "That title is no longer in your library."}
    if not encoder_available():
        return {"ok": False, "error": "ffmpeg has no AV1/HEVC/H.264 encoder to compress with."}
    files = _title_files(target)
    if not files:
        return {"ok": False, "error": "No video files to archive here."}
    store = _load_store()
    pending = [f for f in files
               if str(f) not in store and str(_kept_name(f)) not in store]
    with _cond:
        busy = set()
        if _active:
            busy |= {str(p) for p in _active["files"]}
        for j in _queue:
            busy |= {str(p) for p in j["files"]}
        pending = [f for f in pending if str(f) not in busy]
        if not pending:
            return {"ok": False, "error": "Nothing new to archive here — it's already compressed or in progress."}
        job = {
            "id": str(target), "name": target.name if target.is_dir() else target.stem,
            "files": pending, "total": len(pending), "doneCount": 0, "okCount": 0,
            "failCount": 0, "skipCount": 0, "saved": 0, "state": "queued",
            "current": None, "percent": 0, "queuedAt": time.time(), "messages": [],
        }
        _queue.append(job)
        _ensure_worker()
        _cond.notify_all()
    return {"ok": True, "queued": len(pending), "id": job["id"]}


def cancel(title_id: str | None = None):
    """Cancel the running job (and clear the queue) — or just the job matching
    title_id. The active encode is killed promptly."""
    with _cond:
        if title_id is None:
            _queue.clear()
            if _active:
                _cancel.set()
                if _active_proc:
                    _safe_kill(_active_proc)
        else:
            _queue[:] = [j for j in _queue if j["id"] != title_id]
            if _active and _active["id"] == title_id:
                _cancel.set()
                if _active_proc:
                    _safe_kill(_active_proc)
    return {"ok": True}


def _job_public(j):
    return {
        "id": j["id"], "name": j["name"], "total": j["total"],
        "doneCount": j["doneCount"], "okCount": j["okCount"],
        "failCount": j["failCount"], "skipCount": j["skipCount"],
        "saved": j["saved"], "state": j["state"], "current": j["current"],
        "percent": j["percent"], "messages": j["messages"][-4:],
    }


def status():
    """A snapshot for /api/archive: encoder availability, the active job + queue, and
    lifetime totals (files compressed, bytes saved)."""
    codec, enc = _pick_encoder()
    store = _load_store()
    total_saved = sum(r.get("saved", 0) for r in store.values() if isinstance(r, dict))
    with _cond:
        active = _job_public(_active) if _active else None
        queue = [_job_public(j) for j in _queue]
    return {
        "available": enc is not None, "codec": codec, "encoder": enc,
        "keepOriginal": ARCHIVE_KEEP_ORIGINAL,
        "active": active, "queue": queue,
        "totals": {"filesArchived": len(store), "bytesSaved": total_saved},
    }


def title_archive_state(title_id: str):
    """Per-title archive summary for /api/title: how many of its files are archived,
    bytes saved, and whether it's a candidate (has un-archived files)."""
    out = {"archived": 0, "total": 0, "fullyArchived": False, "saved": 0,
           "candidate": False, "available": encoder_available(),
           "running": False, "keepOriginal": ARCHIVE_KEEP_ORIGINAL}
    target = resolve_within_roots(title_id, must_exist=True)
    if target is None:
        return out
    store = _load_store()
    files = _title_files(target)
    archived = [f for f in files if str(f) in store]
    out["total"] = len(files)
    out["archived"] = len(archived)
    out["fullyArchived"] = bool(files) and len(archived) == len(files)
    out["saved"] = sum(store[str(f)].get("saved", 0) for f in archived)
    out["candidate"] = bool(files) and len(archived) < len(files)
    with _cond:
        out["running"] = bool(
            (_active and _active["id"] == str(target))
            or any(j["id"] == str(target) for j in _queue))
    return out
