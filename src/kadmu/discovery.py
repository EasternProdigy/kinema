"""Discovery polish — the Netflix-feel browse layer over the catalog: per-title
facets (genre / year / rating / popularity / runtime) so the front-end can offer
**browse-by-genre + filters + a Top-10**, and a per-viewer **watch history** (the
titles you've actually finished, newest first).

All derived from data Kadmu already holds — the TMDB enrichment caches and the resume
table — so there's **no new outbound call and no new cost**. Stdlib only. Sits above
enrich/catalog/store, below handler (nothing here imports handler)."""
from __future__ import annotations
from pathlib import Path

from . import enrich, rt, tmdb
from .accounts import _current_uid, get_user
from .catalog import parse_episode, series_dir_for
from .library import clean_title
from .store import (
    load_progress, resolve_within_roots, active_profile_ceiling,
    owning_root, viewer_root_scope, is_combined_subprofile,
)
from .const import WATCHED_FRAC, VIDEO_EXTS, MATURITY_MAX


# --------------------------------------------------------------------------- #
# Facets — TMDB-derived attributes overlaid on each catalog card
# --------------------------------------------------------------------------- #
def _facet_lookup():
    """A cid -> facets function backed by one load of the enrichment caches."""
    match = enrich.load_match()
    cache = enrich.load_cache()

    def facets(cid):
        key = enrich.match_key(match.get(cid))
        d = cache.get(key) if key not in (None, "none") else None
        if not isinstance(d, dict):
            return {}
        vote = d.get("vote_average") or 0
        return {
            "genres": d.get("genres") or [],
            "year": d.get("year"),
            "rating": round(vote, 1) if vote else None,
            "popularity": d.get("popularity") or 0,
            "runtime": d.get("runtime"),
            # Real cover art so owned titles look like a streaming service (portrait
            # poster + cinematic backdrop), plus a synopsis + maturity for the hero.
            "poster": tmdb.poster_url(d.get("poster_path"), "w342"),
            "backdrop": tmdb.poster_url(d.get("backdrop_path"), "w780"),
            "logo": tmdb.poster_url(d.get("logo"), "w500"),   # styled wordmark for the hero
            "overview": d.get("overview") or "",
            "maturity": d.get("cert") or "",
        }
    return facets


def attach_facets(cat):
    """Overlay genre/year/rating/popularity/runtime onto every show & movie in a
    build_catalog() payload (in place). A no-op (harmless) when TMDB is off — the
    cards just carry empty genres, and the front-end falls back to what it has."""
    if not isinstance(cat, dict) or not cat.get("ready"):
        return cat
    facets = _facet_lookup()
    for it in list(cat.get("shows", [])) + list(cat.get("movies", [])):
        fc = facets(it.get("id"))
        if not fc:
            it.setdefault("genres", [])
            continue
        for k, v in fc.items():
            if k == "year" and it.get("year"):   # keep a year parsed from the filename
                continue
            it[k] = v
    return cat


def attach_title_detail(detail):
    """Overlay the full TMDB record (synopsis, genres, cast, creators, rating, cover
    art, maturity, runtime) onto a title_detail() payload, in place. A no-op when the
    title has no match / the layer is off — the page just shows what it parsed locally."""
    if not isinstance(detail, dict):
        return detail
    match = enrich.load_match()
    cache = enrich.load_cache()
    key = enrich.match_key(match.get(detail.get("id")))
    d = cache.get(key) if key not in (None, "none") else None
    if not isinstance(d, dict):
        return detail
    vote = d.get("vote_average") or 0
    overlay = {
        "tmdb": True,
        "overview": d.get("overview") or "",
        "genres": d.get("genres") or [],
        "cast": (d.get("cast") or [])[:8],
        "creators": (d.get("directors") or [])[:3],
        "rating": round(vote, 1) if vote else None,
        "votes": d.get("vote_count") or 0,
        "poster": enrich.poster_url(d.get("poster_path")),
        "backdrop": tmdb.poster_url(d.get("backdrop_path"), "w780"),
        "logo": tmdb.poster_url(d.get("logo"), "w500"),   # styled title wordmark
        "maturity": d.get("cert") or "",
        "runtime": d.get("runtime"),
        "trailer": ("https://www.youtube.com/watch?v=%s" % d["trailer"]) if d.get("trailer") else "",
        "tmdbUrl": "https://www.themoviedb.org/%s/%s" % (d.get("kind"), d.get("tmdb_id"))
                   if d.get("tmdb_id") else "",
    }
    if not detail.get("year") and d.get("year"):
        overlay["year"] = d.get("year")
    detail.update(overlay)
    # Franchise rail: other OWNED titles in the same TMDB collection. No extra API call —
    # belongs_to_collection rides along in each movie's cached detail. Parental-gated.
    coll = d.get("collection")
    if isinstance(coll, dict) and coll.get("id"):
        members = _collection_members(coll["id"], match, cache, exclude=detail.get("id"))
        if members:
            detail["collection"] = {"name": coll.get("name") or "", "items": members}
    return detail


def _collection_members(cid, match, cache, exclude=None, cap=24):
    """Owned catalog cards that share TMDB collection `cid`, oldest-first, respecting
    the active viewer's parental/scope gate. `match`/`cache` are passed in so the
    caller's single load is reused."""
    gate = play_gate()                          # built once: parental controls + library scope
    items = []
    for card_id, rec in match.items():
        if exclude is not None and card_id == exclude:
            continue
        k = enrich.match_key(rec)
        if k in (None, "none"):
            continue
        cd = cache.get(k)
        if not isinstance(cd, dict):
            continue
        c = cd.get("collection")
        if not (isinstance(c, dict) and c.get("id") == cid):
            continue
        if not gate(card_id):
            continue
        items.append({
            "id": card_id,
            "name": cd.get("title") or "",
            "year": cd.get("year"),
            "kind": cd.get("kind") or "movie",
            "poster": enrich.poster_url(cd.get("poster_path")),
        })
    items.sort(key=lambda x: (x.get("year") or 9999))
    return items[:cap]


# --------------------------------------------------------------------------- #
# Parental controls — filter the catalog / block playback above the viewer's
# maturity ceiling. Each title's level comes from the TMDB certification cache.
# --------------------------------------------------------------------------- #
def viewer_ceiling():
    """(ceiling_level, hide_unrated) for the active viewer. (MATURITY_MAX, False)
    means no restriction — the default for the box owner / adult profiles."""
    if is_combined_subprofile():            # accounts+profiles: the sub-profile's ceiling
        return active_profile_ceiling()
    if rt.ACCOUNTS_ENABLED:
        uid = _current_uid()
        if not uid:
            return MATURITY_MAX, False
        try:
            m = int((get_user(uid) or {}).get("maturity", MATURITY_MAX))
        except (TypeError, ValueError):
            m = MATURITY_MAX
        return m, (m < MATURITY_MAX)
    if rt.PROFILES_ENABLED:
        return active_profile_ceiling()
    return MATURITY_MAX, False


def external_suggestions_ok():
    """Whether to surface TMDB titles you don't own (discovery / search). Off for
    maturity-restricted viewers — those results carry no certification to filter on."""
    ceiling, _ = viewer_ceiling()
    return ceiling >= MATURITY_MAX


def _maturity_lookup():
    match = enrich.load_match()
    cache = enrich.load_cache()

    def level(cid):
        key = enrich.match_key(match.get(cid))
        d = cache.get(key) if key not in (None, "none") else None
        return d.get("maturity") if isinstance(d, dict) else None
    return level


def _allowed(level, ceiling, hide_unrated):
    if ceiling >= MATURITY_MAX:
        return True
    if level is None:
        return not hide_unrated          # unrated → hidden for a kid ceiling (safer)
    return level <= ceiling


def _card_id_for_path(path):
    """The catalog card id a media path belongs to (a movie is itself; an episode
    rolls up to its show folder) — so playback can be checked against the title."""
    p = Path(path)
    ep = parse_episode(p.name)
    if ep is not None:
        sdir, _ = series_dir_for(p)
        return str(sdir)
    return str(p)


def play_gate():
    """A predicate `allowed(path_or_id) -> bool` combining the active viewer's
    parental-controls (maturity ceiling) AND library scope (which roots they may see).
    Built once (vs. per item); near-zero cost for an unrestricted viewer. Accepts either
    a file path or a catalog card id (both resolve to the owning title / root)."""
    ceiling, hide = viewer_ceiling()
    scope = viewer_root_scope()              # set of allowed root path-strings, or None
    mature = ceiling < MATURITY_MAX
    if not mature and scope is None:
        return lambda _path: True            # unrestricted viewer — no work
    level = _maturity_lookup() if mature else None

    def ok(path):
        if scope is not None:                # library scoping: must live in an allowed root
            r = owning_root(Path(path))
            if r is None or str(r) not in scope:
                return False
        if mature and not _allowed(level(_card_id_for_path(path)), ceiling, hide):
            return False                     # parental controls: above the ceiling
        return True
    return ok


def filter_maturity(cat):
    """Drop shows/movies the active viewer may not see (maturity + scope) from a
    catalog payload."""
    if not isinstance(cat, dict):
        return cat
    gate = play_gate()
    for key in ("shows", "movies"):
        cat[key] = [it for it in cat.get(key, []) if gate(it.get("id", ""))]
    return cat


def title_allowed(card_id):
    return play_gate()(card_id)


def path_allowed(path):
    """Whether the active viewer may play this file (maturity + library scope)."""
    return play_gate()(path)


# --------------------------------------------------------------------------- #
# Watch history — finished titles for the active viewer, newest first
# --------------------------------------------------------------------------- #
def _finished(rec):
    dur = (rec or {}).get("duration") or 0
    pos = (rec or {}).get("position", 0) or 0
    return bool(dur) and (pos / dur) >= WATCHED_FRAC


def watch_history(limit=80):
    """The titles the active viewer has finished, newest-first. Episodes roll up to
    their show (so a binge shows as one card, stamped with the latest episode you
    finished). Derived from the resume table — per-viewer, no tracking log needed."""
    progress = load_progress()
    if not progress:
        return []
    finished = [(p, (r.get("updated", 0) or 0), r) for p, r in progress.items() if _finished(r)]
    finished.sort(key=lambda x: x[1], reverse=True)

    gate = play_gate()                                 # parental controls
    out, seen = [], set()
    for path, updated, rec in finished:
        p = Path(path)
        if p.suffix.lower() not in VIDEO_EXTS:
            continue
        if resolve_within_roots(path, must_exist=True) is None:
            continue                                  # file gone / outside the library
        if not gate(path):
            continue                                  # above the viewer's maturity ceiling
        ep = parse_episode(p.name)
        if ep is not None:
            season, epno = ep
            sdir, sfolder = series_dir_for(p)
            tid = str(sdir)
            entry = {"id": tid, "kind": "show", "name": clean_title(sdir.name) or sdir.name,
                     "when": updated, "episode": f"S{season}E{epno}", "path": path}
        else:
            tid = path
            entry = {"id": tid, "kind": "movie", "name": clean_title(p.name),
                     "when": updated, "episode": None, "path": path}
        if tid in seen:
            continue
        seen.add(tid)
        out.append(entry)
        if len(out) >= limit:
            break
    return out
