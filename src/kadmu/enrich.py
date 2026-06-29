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
from .const import DATA_DIR, CERT_MOVIE_LEVEL, CERT_TV_LEVEL, load_json, save_json

MATCH_PATH = DATA_DIR / "catalog_match.json"
CACHE_PATH = DATA_DIR / "tmdb_cache.json"
EPISODES_PATH = DATA_DIR / "tmdb_episodes.json"   # per-season episode metadata, fetched lazily

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


def load_episodes() -> dict:
    d = load_json(EPISODES_PATH, {})
    return d if isinstance(d, dict) else {}


# --------------------------------------------------------------------------- #
# Per-season episode metadata — fetched lazily the first time a show's season is
# opened on the detail page, then cached on disk (one TMDB round-trip per season).
# --------------------------------------------------------------------------- #
def _tv_id(card_id):
    """The TMDB tv id a catalog card is matched to, or None if it isn't a TV match."""
    key = match_key(load_match().get(card_id))
    if not isinstance(key, str) or not key.startswith("tv:"):
        return None
    try:
        return int(key.split(":", 1)[1])
    except (ValueError, IndexError):
        return None


def _compact_episode(ep):
    name = (ep.get("name") or "").strip()
    return {
        "episode": ep.get("episode_number"),
        "name": name,
        "overview": (ep.get("overview") or "").strip(),
        "still": tmdb.poster_url(ep.get("still_path"), "w185"),
        "air_date": ep.get("air_date") or "",
        "rating": round(float(ep.get("vote_average") or 0), 1) or None,
        "runtime": ep.get("runtime"),
    }


def season_episodes(card_id, season_number):
    """{'season': {...}, 'episodes': {epno: {...}}} of TMDB metadata for one season of a
    matched show. Cached on disk; fetched once per (show, season). {} when there's no
    TMDB match or the layer is off."""
    if not tmdb.enabled():
        return {}
    tv = _tv_id(card_id)
    if tv is None:
        return {}
    try:
        season_number = int(season_number)
    except (TypeError, ValueError):
        return {}
    ckey = f"tv:{tv}:s{season_number}"
    cache = load_episodes()
    hit = cache.get(ckey)
    if isinstance(hit, dict):
        return hit

    raw = tmdb.season(tv, season_number)
    if not isinstance(raw, dict):
        return {}
    episodes = {}
    for ep in (raw.get("episodes") or []):
        n = ep.get("episode_number")
        if n is not None:
            episodes[str(n)] = _compact_episode(ep)
    out = {
        "season": {
            "name": (raw.get("name") or "").strip(),
            "overview": (raw.get("overview") or "").strip(),
            "poster": tmdb.poster_url(raw.get("poster_path"), "w342"),
            "air_date": raw.get("air_date") or "",
        },
        "episodes": episodes,
    }
    with _write_lock:
        cache = load_episodes()
        cache[ckey] = out
        save_json(EPISODES_PATH, cache)
    return out


# --------------------------------------------------------------------------- #
# External title search — TMDB movies/shows you DON'T own, for the search bar.
# Cached in memory (TTL) so type-ahead doesn't hammer the API. [] when TMDB off.
# --------------------------------------------------------------------------- #
_ext_search = {}                          # norm_query -> (ts, [items])
_ext_search_lock = threading.Lock()
_EXT_SEARCH_TTL = 1800.0


def _owned_keys():
    out = set()
    for rec in load_match().values():
        k = match_key(rec)
        if k and k != "none":
            out.add(k)
    return out


def owned_genres(limit=6):
    """The most common genres across the library's TMDB-matched titles, most-first.
    Tilts the discover rails toward what the collection already leans into, so the
    suggestions sharpen as the library grows. [] when nothing's matched / TMDB off."""
    if not tmdb.enabled():
        return []
    cache = load_cache()
    tally = {}
    for rec in load_match().values():
        k = match_key(rec)
        if k in (None, "none"):
            continue
        d = cache.get(k)
        if isinstance(d, dict):
            for g in (d.get("genres") or []):
                if g:
                    tally[g] = tally.get(g, 0) + 1
    return [g for g, _ in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def search_external(query, limit=12):
    """TMDB titles matching `query` that aren't in the library — for the search bar's
    'not in your library' section. Cached; returns [] when the metadata layer is off."""
    if not tmdb.enabled():
        return []
    q = (query or "").strip()
    if len(q) < 2:
        return []
    nq = q.lower()
    now = time.time()
    with _ext_search_lock:
        hit = _ext_search.get(nq)
        if hit and now - hit[0] < _EXT_SEARCH_TTL:
            return hit[1][:limit]
    owned = _owned_keys()
    out, seen = [], set()
    for item in tmdb.search_multi(q):
        mt = item.get("media_type")
        if mt not in ("movie", "tv"):
            continue
        tid = item.get("id")
        if tid is None:
            continue
        key = "%s:%s" % (mt, tid)
        if key in owned or key in seen:
            continue
        title = item.get("title") or item.get("name") or ""
        if not title:
            continue
        seen.add(key)
        dt = item.get("release_date") or item.get("first_air_date") or ""
        year = int(dt[:4]) if dt[:4].isdigit() else None
        out.append({
            "external": True, "id": key, "tmdb_id": tid,
            "kind": "show" if mt == "tv" else "movie", "tmdbKind": mt,
            "name": title, "year": year,
            "poster": tmdb.poster_url(item.get("poster_path")),
            "overview": (item.get("overview") or "").strip(),
            "vote": round(float(item.get("vote_average") or 0), 1),
            "popularity": float(item.get("popularity") or 0),
            "tmdbUrl": "https://www.themoviedb.org/%s/%s" % (mt, tid),
        })
    out.sort(key=lambda x: x["popularity"], reverse=True)
    with _ext_search_lock:
        if len(_ext_search) > 300:
            _ext_search.clear()
        _ext_search[nq] = (now, out)
    return out[:limit]


# --------------------------------------------------------------------------- #
# Discovery catalog — popular / trending / by-genre titles you DON'T own, for the
# empty-library home and the taste-seeded "more to watch" rails. Built from TMDB's
# discover/trending endpoints, excludes what you already have, cached in memory
# (the genre selection rarely changes; a big page of rows is one TTL window).
# --------------------------------------------------------------------------- #
_discover_cache = {}                       # genre-key -> (ts, payload)
_discover_lock = threading.Lock()
_DISCOVER_TTL = 1800.0
_DISCOVER_ROW = 18                         # titles per rail


def _disc_stub(item, kind, gmaps, owned, seen):
    """One external-suggestion stub from a TMDB discover/trending item, or None when
    it's a person / already owned / a dupe / unusable. `kind` is forced for /discover
    results (which carry no media_type); trending items carry their own."""
    mt = kind or item.get("media_type")
    if mt not in ("movie", "tv"):
        return None
    tid = item.get("id")
    if tid is None:
        return None
    key = "%s:%s" % (mt, tid)
    if key in owned or key in seen:
        return None
    title = item.get("title") or item.get("name") or ""
    if not title:
        return None
    seen.add(key)
    dt = item.get("release_date") or item.get("first_air_date") or ""
    year = int(dt[:4]) if dt[:4].isdigit() else None
    gmap = gmaps.get(mt) or {}
    genres = [gmap.get(int(g)) for g in (item.get("genre_ids") or [])
              if isinstance(g, int) and gmap.get(int(g))]
    return {
        "external": True, "id": key, "tmdb_id": tid,
        "kind": "show" if mt == "tv" else "movie", "tmdbKind": mt,
        "name": title, "year": year, "genres": genres,
        "poster": tmdb.poster_url(item.get("poster_path")),
        "backdrop": tmdb.poster_url(item.get("backdrop_path"), "w780"),
        "overview": (item.get("overview") or "").strip(),
        "vote": round(float(item.get("vote_average") or 0), 1),
        "popularity": float(item.get("popularity") or 0),
        "tmdbUrl": "https://www.themoviedb.org/%s/%s" % (mt, tid),
    }


def discover_catalog(genre_names=None, limit_per_row=_DISCOVER_ROW):
    """Rows of TMDB titles you don't own — a streaming-style discover homepage for a
    library that's empty (or just for "what should I get next"). When `genre_names`
    is given (the viewer's picks), it leads with a rail per genre; otherwise it shows
    trending + popular. Cached in memory (TTL); {} -> off when there's no TMDB key."""
    if not tmdb.enabled():
        return {"enabled": False, "rows": [], "genres": []}
    names = [str(g) for g in (genre_names or []) if str(g).strip()][:6]
    ckey = "|".join(sorted(n.lower() for n in names)) or "_default"
    now = time.time()
    with _discover_lock:
        hit = _discover_cache.get(ckey)
        if hit and now - hit[0] < _DISCOVER_TTL:
            return hit[1]

    owned = _owned_keys()
    gmaps = {"movie": tmdb.genre_map("movie"), "tv": tmdb.genre_map("tv")}
    seen = set()
    rows = []

    def add_row(title, raw, kind=None):
        items = []
        for it in (raw or []):
            stub = _disc_stub(it, kind, gmaps, owned, seen)
            if stub:
                items.append(stub)
            if len(items) >= limit_per_row:
                break
        if items:
            rows.append({"title": title, "items": items})

    # Lead with what's hot, then the viewer's tastes (or broad popularity), then a
    # quality shelf. Each call is paced + best-effort; a failure just drops its row.
    try:
        add_row("Trending this week", tmdb.trending("week"))
    except Exception:
        pass
    if names:
        index = {g["name"].lower(): g for g in tmdb.genres_combined()}
        for name in names:
            g = index.get(name.lower())
            if not g:
                continue
            raw = []
            try:
                if g.get("movie"):
                    raw += [dict(x, media_type="movie") for x in tmdb.discover("movie", g["movie"])]
                if g.get("tv"):
                    raw += [dict(x, media_type="tv") for x in tmdb.discover("tv", g["tv"])]
            except Exception:
                raw = []
            raw.sort(key=lambda x: float(x.get("popularity") or 0), reverse=True)
            add_row("%s you might like" % name, raw)
    else:
        try:
            add_row("Popular movies", tmdb.discover("movie"), kind="movie")
            add_row("Popular shows", tmdb.discover("tv"), kind="tv")
        except Exception:
            pass
    try:
        add_row("Critically acclaimed",
                tmdb.discover("movie", sort_by="vote_average.desc", min_votes=800), kind="movie")
    except Exception:
        pass

    payload = {"enabled": True, "rows": rows, "genres": names}
    with _discover_lock:
        if len(_discover_cache) > 40:
            _discover_cache.clear()
        _discover_cache[ckey] = (now, payload)
    return payload


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


def _us_cert(kind, raw):
    """(certification_string, maturity_level) from TMDB's US content rating, or
    ('', None) when unknown. Movies carry it under release_dates, TV under
    content_ratings."""
    if kind == "movie":
        for entry in ((raw.get("release_dates") or {}).get("results") or []):
            if (entry.get("iso_3166_1") or "").upper() != "US":
                continue
            for rd in entry.get("release_dates") or []:
                cert = (rd.get("certification") or "").strip().upper()
                if cert:
                    return cert, CERT_MOVIE_LEVEL.get(cert)
        return "", None
    for entry in ((raw.get("content_ratings") or {}).get("results") or []):
        if (entry.get("iso_3166_1") or "").upper() != "US":
            continue
        cert = (entry.get("rating") or "").strip().upper()
        if cert:
            return cert, CERT_TV_LEVEL.get(cert)
    return "", None


# Bump when _compact() gains a field worth backfilling onto already-matched titles;
# enrich_once re-fetches any cached detail whose `_schema` is older (see _stale).
_SCHEMA = 3


def _logo(raw):
    """Best title-logo path from TMDB images — the styled wordmark streaming UIs show
    in place of plain text — preferring English, then language-neutral, highest-voted.
    '' when there's none."""
    logos = ((raw.get("images") or {}).get("logos")) or []
    if not logos:
        return ""

    def rank(l):
        lang = l.get("iso_639_1") or ""
        return (0 if lang == "en" else 1 if lang == "" else 2,
                -float(l.get("vote_average") or 0))

    return (sorted(logos, key=rank)[0].get("file_path")) or ""


def _trailer(raw):
    """The best YouTube trailer *key* from TMDB's videos, or '' — preferring an
    official 'Trailer', then any trailer, then a teaser. YouTube only: it's the one
    site we can deep-link to (we open it in a new tab — never an embed, so the strict
    CSP and the no-phone-home default are both untouched)."""
    vids = ((raw.get("videos") or {}).get("results")) or []
    yt = [v for v in vids if (v.get("site") or "").lower() == "youtube" and v.get("key")]
    if not yt:
        return ""

    def rank(v):
        t = (v.get("type") or "").lower()
        kind_score = 0 if t == "trailer" else 1 if t == "teaser" else 2
        return (kind_score, 0 if v.get("official") else 1)

    yt.sort(key=rank)
    return yt[0]["key"]


def _collection(raw):
    """{id, name} for the franchise a movie belongs to, or None. Comes free in the
    base movie detail (belongs_to_collection) — no extra API round-trip."""
    bc = raw.get("belongs_to_collection")
    if isinstance(bc, dict) and bc.get("id"):
        return {"id": int(bc["id"]), "name": bc.get("name") or ""}
    return None


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

    cert, maturity = _us_cert(kind, raw)

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
        "cert": cert, "maturity": maturity,    # parental controls
        "trailer": _trailer(raw),              # YouTube key (deep-link, no embed)
        "collection": _collection(raw),        # franchise grouping (movies)
        "logo": _logo(raw),                    # styled title wordmark (hero / title page)
        "recs": recs,
        "_schema": _SCHEMA,
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
        # Schema-upgrade backfill: matched titles whose cached detail predates the current
        # `_schema` (i.e. is missing fields we now store — trailer, collection, logo, …).
        # We re-fetch their detail by the known tmdb id — no re-search — so new metadata
        # fills in automatically over the next few enrich cycles, with no full re-match.
        def _stale(c):
            k = match_key(match.get(c["id"]))
            if k in (None, "none"):
                return False
            d = cache.get(k)
            return isinstance(d, dict) and d.get("_schema") != _SCHEMA
        stale = [c for c in cards if _stale(c)]
        remaining = len(todo)
        _busy[0] = True
        processed = matched = refreshed = 0
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
            # Spend any leftover budget refreshing stale-schema details (re-fetch by id).
            for card in stale[:max(0, limit - processed)]:
                rec = match.get(card["id"]) or {}
                kind, tid, key = rec.get("kind"), rec.get("tmdb_id"), match_key(rec)
                if kind not in ("movie", "tv") or tid is None or not key:
                    continue
                raw = tmdb.details(kind, int(tid))
                if isinstance(raw, dict) and raw.get("id") is not None:
                    cache[key] = _compact(kind, int(tid), raw)
                    refreshed += 1
            if processed or refreshed:
                save_json(MATCH_PATH, match)
                save_json(CACHE_PATH, cache)
        finally:
            _busy[0] = False
            _last_run[0] = now
    return {"enabled": True, "ready": True, "processed": processed,
            "matched": matched, "refreshed": refreshed,
            "remaining": max(0, remaining - processed)}


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
                elif r.get("remaining", 0) > 0 or r.get("processed", 0) > 0 or r.get("refreshed", 0) > 0:
                    wait = 1.5                          # more to match / backfill; come back fast
        except Exception:
            pass
        _event.wait(timeout=wait)
        _event.clear()


def start_enricher():
    # Re-check for newly-added titles whenever the library is re-indexed.
    library.add_post_index_hook(request_enrich)
    threading.Thread(target=_enrich_loop, name="tmdb-enricher", daemon=True).start()
