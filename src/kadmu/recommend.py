"""Recommendations — "what should I watch?" derived from the viewer's own taste,
with a transparent, user-tunable weighting.

Signals (all already in the store): **thumbs ratings** (-1/0/1 per show/movie),
**watch history** (finished ≥95% / in-progress / recency, from the resume table), and,
when the streaming-mode metadata layer is on, **TMDB genres** per title. From those we
build a per-viewer taste profile (genre affinities + liked titles) and score every owned
title the viewer hasn't finished into Netflix-style rows:

  • Keep watching      — shows mid-season / movies started but not finished
  • Top picks for you  — best unwatched matches to your taste (recency-only until you rate)
  • Because you liked X — titles most similar to each one you gave a thumbs-up

**Transparency + control.** The scorer's four dials are exposed to the viewer (see
`reco_config`/`set_reco_weights`): how much **genre match**, **similarity to what you
liked**, **recently added**, and **surprise** each count. A viewer can reweight them or
reset to automatic (defaults). Each recommended item also carries a short human `why`.

It degrades gracefully: with no genres yet (TMDB off) it leans on ratings, finish
history, title/franchise overlap and freshness, so it's useful from day one and gets
sharper the moment enrichment lands. Pure-ish (reads catalog/ratings/progress/prefs) and
stdlib-only; sits above catalog/store, below handler.
"""
from __future__ import annotations
import hashlib
import re
import time

from .const import DATA_DIR, load_json
from .catalog import build_catalog
from .store import load_reco_weights, save_reco_weights

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "and", "to", "in", "on", "season", "series",
         "complete", "collection", "part", "vol", "volume", "episode", "ep"}
_YEAR = re.compile(r"^(?:19|20)\d{2}$")

# Base scoring weights (the engine's shape). The viewer's dials multiply these.
_W_GENRE, _W_TOKEN, _W_FRESH, _W_JITTER = 1.5, 0.8, 0.5, 0.05
_LIKE, _FINISH, _DISLIKE = 2, 1, -2     # taste weights per signal

# The four user-facing dials (multipliers, default 1.0 = "automatic"). Clamped 0..3.
WEIGHT_KEYS = ("genre", "similar", "fresh", "surprise")
DEFAULT_WEIGHTS = {k: 1.0 for k in WEIGHT_KEYS}
WEIGHT_INFO = [
    {"key": "genre", "label": "Genre match",
     "help": "Favor titles in the genres you rate up or finish. (Needs metadata on.)"},
    {"key": "similar", "label": "Similar to what you liked",
     "help": "Weight titles like the ones you gave a thumbs-up — same series/franchise and shared genres."},
    {"key": "fresh", "label": "Recently added",
     "help": "Boost newer additions to your library."},
    {"key": "surprise", "label": "Surprise me",
     "help": "Add variety so it isn't always the same picks."},
]


def clean_weights(d) -> dict:
    """Keep only known dials, coerced to floats clamped to 0..3."""
    out = {}
    for k in WEIGHT_KEYS:
        try:
            out[k] = max(0.0, min(3.0, float((d or {}).get(k))))
        except (TypeError, ValueError):
            continue
    return out


def effective_weights(custom) -> dict:
    """Defaults with any saved overrides applied."""
    w = dict(DEFAULT_WEIGHTS)
    w.update(clean_weights(custom or {}))
    return w


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
        return [x for x in (rec.get("genres") or []) if isinstance(x, str)]

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


def _score(c, profile, genres_for, fr_map, w):
    gs = sum(profile["aff"].get(g, 0) for g in genres_for(c["id"]))
    ts = len(_tokens(c.get("name", "")) & profile["liked_tokens"])
    fr = fr_map.get(c["id"], 0)
    return (_W_GENRE * w["genre"] * gs
            + _W_TOKEN * w["similar"] * ts
            + _W_FRESH * w["fresh"] * fr
            + _W_JITTER * w["surprise"] * _jitter(c["id"]))


def _similar(seed, c, genres_for):
    sg, cg = set(genres_for(seed["id"])), set(genres_for(c["id"]))
    gj = len(sg & cg) / (len(sg | cg) or 1)
    tk = len(_tokens(seed.get("name", "")) & _tokens(c.get("name", "")))
    return 3 * gj + tk


def _why(card, reason, profile, genres_for, seed_name=None):
    """A short human reason for one recommendation (powers the transparency panel)."""
    if reason == "continue":
        return "Pick up where you left off" if not _is_show(card) else "Next episode up"
    if reason == "because":
        return f"Similar to {seed_name}" if seed_name else "Similar to one you liked"
    hot = [g for g in genres_for(card["id"]) if profile["aff"].get(g, 0) > 0]
    if hot:
        return "Matches your taste: " + ", ".join(hot[:2])
    if _tokens(card.get("name", "")) & profile["liked_tokens"]:
        return "Like other titles you enjoyed"
    return "New to your library"


def _item(card, reason, profile, genres_for, seed_name=None):
    d = dict(card)            # copy so the same card can appear in multiple rows
    d["reason"] = reason
    d["why"] = _why(card, reason, profile, genres_for, seed_name)
    return d


def recommend_rows(cards, genres_for, now, weights=None, top_n=20, max_because=3):
    """The ordered list of recommendation rows for a viewer's catalog cards."""
    w = effective_weights(weights)
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
                     "items": [_item(c, "continue", profile, genres_for) for c in kw[:top_n]]})
        used |= {c["id"] for c in kw}

    # 2) Top picks — best eligible matches to taste (recency-led until you rate).
    pool = [c for c in cards if _eligible(c) and c["id"] not in used]
    pool.sort(key=lambda c: _score(c, profile, genres_for, fr_map, w), reverse=True)
    if pool:
        rows.append({
            "key": "top",
            "title": "Top picks for you" if profile["has_signal"] else "New & unwatched",
            "items": [_item(c, "top", profile, genres_for) for c in pool[:top_n]],
        })

    # 3) Because you liked X — per thumbs-up seed, the most similar eligible titles.
    seeds = [c for c in cards if c.get("rating") == 1]
    seeds.sort(key=lambda c: c.get("lastWatched", 0) or c.get("mtime", 0), reverse=True)
    for seed in seeds[:max_because]:
        ranked = sorted(
            ((c, _similar(seed, c, genres_for)) for c in cards
             if c["id"] != seed["id"] and _eligible(c)),
            key=lambda x: x[1], reverse=True)
        items = [_item(c, "because", profile, genres_for, seed.get("name"))
                 for c, s in ranked if s > 0][:top_n]
        if items:
            rows.append({"key": f"because:{seed['id']}",
                         "title": f"Because you liked {seed.get('name', 'this')}",
                         "items": items})
    return rows


def profile_summary(cards, genres_for):
    """What the engine knows about this viewer — shown in the transparency panel."""
    prof = build_profile(cards, genres_for)
    top = sorted(prof["aff"].items(), key=lambda kv: kv[1], reverse=True)
    return {
        "titles": len(cards),
        "ratedUp": sum(1 for c in cards if c.get("rating") == 1),
        "ratedDown": sum(1 for c in cards if c.get("rating") == -1),
        "finished": sum(1 for c in cards if _finished(c)),
        "topGenres": [g for g, s in top if s > 0][:5],
        "hasGenres": any(genres_for(c["id"]) for c in cards),
        "hasSignal": prof["has_signal"],
    }


# --------------------------------------------------------------------------- #
# Public entry points (wire the live catalog + ratings + prefs into the engine)
# --------------------------------------------------------------------------- #
def _cards():
    cat = build_catalog()
    if not cat.get("ready"):
        return None
    return list(cat.get("shows", [])) + list(cat.get("movies", []))


def recommend_for_viewer():
    cards = _cards()
    if cards is None:
        return {"ready": False, "rows": []}
    return {"ready": True,
            "rows": recommend_rows(cards, load_genre_map(), time.time(),
                                   weights=load_reco_weights())}


def reco_config():
    """Everything the transparency/tuning panel needs: the current dials, the
    defaults, whether they've been customised, what each dial does, and a summary of
    the viewer's own signals."""
    cards = _cards() or []
    genres_for = load_genre_map()
    custom = load_reco_weights()
    return {
        "weights": effective_weights(custom),
        "defaults": dict(DEFAULT_WEIGHTS),
        "custom": bool(clean_weights(custom)),
        "info": WEIGHT_INFO,
        "profile": profile_summary(cards, genres_for),
        "explain": ("Recommendations come only from your own activity on this account — the "
                    "titles you thumbs-up / thumbs-down and what you watch. Nothing leaves "
                    "your library. Use the dials to weight what matters to you, or reset to "
                    "automatic to let Kadmu decide."),
        "min": 0.0, "max": 3.0, "step": 0.1,
    }


def set_reco_weights(weights):
    """Persist the viewer's dials. Pass None/empty to reset to automatic (defaults)."""
    return save_reco_weights(clean_weights(weights) if weights else {})
