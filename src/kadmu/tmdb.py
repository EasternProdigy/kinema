"""TMDB API client — the (optional) metadata layer behind the recommender.

The recommender works with no network at all (local features + your ratings/watch
history). When a TMDB API key is configured it gets *much* sharper: real genres,
keywords, cast/crew, ratings, and TMDB's own "recommendations"/"similar" graph —
the last of which is what lets Kadmu suggest titles you don't own yet.

Stdlib only (urllib + json + ssl). No third-party SDK. Every call is best-effort:
on any network error / missing key it returns None and the caller degrades. Posters
are proxied + disk-cached through here so the browser never talks to TMDB directly
(keeps the strict same-origin CSP and leaks nothing client-side).

Sits at the bottom of the metadata stack: enrich.py drives it; nothing here imports
another kadmu module except const (paths + atomic IO).
"""
from __future__ import annotations
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .const import STATE_DIR

API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/"
IMAGE_DIR = STATE_DIR / "cache" / "tmdb"          # disk cache for proxied posters
POSTER_SIZES = {"w92", "w154", "w185", "w342", "w500", "w780", "original"}
_PATH_RE = re.compile(r"^/[\w./-]+\.(?:jpg|jpeg|png|webp)$", re.IGNORECASE)
_USER_AGENT = "Kadmu/1.0 (+https://kadmu.app)"
_TIMEOUT = 15

# A key set from config.json at startup (env always wins; see api_key()).
_configured_key: str | None = None
_key_lock = threading.Lock()
_ssl_ctx = ssl.create_default_context()

# Be a polite client: serialise network calls and keep a small floor between them,
# so a big first-run enrichment can't burst past TMDB's rate window. (Enrichment
# already runs on a single background thread; this is belt-and-suspenders.)
_net_lock = threading.Lock()
_last_call = [0.0]
_MIN_INTERVAL = 0.06        # ~16 req/s ceiling, well under TMDB's ~50/s

_genre_cache: dict[str, dict] = {}
_genre_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Key resolution
# --------------------------------------------------------------------------- #
def set_key(key: str | None):
    """Register the key persisted in config.json. Env (KADMU_TMDB_KEY) still wins."""
    global _configured_key
    with _key_lock:
        _configured_key = (key or "").strip() or None


def api_key() -> str:
    env = os.environ.get("KADMU_TMDB_KEY", "").strip()
    if env:
        return env
    with _key_lock:
        return _configured_key or ""


def enabled() -> bool:
    return bool(api_key())


def _is_bearer(key: str) -> bool:
    # v4 read access tokens are long JWTs (header.payload.signature); v3 keys are
    # 32-char hex. Detect so the same field accepts either.
    return key.count(".") == 2 and len(key) > 100


# --------------------------------------------------------------------------- #
# Low-level GET (best-effort, bounded retries, polite pacing)
# --------------------------------------------------------------------------- #
def _get(path: str, params: dict | None = None):
    key = api_key()
    if not key:
        return None
    params = dict(params or {})
    headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    if _is_bearer(key):
        headers["Authorization"] = "Bearer " + key
    else:
        params["api_key"] = key
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)

    for attempt in range(3):
        with _net_lock:
            gap = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
            if gap > 0:
                time.sleep(gap)
            _last_call[0] = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_ctx) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:                 # rate limited: back off
                try:
                    wait = min(10.0, float(e.headers.get("Retry-After") or 2))
                except (TypeError, ValueError):
                    wait = 2.0
                time.sleep(max(0.5, wait))
                continue
            return None                                       # 401/404/etc → give up
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError,
                ValueError):
            return None
    return None


# --------------------------------------------------------------------------- #
# Search + details
# --------------------------------------------------------------------------- #
def search(kind: str, query: str, year=None):
    """Best matches for a title. kind is 'movie' or 'tv'. Returns a results list."""
    if not query:
        return []
    params = {"query": query, "include_adult": "false", "language": "en-US"}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = str(year)
    data = _get(f"/search/{kind}", params)
    if not isinstance(data, dict):
        return []
    res = data.get("results")
    return res if isinstance(res, list) else []


def details(kind: str, tmdb_id: int):
    """Full detail for a movie/tv id, with keywords, credits, recommendations and
    similar folded in (one round-trip). Returns the raw TMDB dict, or None."""
    return _get(f"/{kind}/{int(tmdb_id)}",
                {"append_to_response": "keywords,credits,recommendations,similar",
                 "language": "en-US"})


def genre_map(kind: str) -> dict:
    """{genre_id: name} for movie or tv, fetched once and cached in memory."""
    with _genre_lock:
        if kind in _genre_cache:
            return _genre_cache[kind]
    data = _get(f"/genre/{kind}/list", {"language": "en-US"})
    out = {}
    if isinstance(data, dict):
        for g in data.get("genres") or []:
            if isinstance(g, dict) and g.get("id") is not None:
                out[int(g["id"])] = g.get("name") or ""
    with _genre_lock:
        # Only cache a non-empty map, so a transient failure doesn't pin {}.
        if out:
            _genre_cache[kind] = out
    return out


# --------------------------------------------------------------------------- #
# Poster proxy (server-side fetch + disk cache; keeps the browser same-origin)
# --------------------------------------------------------------------------- #
def poster_url(poster_path: str | None, size: str = "w342") -> str:
    """The same-origin URL the frontend should use for a TMDB poster path."""
    if not poster_path:
        return ""
    return f"/api/tmdb/img?path={urllib.parse.quote(poster_path)}&size={size}"


def fetch_image(poster_path: str, size: str = "w342"):
    """Bytes for a TMDB image, served from the on-disk cache or fetched once.
    Returns (data, content_type) or None. Validates path + size (no SSRF)."""
    if size not in POSTER_SIZES or not poster_path or not _PATH_RE.match(poster_path):
        return None
    ext = Path(poster_path).suffix.lower() or ".jpg"
    ctype = {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    cache = IMAGE_DIR / size / (poster_path.lstrip("/").replace("/", "_"))
    try:
        if cache.is_file() and cache.stat().st_size > 0:
            return cache.read_bytes(), ctype
    except OSError:
        pass
    req = urllib.request.Request(IMAGE_BASE + size + poster_path,
                                 headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_ctx) as resp:
            data = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            ConnectionError, OSError):
        return None
    if not data:
        return None
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(cache.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, cache)
    except OSError:
        pass
    return data, ctype
