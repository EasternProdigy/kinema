"""Recommendations — "what should I watch?" derived from the viewer's own taste.

Signals (all already in the store): **thumbs ratings** (-1/0/1 per show/movie),
**watch history** (finished ≥95% / in-progress / recency, from the resume table), and,
when the streaming-mode metadata layer is on, **TMDB genres** per title. From those we
build a per-viewer taste profile (genre affinities + liked titles) and score every owned
title the viewer hasn't finished, producing Netflix-style rows:

  • Keep watching      — shows mid-season / movies started but not finished
  • Top picks for you  — best unwatched matches to your taste (recency-only until you rate)
  • Because you liked X — titles most similar to each one you gave a 👍

It degrades gracefully: with no genres yet (TMDB off) it leans on ratings, finish
history, title/franchise overlap and freshness, so it's useful from day one and gets
sharper the moment enrichment lands. Pure-ish (reads catalog/ratings/progress) and
stdlib-only; sits above catalog/store, below handler.

`genres_for(catalog_id)` is the forward-compatible hook into the metadata layer: it
reads the (optional) `catalog_match.json` (catalog id → tmdb id) + `tmdb_cache.json`
(tmdb id → {genres,…}); both absent ⇒ it returns [] and the genre dimension is simply 0.
"""
from __future__ import annotations
import hashlib
import re
import time

from .const import DATA_DIR, load_json
from .catalog import build_catalog
from .store import load_ratings  # noqa: F401  (kept for parity / future weighting)

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "and", "to", "in", "on", "season", "series",
         "complete", "collection", "part", "vol", "volume", "episode", "ep"}
_YEAR = re.compile(r"^(?:19|20)\d{2}$")

# Scoring weights (tunable). Genre affinity dominates once metadata exists; token
# overlap + freshness carry the no-metadata case.
_W_GENRE, _W_TOKEN, _W_FRESH, _W_JITTER = 1.5, 0.8, 0.5, 0.05
_LIKE, _FINISH, _DISLIKE = 2, 1, -2     # taste weights per signal


def _tokens(name: str) -> set:
    out = set()
    for t in _TOKEN.findall((name or "").lower()):
        if len(t) < 2 or t in _STOP or _YEAR.match(t):
            continue
        out.add(t)
    return out


def _jitter(cid: str) -> float:
    """Deterministic 0..1 tiebreak so ordering is stable across requests (no RNG)."""
    return int(hashlib.sha1((cid or "").encode("utf-8")).hexdigest()[:6], 16) / 0xFFFFFF


# --------------------------------------------------------------------------- #
# Metadata hook (forward-compatible with the TMDB enrichment layer)
# --------------------------------------------------------------------------- #
def load_genre_map():
    """Return a `genres_for(catalog_id) -> [genre, …]` callable. Reads the optional
    match + tmdb caches; with neither present every title has no genres (the engine
    falls back to ratings/tokens/freshness)."""
    match = load_json(DATA_DIR / "catalog_match.json", {})
    tmdb = load_json(DATA_DIR / "tmdb_cache.json", {})
    if not isinstance(match, dict) or not isinstance(tmdb, dict):
        match, tmdb = {}, {}

    def genres_for(cid):
        tid = match.get(cid)
        if tid is None:
            return []
        rec = tmdb.get(str(tid)) or tmdb.get(tid) or {}
        g = rec.get("genres") or []
        return [x for x in g if isinstance(x, str)]

    return genres_for


# --------------------------------------------------------------------------- #
# Title state helpers (catalog cards: shows carry watched=int/episodeCount;
# movies carry watched=bool/position/duration)
# --------------------------------------------------------------------------- #
def _is_show(c):
    return c.get("kind") == "show"


def _finished(c) -> bool:
    if _is_show(c):
        n = c.get("episodeCount", 0) or 0
        return n > 0 and (c.get("watched", 0) or 0) >= n
    return bool(c.get("watched"))


def _in_progress(c) -> bool:
    if _is_show(c):
        w = c.get("watched", 0) or 0
        return 0 < w < (c.get("episodeCount", 0) or 0)
    return bool(c.get("position")) and not c.get("watched")


def _eligible(c) -> bool:
    """A candidate to recommend: not thumbs-down, not already finished."""
    return c.get("rating", 0) != -1 and not _finished(c)


# --------------------------------------------------------------------------- #
# Taste profile + scoring (pure: operate on cards + a genres_for callable)
# --------------------------------------------------------------------------- #
def build_profile(cards, genres_for):
    aff: dict[str, float] = {}
    liked, disliked, liked_tokens = set(), set(), set()
    any_rating = any(c.get("rating") for c in cards)
    any_finish = any(_finished(c) for c in cards)
    for c in cards:
        r = c.get("rating", 0)
        if r == 1:
            w = _LIKE
            liked.add(c["id"]); liked_tokens |= _tokens(c.get("name", ""))
        elif r == -1:
            w = _DISLIKE
            disliked.add(c["id"])
        elif _finished(c):
            w = _FINISH
            liked_tokens |= _tokens(c.get("name", ""))
        else:
            continue
        for g in genres_for(c["id"]):
            aff[g] = aff.get(g, 0) + w
    return {"aff": aff, "liked": liked, "disliked": disliked,
            "liked_tokens": liked_tokens,
            "has_signal": bool(aff) or any_rating or any_finish}


def _freshness_map(cards):
    mts = [c.get("mtime", 0) or 0 for c in cards] or [0]
    lo, hi = min(mts), max(mts)
    rng = (hi - lo) or 1
    return {c["id"]: ((c.get("mtime", 0) or 0) - lo) / rng for c in cards}


def _score(c, profile, genres_for, fr_map):
    gs = sum(profile["aff"].get(g, 0) for g in genres_for(c["id"]))
    ts = len(_tokens(c.get("name", "")) & profile["liked_tokens"])
    fr = fr_map.get(c["id"], 0)
    return _W_GENRE * gs + _W_TOKEN * ts + _W_FRESH * fr + _W_JITTER * _jitter(c["id"])


def _similar(seed, c, genres_for):
    sg, cg = set(genres_for(seed["id"])), set(genres_for(c["id"]))
    gj = len(sg & cg) / (len(sg | cg) or 1)
    tk = len(_tokens(seed.get("name", "")) & _tokens(c.get("name", "")))
    return 3 * gj + tk


def _item(card, reason):
    d = dict(card)            # copy so the same card can appear in multiple rows
    d["reason"] = reason
    return d


def recommend_rows(cards, genres_for, now, top_n=20, max_because=3):
    """The ordered list of recommendation rows for a viewer's catalog cards."""
    profile = build_profile(cards, genres_for)
    fr_map = _freshness_map(cards)
    rows = []
    used = set()

    # 1) Keep watching — most actionable, shown first.
    kw = [c for c in cards if _in_progress(c)]
    kw.sort(key=lambda c: c.get("lastWatched", 0) or c.get("position", 0) or c.get("mtime", 0),
            reverse=True)
    if kw:
        rows.append({"key": "continue", "title": "Keep watching",
                     "items": [_item(c, "continue") for c in kw[:top_n]]})
        used |= {c["id"] for c in kw}

    # 2) Top picks — best eligible matches to taste (recency-led until you rate).
    pool = [c for c in cards if _eligible(c) and c["id"] not in used]
    pool.sort(key=lambda c: _score(c, profile, genres_for, fr_map), reverse=True)
    if pool:
        rows.append({
            "key": "top",
            "title": "Top picks for you" if profile["has_signal"] else "New & unwatched",
            "items": [_item(c, "top") for c in pool[:top_n]],
        })

    # 3) Because you liked X — per thumbs-up seed, the most similar eligible titles.
    seeds = [c for c in cards if c.get("rating") == 1]
    seeds.sort(key=lambda c: c.get("lastWatched", 0) or c.get("mtime", 0), reverse=True)
    for seed in seeds[:max_because]:
        ranked = sorted(
            ((c, _similar(seed, c, genres_for)) for c in cards
             if c["id"] != seed["id"] and _eligible(c)),
            key=lambda x: x[1], reverse=True)
        items = [_item(c, "because") for c, s in ranked if s > 0][:top_n]
        if items:
            rows.append({"key": f"because:{seed['id']}",
                         "title": f"Because you liked {seed.get('name', 'this')}",
                         "items": items})
    return rows


# --------------------------------------------------------------------------- #
# Public entry — wires the live catalog + ratings + metadata into the engine
# --------------------------------------------------------------------------- #
def recommend_for_viewer():
    cat = build_catalog()
    if not cat.get("ready"):
        return {"ready": False, "rows": []}
    cards = list(cat.get("shows", [])) + list(cat.get("movies", []))
    return {"ready": True, "rows": recommend_rows(cards, load_genre_map(), time.time())}
