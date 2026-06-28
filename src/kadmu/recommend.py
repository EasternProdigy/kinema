"""Recommendations — a content-based recommender tuned for a *personal* library.

There's no crowd here (one viewer per profile) and the app never phones home, so classic
collaborative filtering doesn't apply. Instead this is a strong **content-based** engine,
pure-stdlib (no numpy/sklearn), built from signals already in the store:

  • **thumbs ratings** (-1/0/1, with the time you set them),
  • **watch history** — finished (≥95%), completion ratio, recency, and *abandoned* (started
    a little, long ago, never resumed) as a soft negative,
  • **content features** per title — genres / keywords / cast & directors / original language
    from the metadata layer (when on), plus always-available local features: decade,
    movie-vs-show, runtime band, and title/franchise tokens.

How it ranks (all stdlib):
  1. Each title → a sparse **feature vector**, every tag weighted by **TF-IDF** so a rare,
     discriminating tag ("k:dystopia") counts far more than a ubiquitous one ("g:drama").
  2. A per-viewer **taste vector** = the time-decayed, signed sum of the vectors of the
     titles you rated/finished (dislikes & abandons subtract). Newer signals weigh more
     (exponential half-life), so it tracks evolving taste.
  3. Score = **cosine(taste, title)** (your taste) + an **item-item neighbor** term (max
     similarity to something you liked) + a **freshness** prior + a mild **quality** prior.
  4. The "Top picks" shelf is then **diversified with MMR** so it isn't ten near-identical
     titles — the "variety" dial controls how hard.

All of it is transparent and user-tunable (see reco_config / set_reco_weights) and every
recommendation carries a human `why`. With no metadata yet it degrades to the local features
+ ratings/recency and still works; it gets markedly sharper the moment TMDB enrichment lands.

stdlib only; sits above catalog/store, below handler.
"""
from __future__ import annotations
import math
import re
import time

from .const import DATA_DIR, load_json
from .catalog import build_catalog
from .store import load_reco_weights, save_reco_weights, load_ratings, load_progress

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "and", "to", "in", "on", "season", "series", "complete",
         "collection", "part", "vol", "volume", "episode", "ep", "movie", "film"}
_YEAR = re.compile(r"^(?:19|20)\d{2}$")

# Feature base weights (before TF-IDF). Strong discriminators (keywords, people) over
# broad ones (kind). Local features (decade/tokens/len) are always available; the rest
# come from the metadata layer when present.
_FW = {"g": 1.0, "k": 0.9, "p": 0.7, "lang": 0.3, "dec": 0.4, "kind": 0.15, "t": 0.35, "len": 0.15}

# Taste signal strengths (scaled by recency decay + completion confidence).
_HALFLIFE_DAYS = 240.0          # a rating/watch this old counts half as much
_S_LIKE, _S_DISLIKE, _S_FINISH, _S_ABANDON = 1.0, 1.0, 0.6, 0.3

# The four user-facing dials (multipliers, default 1.0 = "automatic"). Clamped 0..3.
WEIGHT_KEYS = ("genre", "similar", "fresh", "surprise")
DEFAULT_WEIGHTS = {k: 1.0 for k in WEIGHT_KEYS}
WEIGHT_INFO = [
    {"key": "genre", "label": "Match my taste",
     "help": "How strongly to favor the genres, keywords, and people you rate up or finish."},
    {"key": "similar", "label": "More like what I liked",
     "help": "Weight titles that closely resemble a specific one you gave a thumbs-up."},
    {"key": "fresh", "label": "Recently added",
     "help": "Boost newer additions to your library."},
    {"key": "surprise", "label": "Variety",
     "help": "Spread the picks out so it isn't the same kind of thing over and over."},
]


# --------------------------------------------------------------------------- #
# Dials
# --------------------------------------------------------------------------- #
def clean_weights(d) -> dict:
    out = {}
    for k in WEIGHT_KEYS:
        try:
            out[k] = max(0.0, min(3.0, float((d or {}).get(k))))
        except (TypeError, ValueError):
            continue
    return out


def effective_weights(custom) -> dict:
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


# --------------------------------------------------------------------------- #
# Feature source — the title → tag-weights map (metadata layer + local features)
# --------------------------------------------------------------------------- #
class FeatureSource:
    """Reads the optional metadata caches (catalog_match.json → tmdb_cache.json) and
    derives a weighted tag dict per catalog card. Always contributes local features so
    the engine is useful even with no metadata."""

    def __init__(self):
        m = load_json(DATA_DIR / "catalog_match.json", {})
        t = load_json(DATA_DIR / "tmdb_cache.json", {})
        self._match = m if isinstance(m, dict) else {}
        self._tmdb = t if isinstance(t, dict) else {}

    def _detail(self, cid):
        tid = self._match.get(cid)
        if tid is None:
            return {}
        d = self._tmdb.get(str(tid)) or self._tmdb.get(tid) or {}
        return d if isinstance(d, dict) else {}

    def tags(self, card) -> dict:
        f: dict[str, float] = {}
        d = self._detail(card["id"])

        def add(prefix, value, cap=None):
            if not isinstance(value, str) or not value.strip():
                return
            key = f"{prefix}:{value.strip().lower()}"
            f[key] = max(f.get(key, 0.0), _FW[prefix])

        for g in (d.get("genres") or []):
            add("g", g)
        for k in (d.get("keywords") or [])[:12]:
            add("k", k)
        for p in (d.get("cast") or [])[:6]:
            add("p", p)
        for p in (d.get("directors") or d.get("crew") or [])[:3]:
            add("p", p)
        add("lang", d.get("original_language"))

        # Local features (always available).
        y = card.get("year")
        if y:
            f[f"dec:{(int(y) // 10) * 10}"] = _FW["dec"]
        if card.get("kind"):
            f[f"kind:{card['kind']}"] = _FW["kind"]
        for tk in _tokens(card.get("name", "")):
            f[f"t:{tk}"] = _FW["t"]
        if card.get("kind") == "movie":
            dur = card.get("duration") or 0
            band = "short" if 0 < dur < 2400 else ("epic" if dur > 7200 else ("feature" if dur else None))
            if band:
                f[f"len:{band}"] = _FW["len"]
        return f

    def quality(self, card) -> float:
        v = self._detail(card["id"]).get("vote_average")
        try:
            return max(0.0, min(1.0, float(v) / 10.0)) if v else 0.0
        except (TypeError, ValueError):
            return 0.0

    def has_metadata(self, cards) -> bool:
        return any(self._detail(c["id"]).get("genres") for c in cards)


# --------------------------------------------------------------------------- #
# Vector math (sparse dicts; stdlib)
# --------------------------------------------------------------------------- #
def _idf(index):
    n = len(index) or 1
    df: dict[str, int] = {}
    for tags in index.values():
        for t in tags:
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


def _vec(tags, idf):
    return {t: w * idf.get(t, 1.0) for t, w in tags.items()}


def _norm(v):
    return math.sqrt(sum(x * x for x in v.values())) or 1.0


def _cos(a, an, b, bn):
    if len(a) > len(b):
        a, b = b, a
    s = 0.0
    for t, w in a.items():
        o = b.get(t)
        if o:
            s += w * o
    return s / (an * bn)


# --------------------------------------------------------------------------- #
# Title state + signals
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
    return c.get("rating", 0) != -1 and not _finished(c)


def _decay(ts, now):
    if not ts:
        return 0.45                       # unknown time → mild weight
    age = max(0.0, (now - ts) / 86400.0)
    return 0.5 ** (age / _HALFLIFE_DAYS)


def _signal(c, now):
    """Signed taste weight for a title (+ liked/finished, − disliked/abandoned), scaled by
    recency decay and completion confidence. 0 ⇒ no signal."""
    dec = _decay(max(c.get("rating_ts", 0) or 0, c.get("watch_ts", 0) or 0), now)
    r = c.get("rating", 0)
    if r == 1:
        return _S_LIKE * dec
    if r == -1:
        return -_S_DISLIKE * dec
    if _finished(c):
        comp = c.get("completion", 1.0) or 1.0
        return _S_FINISH * (0.6 + 0.4 * min(1.0, comp)) * dec
    comp = c.get("completion", 0.0) or 0.0
    wts = c.get("watch_ts", 0) or 0
    if 0.02 < comp < 0.2 and wts and (now - wts) > 21 * 86400:
        return -_S_ABANDON * dec          # started, drifted away → soft negative
    return 0.0


# --------------------------------------------------------------------------- #
# The model (pure: cards already enriched with rating_ts/watch_ts/completion)
# --------------------------------------------------------------------------- #
def build_model(cards, tags_for, quality_for, now):
    index = {c["id"]: (tags_for(c) or {}) for c in cards}
    idf = _idf(index)
    vecs = {cid: _vec(tags, idf) for cid, tags in index.items()}
    norms = {cid: _norm(v) for cid, v in vecs.items()}

    taste: dict[str, float] = {}
    liked, finished_pos = [], []
    for c in cards:
        s = _signal(c, now)
        if s == 0:
            continue
        if c.get("rating") == 1:
            liked.append(c["id"])
        elif s > 0:
            finished_pos.append(c["id"])
        for t, w in vecs[c["id"]].items():
            taste[t] = taste.get(t, 0.0) + s * w
    return {
        "index": index, "idf": idf, "vecs": vecs, "norms": norms,
        "taste": taste, "taste_norm": _norm(taste),
        "liked": liked, "seeds": liked or finished_pos,
        "quality": {c["id"]: (quality_for(c) if quality_for else 0.0) for c in cards},
        "has_signal": bool(taste),
    }


def _freshness(cards):
    mts = [c.get("mtime", 0) or 0 for c in cards] or [0]
    lo, hi = min(mts), max(mts)
    rng = (hi - lo) or 1
    return {c["id"]: ((c.get("mtime", 0) or 0) - lo) / rng for c in cards}


def _base_score(cid, M, fr, w):
    cos = _cos(M["taste"], M["taste_norm"], M["vecs"][cid], M["norms"][cid]) if M["taste"] else 0.0
    nb = 0.0
    if M["liked"]:
        nb = max(_cos(M["vecs"][l], M["norms"][l], M["vecs"][cid], M["norms"][cid])
                 for l in M["liked"])
    return (w["genre"] * cos
            + w["similar"] * 0.6 * nb
            + w["fresh"] * 0.5 * fr.get(cid, 0.0)
            + 0.25 * M["quality"].get(cid, 0.0))


def _minmax(scores):
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    rng = (hi - lo) or 1.0
    return {k: (v - lo) / rng for k, v in scores.items()}


def _mmr(ids, score01, M, k, lam):
    """Maximal Marginal Relevance: greedily pick high-scoring items that are also
    dissimilar to those already picked — diversity without losing relevance."""
    pool, picked, pv = list(ids), [], []
    while pool and len(picked) < k:
        best, best_val = None, None
        for cid in pool:
            div = max((_cos(M["vecs"][cid], M["norms"][cid], v, n) for v, n in pv), default=0.0)
            val = (1 - lam) * score01.get(cid, 0.0) - lam * div
            if best_val is None or val > best_val:
                best, best_val = cid, val
        picked.append(best)
        pv.append((M["vecs"][best], M["norms"][best]))
        pool.remove(best)
    return picked


_PRETTY = {"g": lambda v: v.title(), "k": lambda v: v, "p": lambda v: v.title(),
           "dec": lambda v: v + "s", "lang": lambda v: v.upper(), "t": lambda v: v,
           "len": lambda v: {"short": "Short", "feature": "Feature", "epic": "Epic"}.get(v, v),
           "kind": lambda v: v}


def _pretty(tag):
    pre, _, val = tag.partition(":")
    return _PRETTY.get(pre, lambda v: v)(val)


def _top_match_tags(cid, M, n=2):
    """The tags that most explain why a title matches the taste vector."""
    v, taste = M["vecs"][cid], M["taste"]
    scored = [(t, w * taste.get(t, 0.0)) for t, w in v.items() if taste.get(t, 0.0) > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    pretty = []
    for t, _s in scored:
        if t.startswith(("g:", "k:", "p:", "dec:", "len:")):  # human-meaningful tags only
            pretty.append(_pretty(t))
        if len(pretty) >= n:
            break
    return pretty


def _why(cid, card, reason, M, seed_name=None):
    if reason == "continue":
        return "Next episode up" if _is_show(card) else "Pick up where you left off"
    if reason == "because":
        return f"Similar to {seed_name}" if seed_name else "Similar to one you liked"
    if reason == "gem":
        return "A gem you haven't started"
    if reason == "again":
        return "Worth a rewatch"
    tags = _top_match_tags(cid, M)
    if tags:
        return "Matches your taste: " + ", ".join(tags)
    if reason == "more" and seed_name:
        return f"More {seed_name}"
    return "New to your library"


def _item(card, reason, M, seed_name=None):
    d = dict(card)
    for k in ("rating_ts", "watch_ts", "completion"):   # internal-only; don't leak to UI
        d.pop(k, None)
    d["reason"] = reason
    d["why"] = _why(card["id"], card, reason, M, seed_name)
    return d


def recommend_rows(cards, tags_for, now, weights=None, quality_for=None,
                   top_n=24, max_because=3, mmr_cap=200):
    """The ordered recommendation shelves for a viewer's (enriched) catalog cards."""
    w = effective_weights(weights)
    M = build_model(cards, tags_for, quality_for, now)
    by_id = {c["id"]: c for c in cards}
    fr = _freshness(cards)
    lam = max(0.0, min(0.85, 0.35 * w["surprise"]))     # variety dial → MMR strength
    rows, used = [], set()

    # 1) Keep watching.
    kw = [c for c in cards if _in_progress(c)]
    kw.sort(key=lambda c: c.get("watch_ts", 0) or c.get("mtime", 0), reverse=True)
    if kw:
        rows.append({"key": "continue", "title": "Keep watching",
                     "items": [_item(c, "continue", M) for c in kw[:top_n]]})
        used |= {c["id"] for c in kw}

    # 2) Top picks — score → take the best, diversify with MMR.
    elig = [c["id"] for c in cards if _eligible(c) and c["id"] not in used]
    base = {cid: _base_score(cid, M, fr, w) for cid in elig}
    ranked = sorted(elig, key=lambda c: base[c], reverse=True)[:mmr_cap]
    picks = _mmr(ranked, _minmax({c: base[c] for c in ranked}), M, top_n, lam)
    if picks:
        rows.append({
            "key": "top",
            "title": "Top picks for you" if M["has_signal"] else "New & unwatched",
            "items": [_item(by_id[c], "top", M) for c in picks],
        })

    # 3) Because you liked X — nearest eligible titles to each recent thumbs-up.
    seeds = [c for c in cards if c.get("rating") == 1]
    seeds.sort(key=lambda c: c.get("rating_ts", 0) or c.get("watch_ts", 0) or c.get("mtime", 0),
               reverse=True)
    for seed in seeds[:max_because]:
        sv, sn = M["vecs"][seed["id"]], M["norms"][seed["id"]]
        sims = [(cid, _cos(sv, sn, M["vecs"][cid], M["norms"][cid]))
                for cid in elig if cid != seed["id"]]
        sims = [cid for cid, s in sorted(sims, key=lambda x: x[1], reverse=True) if s > 0.02][:top_n]
        if sims:
            rows.append({"key": f"because:{seed['id']}",
                         "title": f"Because you liked {seed.get('name', 'this')}",
                         "items": [_item(by_id[c], "because", M, seed.get("name")) for c in sims]})

    # 4) More <your strongest tag> — a genre/keyword shelf around your top affinity.
    pos = sorted(((t, s) for t, s in M["taste"].items()
                  if s > 0 and t.startswith(("g:", "k:"))), key=lambda x: x[1], reverse=True)
    if pos:
        tag = pos[0][0]
        hits = [cid for cid in ranked if tag in M["index"].get(cid, {})][:top_n]
        if len(hits) >= 3:
            rows.append({"key": f"more:{tag}", "title": f"More {_pretty(tag)}",
                         "items": [_item(by_id[c], "more", M, _pretty(tag)) for c in hits]})

    # 5) Hidden gems — eligible, never started, older in the library, decent score.
    if M["has_signal"]:
        gems = [cid for cid in ranked
                if (by_id[cid].get("completion", 0) or 0) == 0 and base[cid] > 0]
        gems.sort(key=lambda c: (by_id[c].get("mtime", 0) or 0))   # oldest first = surfacing
        gems = gems[:top_n]
        if len(gems) >= 3:
            rows.append({"key": "gems", "title": "Hidden gems in your library",
                         "items": [_item(by_id[c], "gem", M) for c in gems]})

    # 6) Watch again — finished favorites worth a rewatch.
    again = [c for c in cards if c.get("rating") == 1 and _finished(c)]
    again.sort(key=lambda c: c.get("watch_ts", 0) or c.get("mtime", 0), reverse=True)
    if again:
        rows.append({"key": "again", "title": "Watch again",
                     "items": [_item(c, "again", M) for c in again[:top_n]]})
    return rows


def profile_summary(cards, tags_for, has_metadata, now):
    M = build_model(cards, tags_for, None, now)
    top = sorted(((t, s) for t, s in M["taste"].items()
                  if s > 0 and t.startswith(("g:", "k:"))), key=lambda x: x[1], reverse=True)
    return {
        "titles": len(cards),
        "ratedUp": sum(1 for c in cards if c.get("rating") == 1),
        "ratedDown": sum(1 for c in cards if c.get("rating") == -1),
        "finished": sum(1 for c in cards if _finished(c)),
        "topGenres": [_pretty(t) for t, _s in top][:5],
        "hasGenres": has_metadata,
        "hasSignal": M["has_signal"],
    }


# --------------------------------------------------------------------------- #
# Public entry points (wire the live catalog + ratings + watch history + prefs)
# --------------------------------------------------------------------------- #
def _enriched_cards():
    cat = build_catalog()
    if not cat.get("ready"):
        return None
    cards = list(cat.get("shows", [])) + list(cat.get("movies", []))
    ratings, progress = load_ratings(), load_progress()
    for c in cards:
        c["rating_ts"] = (ratings.get(c["id"]) or {}).get("updated", 0) or 0
        if c.get("kind") == "show":
            ep = c.get("episodeCount") or 0
            c["completion"] = (c.get("watched", 0) / ep) if ep else 0.0
            c["watch_ts"] = c.get("lastWatched", 0) or 0
        else:
            pr = progress.get(c.get("path", "")) or {}
            dur = c.get("duration") or 0
            c["completion"] = (c.get("position", 0) / dur) if dur else (1.0 if c.get("watched") else 0.0)
            c["watch_ts"] = pr.get("updated", 0) or 0
    return cards


def recommend_for_viewer():
    cards = _enriched_cards()
    if cards is None:
        return {"ready": False, "rows": []}
    fs = FeatureSource()
    return {"ready": True,
            "rows": recommend_rows(cards, fs.tags, time.time(),
                                   weights=load_reco_weights(), quality_for=fs.quality)}


def reco_config():
    cards = _enriched_cards() or []
    fs = FeatureSource()
    custom = load_reco_weights()
    return {
        "weights": effective_weights(custom),
        "defaults": dict(DEFAULT_WEIGHTS),
        "custom": bool(clean_weights(custom)),
        "info": WEIGHT_INFO,
        "profile": profile_summary(cards, fs.tags, fs.has_metadata(cards), time.time()),
        "explain": ("Recommendations come only from your own activity on this account — the "
                    "titles you rate up / down and what you watch. Each title is described by "
                    "its genres, keywords, cast and more; Kadmu learns the mix you favor (newer "
                    "ratings count more) and finds the closest matches, then spreads them out so "
                    "you get variety. Nothing leaves your library. Use the dials to weight it, or "
                    "reset to automatic."),
        "min": 0.0, "max": 3.0, "step": 0.1,
    }


def set_reco_weights(weights):
    """Persist the viewer's dials. None/empty resets to automatic (defaults)."""
    return save_reco_weights(clean_weights(weights) if weights else {})
