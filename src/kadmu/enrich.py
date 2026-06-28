"""TMDB enrichment — match every show/movie in the library to a TMDB title and cache
the metadata the recommender feeds on (genres, keywords, cast/crew, ratings) plus
TMDB's own recommendations/similar graph (used to suggest titles you *don't* own).

Two on-disk caches under data/ (atomic JSON, single background writer):

  • ``catalog_match.json`` — {card_id: {"key": "movie:603", "tmdb_id", "kind",
    "confidence", "title", "year", "ts"}}. A confidently-unmatched card is recorded
    as {"key": "none", ...} so we don't re-query it every cycle. FeatureSource reads
    the ``key`` to find the detail.
  • ``tmdb_cache.json`` — {"movie:603": {detail…}} where detail carries the feature
    fields above and a compact ``recs`` list of suggestion stubs.

A daemon thread enriches incrementally in small batches (so a big first run never
blocks anything and stays polite to the API), re-walks periodically for new titles,
and rebuilds on demand. Everything degrades to a no-op without a key.

Stdlib only. Depends on tmdb (network) + catalog (the title list) + const (paths/IO);
nothing imports this except recommend/handler/app.
"""
from __future__ import annotations
import difflib
import os
import re
import threading
import time

from . import tmdb
from . import library
from .catalog import build_catalog
from .const import DATA_DIR, load_json, save_json

MATCH_PATH = DATA_DIR / "catalog_match.json"
CACHE_PATH = DATA_DIR / "tmdb_cache.json"

try:
    ENRICH_REFRESH = max(300, int(os.environ.get("KADMU_TMDB_REFRESH_SEC", "21600")))
except ValueError:
    ENRICH_REFRESH = 21600          # re-scan for newly-added titles every ~6h
try:
    BATCH = max(1, int(os.environ.get("KADMU_TMDB_BATCH", "40")))
except ValueError:
    BATCH = 40                      # titles matched per lock-held batch

_MIN_SIM = 0.5                      # below this we record "no confident match"
_KW_CAP, _CAST_CAP, _CREW_CAP, _RECS_CAP = 15, 8, 3, 24
_YEAR_SUFFIX = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")
_LEADING_EP = re.compile(r"(?i)^s\d+\s*e\d+\s*[·:\-]\s*")
_NONWORD = re.compile(r"[^a-z0-9]+")

_write_lock = threading.Lock()      # serialise read-modify-write of the caches
_event = threading.Event()
_force = [False]
_busy = [False]
_last_run = [0.0]

# poster_url is re-exported so callers (recommend/handler) hit one import.
poster_url = tmdb.poster_url
enabled = tmdb.enabled


# --------------------------------------------------------------------------- #
# Cache IO (writes serialised by the worker; reads are lock-free atomic loads)
# --------------------------------------------------------------------------- #
def load_match() -> dict:
    d = load_json(MATCH_PATH, {})
    return d if isinstance(d, dict) else {}


def load_cache() -> dict:
    d = load_json(CACHE_PATH, {})
    return d if isinstance(d, dict) else {}


def match_key(rec):
    """Pull the tmdb cache key out of a match record (tolerates the legacy int form)."""
    if isinstance(rec, dict):
        return rec.get("key")
    if rec in (None, "none"):
        return rec
    return str(rec)


# --------------------------------------------------------------------------- #
# Title → query
# --------------------------------------------------------------------------- #
def _query(card):
    """A clean search title + a year hint from a catalog card."""
    name = _LEADING_EP.sub("", (card.get("name") or "").strip())
    year = card.get("year")
    m = _YEAR_SUFFIX.search(name)
    if m:
        if not year:
            ys = re.search(r"\d{4}", m.group(0))
            year = int(ys.group(0)) if ys else None
        name = name[:m.start()].strip()
    return name, year


def _norm(s: str) -> str:
    return _NONWORD.sub(" ", (s or "").lower()).strip()


def _cand_year(cand):
    d = cand.get("release_date") or cand.get("first_air_date") or ""
    return int(d[:4]) if d[:4].isdigit() else None


def _score(nquery, year, cand, kind):
    """(title_similarity, overall_score) for one search candidate."""
    title = cand.get("title") or cand.get("name") or ""
    orig = cand.get("original_title") or cand.get("original_name") or ""
    sim = max(difflib.SequenceMatcher(None, nquery, _norm(title)).ratio(),
              difflib.SequenceMatcher(None, nquery, _norm(orig)).ratio() if orig else 0.0)
    cy = _cand_year(cand)
    if year and cy:
        diff = abs(year - cy)
        yscore = 1.0 if diff == 0 else (0.7 if diff == 1 else (0.3 if diff <= 2 else 0.0))
    else:
        yscore = 0.5
    pop = min(1.0, (cand.get("popularity") or 0.0) / 50.0)
    return sim, 0.78 * sim + 0.20 * yscore + 0.02 * pop


# --------------------------------------------------------------------------- #
# Detail shaping (raw TMDB → the lean record the recommender reads)
# --------------------------------------------------------------------------- #
def _names(items, key="name", cap=None, where=None):
    out = []
    for it in (items or []):
        if where and not where(it):
            continue
        v = (it or {}).get(key)
        if v:
            out.append(v)
        if cap and len(out) >= cap:
            break
    return out


def _stub(kind, item, gmap):
    tid = item.get("id")
    if tid is None:
        return None
    genres = [gmap.get(int(g)) for g in (item.get("genre_ids") or [])
              if isinstance(g, int) and gmap.get(int(g))]
    ov = (item.get("overview") or "").strip()
    return {
        "key": f"{kind}:{tid}", "kind": kind, "tmdb_id": tid,
        "title": item.get("title") or item.get("name") or "",
        "year": _cand_year(item),
        "genres": genres,
        "poster_path": item.get("poster_path") or "",
        "vote_average": item.get("vote_average") or 0,
        "popularity": item.get("popularity") or 0,
        "overview": ov[:300],
    }


def _compact(kind, tid, raw):
    """The stored detail: feature fields for the recommender + suggestion stubs."""
    title = raw.get("title") or raw.get("name") or ""
    year = None
    d = raw.get("release_date") or raw.get("first_air_date") or ""
    if d[:4].isdigit():
        year = int(d[:4])
    genres = _names(raw.get("genres"))
    kw_root = raw.get("keywords") or {}
    keywords = _names(kw_root.get("keywords") or kw_root.get("results"), cap=_KW_CAP)
    credits = raw.get("credits") or {}
    cast = _names(credits.get("cast"), cap=_CAST_CAP)
    if kind == "movie":
        directors = _names(credits.get("crew"), cap=_CREW_CAP,
                           where=lambda c: c.get("job") == "Director")
    else:
        directors = _names(raw.get("created_by"), cap=_CREW_CAP)
    runtime = raw.get("runtime")
    if not runtime:
        ert = raw.get("episode_run_time") or []
        runtime = ert[0] if ert else None

    gmap = tmdb.genre_map(kind)
    seen, recs = set(), []
    for bucket in ("recommendations", "similar"):
        for item in ((raw.get(bucket) or {}).get("results") or []):
            tid2 = item.get("id")
            if tid2 is None or tid2 in seen or tid2 == tid:
                continue
            stub = _stub(kind, item, gmap)
            if stub:
                seen.add(tid2)
                recs.append(stub)
            if len(recs) >= _RECS_CAP:
                break
        if len(recs) >= _RECS_CAP:
            break

    return {
        "tmdb_id": tid, "kind": kind, "title": title, "year": year,
        "genres": genres, "keywords": keywords, "cast": cast, "directors": directors,
        "original_language": raw.get("original_language") or "",
        "vote_average": raw.get("vote_average") or 0,
        "vote_count": raw.get("vote_count") or 0,
        "popularity": raw.get("popularity") or 0,
        "overview": (raw.get("overview") or "").strip(),
        "poster_path": raw.get("poster_path") or "",
        "backdrop_path": raw.get("backdrop_path") or "",
        "runtime": runtime,
        "recs": recs,
    }


def _match_one(card):
    """Search + fetch detail for one card. Returns (key, tmdb_id, kind, detail,
    confidence) or None if there's no confident match."""
    query, year = _query(card)
    if not query:
        return None
    kind = "tv" if card.get("kind") == "show" else "movie"
    results = tmdb.search(kind, query, year)
    if not results and year:
        results = tmdb.search(kind, query)         # retry without the year hint
    nq = _norm(query)
    best, best_sim, best_sc = None, 0.0, -1.0
    for cand in results[:8]:
        sim, sc = _score(nq, year, cand, kind)
        if sc > best_sc:
            best, best_sim, best_sc = cand, sim, sc
    if best is None or best_sim < _MIN_SIM:
        return None
    tid = best.get("id")
    if tid is None:
        return None
    raw = tmdb.details(kind, tid)
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    return f"{kind}:{tid}", tid, kind, _compact(kind, tid, raw), round(best_sim, 3)


# --------------------------------------------------------------------------- #
# Enrichment driver
# --------------------------------------------------------------------------- #
def _catalog_cards():
    cat = build_catalog()
    if not cat.get("ready"):
        return None
    return list(cat.get("shows", [])) + list(cat.get("movies", []))


def enrich_once(force=False, limit=BATCH):
    """Match up to `limit` not-yet-matched cards. Returns a small status dict.
    `force` is handled by the loop (it wipes the match map first), so callers here
    just process whatever is still unmatched."""
    if not tmdb.enabled():
        return {"enabled": False, "ready": False, "processed": 0, "remaining": 0}
    cards = _catalog_cards()
    if cards is None:
        return {"enabled": True, "ready": False, "processed": 0, "remaining": 0}

    with _write_lock:
        match = load_match()
        cache = load_cache()
        todo = [c for c in cards if c["id"] not in match]
        remaining = len(todo)
        _busy[0] = True
        processed = matched = 0
        now = time.time()
        try:
            for card in todo[:limit]:
                res = _match_one(card)
                processed += 1
                if res is None:
                    match[card["id"]] = {"key": "none", "ts": now}
                    continue
                key, tid, kind, detail, conf = res
                match[card["id"]] = {"key": key, "tmdb_id": tid, "kind": kind,
                                     "confidence": conf, "title": detail.get("title"),
                                     "year": detail.get("year"), "ts": now}
                cache[key] = detail
                matched += 1
            if processed:
                save_json(MATCH_PATH, match)
                save_json(CACHE_PATH, cache)
        finally:
            _busy[0] = False
            _last_run[0] = now
    return {"enabled": True, "ready": True, "processed": processed,
            "matched": matched, "remaining": max(0, remaining - processed)}


def set_manual_match(card_id, kind, tmdb_id):
    """Owner override: pin a card to a specific TMDB id (the search got it wrong)."""
    if kind not in ("movie", "tv") or not tmdb.enabled():
        return None
    try:
        tid = int(tmdb_id)
    except (TypeError, ValueError):
        return None
    raw = tmdb.details(kind, tid)
    if not isinstance(raw, dict) or raw.get("id") is None:
        return None
    detail = _compact(kind, tid, raw)
    key = f"{kind}:{tid}"
    with _write_lock:
        match = load_match()
        cache = load_cache()
        match[card_id] = {"key": key, "tmdb_id": tid, "kind": kind, "confidence": 1.0,
                          "title": detail.get("title"), "year": detail.get("year"),
                          "ts": time.time(), "manual": True}
        cache[key] = detail
        save_json(MATCH_PATH, match)
        save_json(CACHE_PATH, cache)
    return {"key": key, "title": detail.get("title"), "year": detail.get("year")}


def enrich_status():
    """Counts for the UI: how much of the library is matched to TMDB."""
    cards = _catalog_cards()
    match = load_match()
    if cards is None:
        return {"enabled": tmdb.enabled(), "ready": False, "total": 0, "matched": 0,
                "unmatched": 0, "pending": 0, "building": _busy[0]}
    ids = [c["id"] for c in cards]
    matched = sum(1 for cid in ids if match_key(match.get(cid)) not in (None, "none"))
    tried = sum(1 for cid in ids if cid in match)
    return {
        "enabled": tmdb.enabled(), "ready": True, "total": len(ids),
        "matched": matched, "unmatched": len(ids) - matched,
        "pending": len(ids) - tried, "building": _busy[0],
        "lastRun": _last_run[0],
    }


# --------------------------------------------------------------------------- #
# Background worker
# --------------------------------------------------------------------------- #
def request_enrich(force=False):
    """Wake the worker. force=True re-matches the whole library from scratch."""
    if force:
        _force[0] = True
    _event.set()


def _take_force():
    if _force[0]:
        _force[0] = False
        return True
    return False


def _enrich_loop():
    while True:
        wait = ENRICH_REFRESH
        try:
            if tmdb.enabled():
                if _take_force():
                    with _write_lock:
                        save_json(MATCH_PATH, {})      # wipe → everything re-matches
                r = enrich_once(limit=BATCH)
                if not r.get("ready"):
                    wait = 5.0                          # catalog not built yet; retry soon
                elif r.get("remaining", 0) > 0 or r.get("processed", 0) > 0:
                    wait = 1.5                          # more to chew through; come back fast
        except Exception:
            pass
        _event.wait(timeout=wait)
        _event.clear()


def start_enricher():
    # Re-check for newly-added titles whenever the library is re-indexed.
    library.add_post_index_hook(request_enrich)
    threading.Thread(target=_enrich_loop, name="tmdb-enricher", daemon=True).start()
