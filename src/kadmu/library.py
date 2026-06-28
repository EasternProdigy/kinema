"""Library surface: title cleanup, directory listing, the server-side folder
browser + native picker, Continue-watching, the background search index, and the
on-disk file operations (rename / move / mkdir / delete-to-trash) + trash upkeep.
Depends on const, rt, store, media."""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from .const import (
    NATIVE_EXTS, VIDEO_EXTS, SUBTITLE_EXTS, WATCHED_FRAC, TRASH_DIRNAME,
    INDEX_REFRESH, INDEX_MAX_VIDEOS, natural_key, _io_lock,
)
from .store import (
    real_roots, resolve_within_roots, owning_root, load_progress, _migrate_progress,
)
from .media import (
    probe_meta, browser_playable, folder_cover,
    cache_key, _meta_snapshot, _meta_cache_get,
)

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
    progress = load_progress()
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
                try:
                    f_mtime = e.stat().st_mtime
                except OSError:
                    f_mtime = 0
                folders.append({
                    "name": e.name,
                    "path": str(Path(e.path).resolve()),
                    "mtime": f_mtime,
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
    progress = load_progress()

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
# Home feed — a hero pick + "recently added" rail, all from LOCAL data (the
# background index + resume history). No metadata service, no outbound calls.
# --------------------------------------------------------------------------- #
def home_feed():
    """Build the root-view home surface: the newest videos across every root, and
    a hero (resume what you were watching, else the freshest addition)."""
    snap = _index_snapshot()
    meta_all = _meta_snapshot()
    recent = []
    if snap is not None:
        newest = sorted(snap.get("videos", []), key=lambda v: v.get("mtime", 0), reverse=True)[:24]
        for v in newest:
            recent.append({
                "name": v["name"], "display": v["display"], "path": v["path"], "ext": v["ext"],
                "size": v["size"], "mtime": v["mtime"], "playable": True, "direct": v["direct"],
                "duration": (meta_all.get(v["mkey"]) or {}).get("duration"),
            })
    cont = continue_watching()
    hero = None
    if cont:
        hero = dict(cont[0]); hero["reason"] = "resume"
    elif recent:
        hero = dict(recent[0]); hero["reason"] = "new"; hero["position"] = 0
    return {"hero": hero, "recent": recent}


# --------------------------------------------------------------------------- #
# Search (Netflix-style: type anywhere, find shows & episodes across all roots)
# --------------------------------------------------------------------------- #
def _search_rank(title: str, hay: str, q_full: str, terms):
    """Score a candidate for the search query, or return None if it isn't a match.

    Every query term must appear *somewhere* in `hay` (the title plus its folder
    trail), so "office jim" or "breaking bad s01e02" match across name and path.
    The score then rewards what reads as more relevant to a human: the full query
    as a contiguous run in the title, a title that starts with it, terms landing
    in the title itself (and on a word boundary) over terms that only matched the
    folder trail. Tighter titles edge out sprawling ones on ties."""
    title_l = title.lower()
    hay_l = hay.lower()
    if not all(t in hay_l for t in terms):
        return None
    score = 0.0
    if q_full and q_full in title_l:
        score += 140
        if title_l.startswith(q_full):
            score += 90
    elif q_full and q_full in hay_l:
        score += 35
    for t in terms:
        if t in title_l:
            score += 26
            if re.search(r"(?<![a-z0-9])" + re.escape(t), title_l):
                score += 14          # hit at a word start reads as more on-target
        else:
            score += 5               # term only lives in the folder trail
    score -= min(len(title_l), 60) * 0.05    # gently prefer tighter titles
    return score


def search_library(query: str, limit: int = 60):
    """Thorough, ranked search over the whole library — the engine behind the
    type-ahead dropdown and the full results page.

    Splits the query into terms and matches each against a file's cleaned display
    title, its raw name, *and* its folder trail (relative to the root), so people
    can find an episode by show name, season, episode number, or any words in the
    filename — in any order. Folders match on their name and trail too. Results
    are scored by `_search_rank` and returned best-first.

    Served from the background-built catalog (`_index_snapshot`) when ready, which
    makes search instant *and* complete — no per-query filesystem walk, no deadline
    or result cap to truncate big libraries. Until the first index finishes (e.g.
    just after startup) it falls back to a bounded live walk. Only paths inside a
    configured root are ever returned."""
    raw = (query or "").strip()
    q = raw.lower()
    if not q:
        return {"folders": [], "videos": [], "query": raw}
    terms = [t for t in re.split(r"\s+", q) if t]
    snap = _index_snapshot()
    if snap is not None:
        return _search_indexed(snap, q, terms, raw, limit)
    return _search_live(q, terms, raw, limit)


def _search_indexed(snap, q, terms, raw, limit):
    """Rank the in-memory catalog — pure CPU, no filesystem walk. Expensive per-result
    extras (folder counts) are computed only for the handful of folders we keep."""
    wdirs = watched_dirs()
    meta_all = _meta_snapshot()
    fmatches, vmatches = [], []
    for f in snap.get("folders", []):
        s = _search_rank(f["name"], f"{f['trail']} {f['name']}".strip(), q, terms)
        if s is not None:
            fmatches.append((s, f))
    for v in snap.get("videos", []):
        # title scoring sees the pretty title *and* the raw stem; the haystack also
        # carries the folder trail for path-only matches.
        hay = f"{v['trail']} {v['name']}".strip()
        s = _search_rank(f"{v['display']} {Path(v['name']).stem}", hay, q, terms)
        if s is not None:
            vmatches.append((s, v))
    # best score first; natural order breaks ties so seasons/episodes read in order
    fmatches.sort(key=lambda x: (-x[0], natural_key(x[1]["name"])))
    vmatches.sort(key=lambda x: (-x[0], natural_key(x[1]["name"])))
    fmatches, vmatches = fmatches[:limit], vmatches[:limit]
    folders = [{
        "name": f["name"], "path": f["path"],
        "subfolders": _count_subfolders(f["path"]),
        "videos": _count_videos(f["path"]),
        "watched": watched_in_tree(Path(f["path"]), wdirs),
    } for _s, f in fmatches]
    videos = [{
        "name": v["name"], "display": v["display"], "path": v["path"], "ext": v["ext"],
        "size": v["size"], "mtime": v["mtime"], "playable": True, "direct": v["direct"],
        "duration": (meta_all.get(v["mkey"]) or {}).get("duration"),
    } for _s, v in vmatches]
    return {"folders": folders, "videos": videos, "query": raw}


def _search_live(q, terms, raw, limit):
    """Filesystem-walk fallback used only until the background index is built.
    Bounded by a result cap and a wall-clock deadline to stay responsive."""
    folders, videos = [], []
    wdirs = watched_dirs()
    meta_all = _meta_snapshot()
    deadline = time.time() + 5.0
    cap = limit * 6                                  # gather extra, then rank + slice
    for root in real_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            if time.time() > deadline or (len(folders) + len(videos)) >= cap:
                break
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            here = Path(dirpath)
            try:
                rel = here.relative_to(root)
                trail = "" if str(rel) == "." else str(rel).replace(os.sep, " ")
            except ValueError:
                trail = ""
            for d in dirnames:
                s = _search_rank(d, f"{trail} {d}".strip(), q, terms)
                if s is None:
                    continue
                p = (here / d).resolve()
                folders.append({
                    "name": d, "path": str(p),
                    "subfolders": _count_subfolders(p),
                    "videos": _count_videos(p),
                    "watched": watched_in_tree(p, wdirs),
                    "_score": s,
                })
            for fn in filenames:
                if fn.startswith(".") or Path(fn).suffix.lower() not in VIDEO_EXTS:
                    continue
                disp = clean_title(fn)
                s = _search_rank(f"{disp} {Path(fn).stem}", f"{trail} {fn}".strip(), q, terms)
                if s is None:
                    continue
                p = (here / fn).resolve()
                try:
                    st = p.stat()
                except OSError:
                    continue
                ext = p.suffix.lower()
                meta = meta_all.get(f"{p}|{st.st_mtime_ns}|{st.st_size}") or {}
                videos.append({
                    "name": fn, "display": disp, "path": str(p), "ext": ext,
                    "size": st.st_size, "mtime": st.st_mtime, "playable": True,
                    "direct": ext in NATIVE_EXTS, "duration": meta.get("duration"),
                    "_score": s,
                })
        if time.time() > deadline or (len(folders) + len(videos)) >= cap:
            break
    folders.sort(key=lambda x: (-x["_score"], natural_key(x["name"])))
    videos.sort(key=lambda x: (-x["_score"], natural_key(x["name"])))
    folders, videos = folders[:limit], videos[:limit]
    for x in folders + videos:
        x.pop("_score", None)
    return {"folders": folders, "videos": videos, "query": raw}


# --------------------------------------------------------------------------- #
# Background library index (the catalog behind instant, complete search)
# --------------------------------------------------------------------------- #
# A daemon thread walks every root and builds a flat catalog of folders and video
# files (path, cleaned title, folder trail, size/mtime). Search ranks against this
# in memory instead of walking the disk per query. The walk repeats every
# INDEX_REFRESH seconds (so files added outside the app appear), and any mutation
# through the app (add folder, rename/move/delete) triggers an immediate rebuild.
_index_lock = threading.Lock()
_index_data: dict | None = None
_index_event = threading.Event()


def _index_snapshot():
    """The current catalog (a reference; never mutated in place), or None if the
    first build hasn't finished yet."""
    with _index_lock:
        return _index_data


def request_reindex():
    """Ask the indexer to rebuild now (e.g. after a library mutation)."""
    _index_event.set()


def _build_index():
    """Walk every root and build the search catalog. Runs off the request path, so it
    can be exhaustive (no deadline) without ever slowing a search down."""
    videos, folders = [], []
    for root in real_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            here = Path(dirpath)
            try:
                rel = here.relative_to(root)
                trail = "" if str(rel) == "." else str(rel).replace(os.sep, " ")
            except ValueError:
                trail = ""
            for d in dirnames:
                folders.append({"name": d, "path": str(here / d), "trail": trail})
            for fn in filenames:
                if fn.startswith(".") or Path(fn).suffix.lower() not in VIDEO_EXTS:
                    continue
                if len(videos) >= INDEX_MAX_VIDEOS:
                    continue                     # safety cap on pathological libraries
                p = here / fn
                try:
                    st = p.stat()
                except OSError:
                    continue
                ext = p.suffix.lower()
                videos.append({
                    "name": fn, "display": clean_title(fn), "path": str(p), "ext": ext,
                    "size": st.st_size, "mtime": st.st_mtime, "trail": trail,
                    "direct": ext in NATIVE_EXTS,
                    "mkey": f"{p}|{st.st_mtime_ns}|{st.st_size}",
                })
    return {"videos": videos, "folders": folders, "built": time.time()}


def _indexer_loop():
    global _index_data
    while True:
        try:
            built = _build_index()
            with _index_lock:
                _index_data = built
        except Exception:
            pass
        # sleep until the refresh interval elapses OR a rebuild is requested
        _index_event.wait(timeout=INDEX_REFRESH)
        _index_event.clear()


def start_indexer():
    threading.Thread(target=_indexer_loop, name="library-indexer", daemon=True).start()


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
# Trash maintenance — deletes are reversible (moved into each root's .kadmu-trash),
# so the trash has to be reaped or it grows forever. The cache janitor calls
# purge_trash(TRASH_TTL) on its sweeps; the user can also empty it on demand.
# --------------------------------------------------------------------------- #
def _path_size(path):
    """Total bytes of a file, or of a directory tree (best effort)."""
    try:
        st = os.stat(path)
    except OSError:
        return 0
    if not os.path.isdir(path):
        return st.st_size
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.stat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def purge_trash(older_than=None):
    """Permanently delete trashed items. With `older_than` (seconds) only those that
    have sat in the trash longer than that are removed; with None the trash is
    emptied. This is the one place Kadmu actually `rm`s — everything else is a move.
    Returns (items_removed, bytes_freed)."""
    removed, freed = 0, 0
    now = time.time()
    for root in real_roots():
        trash = root / TRASH_DIRNAME
        if not trash.is_dir():
            continue
        try:
            entries = list(os.scandir(trash))
        except OSError:
            continue
        for e in entries:
            try:
                mtime = e.stat(follow_symlinks=False).st_mtime
            except OSError:
                continue
            if older_than is not None and now - mtime <= older_than:
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    freed += _path_size(e.path)
                    shutil.rmtree(e.path, ignore_errors=True)
                else:
                    freed += e.stat().st_size
                    os.remove(e.path)
                removed += 1
            except OSError:
                pass
    return removed, freed


def trash_info():
    """Count and total size of everything currently in the trash (across roots)."""
    items, total = 0, 0
    for root in real_roots():
        trash = root / TRASH_DIRNAME
        if not trash.is_dir():
            continue
        try:
            for e in os.scandir(trash):
                items += 1
                total += _path_size(e.path)
        except OSError:
            continue
    return {"items": items, "bytes": total}


