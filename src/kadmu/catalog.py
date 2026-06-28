"""Media catalog — the Netflix-style view of the library: group the flat file index
into *shows* (folders of SxxExx episodes, by season) and *movies* (standalone
files), expose a per-title detail (seasons → episodes + series-level resume), and
fold in the per-viewer thumbs rating.

Purely derived from the background library index, the resume table, and the
ratings store — no metadata service, no outbound calls, stdlib only. Sits above
store/media/library and below handler (nothing here imports handler)."""
from __future__ import annotations
import os
import re
import threading
from pathlib import Path

from .const import NATIVE_EXTS, VIDEO_EXTS, WATCHED_FRAC, natural_key
from .store import resolve_within_roots, load_progress, load_ratings
from .media import cache_key, _meta_snapshot
from .library import clean_title, _index_snapshot
from .archive import archived_keys, encoder_available

_index_cache_lock = threading.Lock()

# SxxEyy / 1x02 episode markers, and folders that name a season ("S4", "Season 1").
_SXEX = re.compile(r"(?i)\bs(\d{1,3})\s*[._ -]?\s*e(\d{1,3})")
_NXNN = re.compile(r"(?i)(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?![a-z0-9])")
_SEASON_DIR = re.compile(r"(?i)^(?:s|season|series|saison|temporada)\s*0*(\d{1,3})$|^0*(\d{1,3})$")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_MAX_DETAIL_EPISODES = 5000     # safety cap when walking one title folder


def _norm(stem: str) -> str:
    s = re.sub(r"\[[^\]]*\]", " ", stem)
    s = re.sub(r"[._]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_episode(name: str):
    """(season, episode) parsed from a filename, or None if it isn't an episode."""
    norm = _norm(Path(name).stem)
    m = _SXEX.search(norm)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _NXNN.search(norm)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def _season_from_dirname(dirname: str):
    m = _SEASON_DIR.match((dirname or "").strip())
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def series_dir_for(path: Path):
    """For an episode file, the folder that represents its *show* (hopping over a
    season subfolder like 'S4'), plus that folder's season number if it named one."""
    parent = path.parent
    snum = _season_from_dirname(parent.name)
    if snum is not None:
        return parent.parent, snum
    return parent, None


def _year_of(name: str):
    m = _YEAR.search(_norm(Path(name).stem))
    return int(m.group(0)) if m else None


def _frac(rec) -> float:
    pos = (rec or {}).get("position", 0) or 0
    dur = (rec or {}).get("duration") or 0
    return (pos / dur) if dur else 0.0


def _finished(rec) -> bool:
    return bool((rec or {}).get("duration")) and _frac(rec) >= WATCHED_FRAC


def _started(rec) -> bool:
    return ((rec or {}).get("position", 0) or 0) >= 5 or _frac(rec) >= 0.05


def _ep_record(path: Path, progress, meta_all, season=None, episode=None):
    """A player-ready video record for one episode/movie, with its resume state."""
    ext = path.suffix.lower()
    mkey = cache_key(path) or ""
    dur = (meta_all.get(mkey) or {}).get("duration")
    pr = progress.get(str(path)) or {}
    return {
        "name": path.name, "display": clean_title(path.name), "path": str(path), "ext": ext,
        "playable": True, "direct": ext in NATIVE_EXTS,
        "duration": dur or pr.get("duration"),
        "position": pr.get("position", 0) or 0, "updated": pr.get("updated", 0) or 0,
        "watched": _finished(pr), "season": season, "episode": episode,
    }


# --------------------------------------------------------------------------- #
# Catalog grouping — derived from the flat index, cached per index build so the
# /api/catalog and /api/title routes don't regroup the whole tree every request.
# (Per-viewer progress + ratings are overlaid live, never cached.)
# --------------------------------------------------------------------------- #
_grouped: dict | None = None
_grouped_built = None


def _grouped_index(snap):
    """{'shows': {series_id: {...}}, 'movies': [{...}]} grouped from the index
    snapshot, cached by the snapshot's build timestamp."""
    global _grouped, _grouped_built
    built = snap.get("built")
    with _index_cache_lock:
        if _grouped is not None and _grouped_built == built:
            return _grouped
    shows: dict[str, dict] = {}
    movies = []
    for v in snap.get("videos", []):
        p = Path(v["path"])
        ep = parse_episode(v["name"])
        if ep is None:
            movies.append({"id": v["path"], "name": v["display"], "path": v["path"],
                           "ext": v["ext"], "size": v["size"], "mtime": v.get("mtime", 0),
                           "direct": v["direct"], "mkey": v.get("mkey", ""),
                           "year": _year_of(v["name"])})
            continue
        season, _episode = ep
        sdir, sfolder = series_dir_for(p)
        sid = str(sdir)
        season_no = season if season is not None else (sfolder if sfolder is not None else 1)
        g = shows.get(sid)
        if g is None:
            g = shows[sid] = {"id": sid, "name": clean_title(sdir.name) or sdir.name,
                              "seasons": set(), "episodes": [], "mtime": 0}
        g["seasons"].add(season_no)
        g["episodes"].append(v["path"])
        g["mtime"] = max(g["mtime"], v.get("mtime", 0))
    out = {"shows": shows, "movies": movies, "built": built}
    with _index_cache_lock:
        _grouped, _grouped_built = out, built
    return out


def build_catalog():
    """The home-grid payload: every show and movie in the library, each with its
    poster source, counts, the viewer's rating, and (movies) resume progress."""
    snap = _index_snapshot()
    if snap is None:
        return {"shows": [], "movies": [], "ready": False}
    grouped = _grouped_index(snap)
    meta_all = _meta_snapshot()
    progress = load_progress()
    ratings = load_ratings()
    # Archive overlay (cheap: a set of already-archived paths + one encoder check). Powers
    # the "ready to archive" suggestion on fully-watched titles — manual + auto-suggest.
    akeys = archived_keys()
    can_archive = encoder_available()

    def rate(key):
        return _rating_int(ratings.get(key))

    shows = []
    for sid, g in grouped["shows"].items():
        watched = 0
        last = 0.0
        for ep in g["episodes"]:
            pr = progress.get(ep)
            if pr:
                last = max(last, pr.get("updated", 0) or 0)
                if _finished(pr):
                    watched += 1
        epcount = len(g["episodes"])
        archived = sum(1 for ep in g["episodes"] if ep in akeys)
        shows.append({
            "id": sid, "kind": "show", "name": g["name"],
            "seasonCount": len(g["seasons"]), "episodeCount": epcount,
            "watched": watched, "mtime": g["mtime"], "lastWatched": last,
            "rating": rate(sid), "archived": archived,
            "suggestArchive": can_archive and epcount > 0 and watched >= epcount and archived < epcount,
        })
    movies = []
    for m in grouped["movies"]:
        pr = progress.get(m["path"]) or {}
        is_archived = m["path"] in akeys
        watched = _finished(pr)
        movies.append({
            "id": m["id"], "kind": "movie", "name": m["name"], "path": m["path"],
            "ext": m["ext"], "size": m["size"], "mtime": m["mtime"], "year": m["year"],
            "playable": True, "direct": m["direct"],
            "duration": (meta_all.get(m["mkey"]) or {}).get("duration") or pr.get("duration"),
            "position": pr.get("position", 0) or 0, "watched": watched,
            "rating": rate(m["id"]), "archived": 1 if is_archived else 0,
            "suggestArchive": can_archive and watched and not is_archived,
        })
    shows.sort(key=lambda s: natural_key(s["name"]))
    movies.sort(key=lambda s: natural_key(s["name"]))
    return {"shows": shows, "movies": movies, "ready": True}


def _rating_int(rec):
    if isinstance(rec, dict):
        rec = rec.get("rating", 0)
    try:
        return max(-1, min(1, int(rec or 0)))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# Per-title detail (seasons → episodes, or a single movie) + series-level resume
# --------------------------------------------------------------------------- #
def title_detail(raw_id):
    """Detail for one catalog id (a show folder or a movie file path), or None."""
    target = resolve_within_roots(raw_id, must_exist=True)
    if target is None:
        return None
    if target.is_file():
        return _movie_detail(target)
    if target.is_dir():
        return _show_detail(target)
    return None


def _season_label(n):
    if n is None or n <= 0:
        return "Specials"
    return f"Season {n}"


def _show_detail(folder: Path):
    progress = load_progress()
    ratings = load_ratings()
    meta_all = _meta_snapshot()

    by_season: dict = {}
    count = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted((d for d in dirnames if not d.startswith(".")), key=natural_key)
        for fn in sorted(filenames, key=natural_key):
            if fn.startswith(".") or Path(fn).suffix.lower() not in VIDEO_EXTS:
                continue
            if count >= _MAX_DETAIL_EPISODES:
                break
            count += 1
            p = Path(dirpath) / fn
            ep = parse_episode(fn)
            if ep is not None:
                season, epno = ep
            else:
                season = _season_from_dirname(Path(dirpath).name) or 0
                epno = None
            by_season.setdefault(season, []).append(
                _ep_record(p, progress, meta_all, season=season, episode=epno))

    seasons = []
    flat = []
    for s in sorted(by_season.keys()):
        eps = sorted(by_season[s],
                     key=lambda r: (r["episode"] is None, r["episode"] or 0, natural_key(r["name"])))
        seasons.append({"season": s, "label": _season_label(s), "episodes": eps})
        flat.extend(eps)

    resume = _series_resume(flat)
    watched = sum(1 for r in flat if r["watched"])
    return {
        "id": str(folder), "kind": "show", "name": clean_title(folder.name) or folder.name,
        "seasonCount": len(seasons), "episodeCount": len(flat), "watched": watched,
        "rating": _rating_int(ratings.get(str(folder))),
        "resume": resume, "seasons": seasons,
    }


def _series_resume(flat):
    """The episode the 'Resume' button should play: the one you're mid-way through,
    else the next one after the last you finished, else the first episode."""
    if not flat:
        return None
    started = [r for r in flat if r["updated"]]
    if not started:
        first = dict(flat[0]); first["mode"] = "play"; return first
    last = max(started, key=lambda r: r["updated"])
    if not _finished(last):
        out = dict(last); out["mode"] = "resume"; return out
    idx = next((i for i, r in enumerate(flat) if r["path"] == last["path"]), -1)
    if 0 <= idx < len(flat) - 1:
        nxt = dict(flat[idx + 1]); nxt["mode"] = "next"; return nxt
    first = dict(flat[0]); first["mode"] = "replay"; return first


def _movie_detail(path: Path):
    progress = load_progress()
    ratings = load_ratings()
    meta_all = _meta_snapshot()
    rec = _ep_record(path, progress, meta_all)
    resume = dict(rec)
    resume["mode"] = "resume" if (_started(progress.get(str(path))) and not rec["watched"]) else "play"
    return {
        "id": str(path), "kind": "movie", "name": clean_title(path.name),
        "year": _year_of(path.name), "rating": _rating_int(ratings.get(str(path))),
        "video": rec, "resume": resume, "seasons": [],
        "episodeCount": 1, "seasonCount": 0, "watched": 1 if rec["watched"] else 0,
    }
