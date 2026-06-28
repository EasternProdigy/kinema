"""Library config (roots), resume progress, My List, and opt-in viewer profiles.
Every per-viewer helper branches on accounts mode: SQLite per-user (via accounts)
when on, the shared/profile JSON files when off."""
from __future__ import annotations
import re
import threading
import time
from pathlib import Path

from . import rt
from .accounts import (
    _current_uid, db_progress_all, db_set_progress, db_clear_progress,
    db_mylist_all, db_mylist_set, db_ratings_all, db_set_rating, db_migrate_path,
    db_prefs_get, db_prefs_set,
)
from .const import (
    CONFIG_PATH, PROGRESS_PATH, MYLIST_PATH, RATINGS_PATH, RECO_PREFS_PATH, PROFILES_PATH,
    DATA_DIR, NATIVE_EXTS, _io_lock, _REQ, load_json, save_json,
)

# Key under the per-user prefs blob (accounts mode) where reco dials live.
_RECO_PREFS_KEY = "recoWeights"

# --------------------------------------------------------------------------- #
# Viewer profiles (opt-in: separate progress + My List per person, --profiles)
# --------------------------------------------------------------------------- #
# When profiles are off (the default) every helper resolves to the single shared
# progress.json / mylist.json — identical to the original single-password design.
# When on, the active profile rides in on each request (X-Kadmu-Profile) and is
# stashed in the request thread-local; "default" still maps to the shared files so
# existing data and the no-profile experience are preserved.
def _profile_slug(name):
    s = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-")
    return s[:48] or "default"


def current_profile():
    return getattr(_REQ, "profile", "default") if rt.PROFILES_ENABLED else "default"


def progress_path_for(pid):
    if not rt.PROFILES_ENABLED or pid == "default":
        return PROGRESS_PATH
    return DATA_DIR / "profiles" / _profile_slug(pid) / "progress.json"


def mylist_path_for(pid):
    if not rt.PROFILES_ENABLED or pid == "default":
        return MYLIST_PATH
    return DATA_DIR / "profiles" / _profile_slug(pid) / "mylist.json"


def ratings_path_for(pid):
    if not rt.PROFILES_ENABLED or pid == "default":
        return RATINGS_PATH
    return DATA_DIR / "profiles" / _profile_slug(pid) / "ratings.json"


def _progress_path():
    return progress_path_for(current_profile())


def _mylist_path():
    return mylist_path_for(current_profile())


def _ratings_path():
    return ratings_path_for(current_profile())


def list_profiles():
    """Known viewer profiles, always including the shared 'Default'."""
    data = load_json(PROFILES_PATH, {})
    out = [{"id": "default", "name": "Default"}]
    if isinstance(data, dict):
        for pid, rec in data.items():
            if pid == "default":
                continue
            out.append({"id": pid, "name": (rec or {}).get("name") or pid})
    return out


def create_profile(name):
    """Create (or return existing) a viewer profile from a display name."""
    pid = _profile_slug(name)
    if pid == "default":
        return {"id": "default", "name": "Default"}
    with _io_lock:
        data = load_json(PROFILES_PATH, {})
        if not isinstance(data, dict):
            data = {}
        data[pid] = {"name": (name or "").strip()[:48] or pid, "created": time.time()}
        save_json(PROFILES_PATH, data)
    (DATA_DIR / "profiles" / pid).mkdir(parents=True, exist_ok=True)
    return {"id": pid, "name": data[pid]["name"]}


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
    if rt.DEMO_ROOT is not None:
        return [rt.DEMO_ROOT]
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
# Resume-progress store (kept in memory: this process is the only writer)
# --------------------------------------------------------------------------- #
# progress.json is consulted on nearly every request (browsing shows watch
# progress, "Continue watching", search). Re-reading and re-parsing it from disk
# each time made listing O(requests x file). Hold it in memory and persist only on
# change — same pattern as the metadata cache.
# Profile-aware in-memory resume tables: progress-file path -> table. With profiles
# off (or the "default" profile) this is just the one shared PROGRESS_PATH, so the
# fast in-memory path is unchanged; each extra viewer gets their own cached table.
_progress_mem: dict = {}
_progress_lock = threading.Lock()


def _progress_all():
    """The live in-memory progress dict for the active profile (call under lock)."""
    pp = str(_progress_path())
    tbl = _progress_mem.get(pp)
    if tbl is None:
        loaded = load_json(_progress_path(), {})
        tbl = loaded if isinstance(loaded, dict) else {}
        _progress_mem[pp] = tbl
    return tbl


def load_progress():
    """A shallow copy of the active viewer's resume table, safe to iterate without
    locking. Records are always replaced wholesale (never mutated in place), so
    callers can read the value dicts they get back. In accounts mode the table is
    scoped to the signed-in user (SQLite); otherwise it's the shared/profile JSON."""
    if rt.ACCOUNTS_ENABLED:
        uid = _current_uid()
        return db_progress_all(uid) if uid else {}
    with _progress_lock:
        return dict(_progress_all())


def save_progress(data: dict):
    """Replace the whole resume table for the active profile (memory + disk)."""
    with _progress_lock:
        _progress_mem[str(_progress_path())] = data
        save_json(_progress_path(), data)


def set_progress(path_str: str, rec: dict):
    """Upsert one resume entry for the active viewer."""
    if rt.ACCOUNTS_ENABLED:
        uid = _current_uid()
        if uid:
            db_set_progress(uid, path_str, rec)
        return
    with _progress_lock:
        cache = dict(_progress_all())
        cache[path_str] = rec
        _progress_mem[str(_progress_path())] = cache
        save_json(_progress_path(), cache)


def clear_progress(path_str: str | None):
    """Drop one entry (by path) or, with path_str=None, the whole table — for the
    active viewer."""
    if rt.ACCOUNTS_ENABLED:
        uid = _current_uid()
        if uid:
            db_clear_progress(uid, path_str)
        return
    with _progress_lock:
        if path_str is None:
            cache = {}
        else:
            cache = dict(_progress_all())
            cache.pop(path_str, None)
        _progress_mem[str(_progress_path())] = cache
        save_json(_progress_path(), cache)


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
# My List (Netflix-style watchlist of pinned shows / movies)
# --------------------------------------------------------------------------- #
def my_list_items():
    """Stored watchlist (active viewer), filtered to entries that still exist."""
    if rt.ACCOUNTS_ENABLED:
        uid = _current_uid()
        data = db_mylist_all(uid) if uid else {}
    else:
        data = load_json(_mylist_path(), {})
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
    """Add or remove a path from the active viewer's watchlist. Returns the
    updated paths set (or None if the path is outside the library)."""
    if rt.ACCOUNTS_ENABLED:
        uid = _current_uid()
        if uid is None:
            return None
        if on:
            p = resolve_within_roots(path, must_exist=True)
            if not p:
                return None
            return db_mylist_set(uid, str(p), name or p.name, True)
        p = resolve_within_roots(path, must_exist=False)
        return db_mylist_set(uid, str(p) if p else path, "", False)
    mp = _mylist_path()
    with _io_lock:
        data = load_json(mp, {})
        if on:
            p = resolve_within_roots(path, must_exist=True)
            if not p:
                return None
            data[str(p)] = {"name": name or p.name, "added": time.time()}
        else:
            p = resolve_within_roots(path, must_exist=False)
            data.pop(str(p) if p else path, None)
        save_json(mp, data)
    return list(data.keys())


# --------------------------------------------------------------------------- #
# Ratings (Netflix-style thumbs-up / thumbs-down, keyed by show folder or movie
# file path). Value is -1 (down), 0 (none), or +1 (up). Per-viewer, exactly like
# My List: SQLite per-user in accounts mode, the shared/profile JSON otherwise.
# --------------------------------------------------------------------------- #
def _rating_int(rec):
    """Coerce a stored rating record to an int in {-1, 0, 1}."""
    if isinstance(rec, dict):
        rec = rec.get("rating", 0)
    try:
        v = int(rec or 0)
    except (TypeError, ValueError):
        return 0
    return max(-1, min(1, v))


def load_ratings():
    """The active viewer's ratings as {key: {"rating", "updated"}}."""
    if rt.ACCOUNTS_ENABLED:
        uid = _current_uid()
        return db_ratings_all(uid) if uid else {}
    data = load_json(_ratings_path(), {})
    return data if isinstance(data, dict) else {}


def get_rating(key: str):
    """Current rating for one show/movie key (-1, 0 or 1)."""
    return _rating_int(load_ratings().get(key))


def set_rating(key: str, value):
    """Upsert one rating; a value of 0 clears it. -1/0/1 only."""
    value = _rating_int(value)
    if rt.ACCOUNTS_ENABLED:
        uid = _current_uid()
        if uid:
            db_set_rating(uid, key, value)
        return value
    rp = _ratings_path()
    with _io_lock:
        data = load_json(rp, {})
        if not isinstance(data, dict):
            data = {}
        if value == 0:
            data.pop(key, None)
        else:
            data[key] = {"rating": value, "updated": time.time()}
        save_json(rp, data)
    return value


# --------------------------------------------------------------------------- #
# Recommendation weight dials (per-viewer; an empty dict means "automatic"/defaults).
# Stored in the per-user prefs blob in accounts mode, else a profile JSON file —
# same per-viewer split as ratings/My List. The dial keys + clamping live in
# recommend.py; this layer just persists whatever clean dict it's handed.
# --------------------------------------------------------------------------- #
def reco_prefs_path_for(pid):
    if not rt.PROFILES_ENABLED or pid == "default":
        return RECO_PREFS_PATH
    return DATA_DIR / "profiles" / _profile_slug(pid) / "reco_prefs.json"


def _reco_prefs_path():
    return reco_prefs_path_for(current_profile())


def load_reco_weights():
    """The active viewer's saved recommendation dials, or {} when on automatic."""
    if rt.ACCOUNTS_ENABLED:
        uid = _current_uid()
        if not uid:
            return {}
        data = db_prefs_get(uid) or {}
        w = data.get(_RECO_PREFS_KEY)
        return w if isinstance(w, dict) else {}
    data = load_json(_reco_prefs_path(), {})
    return data if isinstance(data, dict) else {}


def save_reco_weights(weights: dict):
    """Persist the viewer's dials (a pre-cleaned dict). An empty dict clears the
    override, returning them to automatic."""
    weights = weights or {}
    if rt.ACCOUNTS_ENABLED:
        uid = _current_uid()
        if uid:
            data = db_prefs_get(uid) or {}
            if weights:
                data[_RECO_PREFS_KEY] = weights
            else:
                data.pop(_RECO_PREFS_KEY, None)
            db_prefs_set(uid, data)
        return weights
    with _io_lock:
        save_json(_reco_prefs_path(), weights)
    return weights


# --------------------------------------------------------------------------- #
# File operations (rename / move / mkdir / delete-to-trash)
# --------------------------------------------------------------------------- #
def _migrate_progress(old: Path, new: Path):
    """Preserve resume positions when a file or folder is renamed/moved: re-key
    every progress entry at (or under) `old` to the matching path under `new`, so
    renaming an episode (or a whole season folder) keeps your place and its
    Continue-watching card instead of orphaning it. In accounts mode this re-keys
    every user's resume + My List at once (file ops are library-wide)."""
    if rt.ACCOUNTS_ENABLED:
        db_migrate_path(old, new)
        return
    progress = load_progress()
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
        save_progress(moved)


