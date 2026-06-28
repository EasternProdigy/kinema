"""Unit tests for the content-based recommendation engine (src/kadmu/recommend.py).

Pure: drives the model with synthetic catalog cards + a stub tag source, no DB, no
network. Run:  python3 src/kadmu/tests/test_recommend.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from kadmu import recommend  # noqa: E402

DAY = 86400
NOW = 1_750_000_000

# id -> {tag: weight}. In tests this stub fully replaces FeatureSource.tags.
TAGS = {
    "alien": {"g:scifi": 1.0, "k:dystopia": 0.9}, "blade": {"g:scifi": 1.0, "k:dystopia": 0.9},
    "dune": {"g:scifi": 1.0}, "notebook": {"g:romance": 1.0}, "evil": {"g:horror": 1.0},
    "found": {"g:scifi": 1.0}, "gigli": {"g:comedy": 1.0}, "titanic": {"g:drama": 1.0},
}
def tags_for(card): return dict(TAGS.get(card["id"], {}))
def quality_for(card): return 0.0


def movie(cid, name, rating=0, watched=False, position=0, duration=100, mtime=0,
          completion=None, watch_ts=0, rating_ts=0, year=None):
    comp = completion if completion is not None else (position / duration if duration else 0.0)
    return {"id": cid, "kind": "movie", "name": name, "rating": rating, "watched": watched,
            "position": position, "duration": duration, "mtime": mtime, "year": year,
            "completion": comp, "watch_ts": watch_ts, "rating_ts": rating_ts}
def show(cid, name, episodeCount, watched, rating=0, mtime=0, lastWatched=0):
    comp = watched / episodeCount if episodeCount else 0.0
    return {"id": cid, "kind": "show", "name": name, "episodeCount": episodeCount, "seasonCount": 1,
            "watched": watched, "rating": rating, "mtime": mtime, "lastWatched": lastWatched,
            "completion": comp, "watch_ts": lastWatched, "rating_ts": 0}

def rows_by_key(rows): return {r["key"]: r for r in rows}
def ids(row): return [it["id"] for it in row["items"]]


class VectorMath(unittest.TestCase):
    def test_idf_favors_rare_tags(self):
        index = {"a": {"common": 1, "rare": 1}, "b": {"common": 1}, "c": {"common": 1}}
        idf = recommend._idf(index)
        self.assertGreater(idf["rare"], idf["common"])   # rarer ⇒ more discriminating

    def test_cosine_basic(self):
        a = {"x": 1.0, "y": 1.0}
        b = {"x": 1.0}
        c = _cos = recommend._cos(a, recommend._norm(a), b, recommend._norm(b))
        self.assertAlmostEqual(c, (1.0) / (2 ** 0.5 * 1.0), places=6)


class Signals(unittest.TestCase):
    def test_recent_like_outweighs_old_like(self):
        recent = recommend._signal(movie("m", "M", rating=1, rating_ts=NOW), NOW)
        old = recommend._signal(movie("m", "M", rating=1, rating_ts=NOW - 730 * DAY), NOW)
        self.assertGreater(recent, old)
        self.assertGreater(old, 0)

    def test_dislike_is_negative(self):
        self.assertLess(recommend._signal(movie("m", "M", rating=-1, rating_ts=NOW), NOW), 0)

    def test_finished_is_positive(self):
        self.assertGreater(recommend._signal(movie("m", "M", watched=True, watch_ts=NOW), NOW), 0)

    def test_abandoned_is_negative(self):
        # started ~10%, drifted away 40 days ago, never rated/finished → soft negative
        c = movie("m", "M", position=10, duration=100, watch_ts=NOW - 40 * DAY)
        self.assertLess(recommend._signal(c, NOW), 0)

    def test_unwatched_unrated_is_zero(self):
        self.assertEqual(recommend._signal(movie("m", "M"), NOW), 0.0)


class MMR(unittest.TestCase):
    def _M(self, vecs):
        return {"vecs": vecs, "norms": {k: recommend._norm(v) for k, v in vecs.items()}}

    def test_diversity_demotes_near_duplicates(self):
        vecs = {"a1": {"x": 1.0}, "a2": {"x": 1.0}, "a3": {"x": 1.0}, "b": {"y": 1.0}}
        M = self._M(vecs)
        score01 = {"a1": 1.0, "a2": 0.98, "a3": 0.97, "b": 0.9}
        diverse = recommend._mmr(list(vecs), score01, M, k=2, lam=0.7)
        self.assertEqual(diverse[0], "a1")
        self.assertEqual(diverse[1], "b")               # variety pulls the different item up
        greedy = recommend._mmr(list(vecs), score01, M, k=2, lam=0.0)
        self.assertEqual(greedy[1], "a2")               # no diversity ⇒ pure score order


class Rows(unittest.TestCase):
    def cards(self):
        return [
            movie("alien", "Alien", rating=1, rating_ts=NOW, mtime=100),   # liked seed, scifi
            movie("blade", "Blade Runner", mtime=90),                      # scifi candidate
            movie("notebook", "The Notebook", mtime=80),                   # romance
            movie("dune", "Dune", rating=-1, mtime=70),                    # disliked → excluded
            movie("evil", "Evil Dead", watched=True, mtime=60),            # finished → excluded
            show("found", "Foundation", 10, 3, mtime=50, lastWatched=NOW), # in-progress
            movie("gigli", "Gigli", position=50, duration=100, mtime=40),  # started
            movie("titanic", "Titanic", rating=1, watched=True, watch_ts=NOW, mtime=30),  # liked+finished
        ]

    def setUp(self):
        self.rows = recommend.recommend_rows(self.cards(), tags_for, NOW, quality_for=quality_for)
        self.by = rows_by_key(self.rows)

    def test_keep_watching(self):
        self.assertEqual(set(ids(self.by["continue"])), {"found", "gigli"})

    def test_top_excludes_disliked_finished_and_keepwatching(self):
        top = ids(self.by["top"])
        for x in ("dune", "evil", "found", "gigli", "titanic"):
            self.assertNotIn(x, top)
        self.assertIn("blade", top)                     # scifi, matches taste
        self.assertEqual(top[-1] if "notebook" in top else "notebook", "notebook")

    def test_taste_ranks_scifi_over_romance(self):
        top = ids(self.by["top"])
        self.assertLess(top.index("blade"), top.index("notebook"))

    def test_because_you_liked(self):
        self.assertIn("because:alien", self.by)
        items = ids(self.by["because:alien"])
        self.assertIn("blade", items)                   # shares scifi + dystopia
        self.assertNotIn("notebook", items)
        self.assertNotIn("alien", items)

    def test_watch_again(self):
        self.assertIn("again", self.by)
        self.assertEqual(set(ids(self.by["again"])), {"titanic"})

    def test_cold_start_title(self):
        plain = [movie("a", "A", mtime=2), movie("b", "B", mtime=1)]
        by = rows_by_key(recommend.recommend_rows(plain, tags_for, NOW))
        self.assertEqual(by["top"]["title"], "New & unwatched")
        self.assertEqual(set(ids(by["top"])), {"a", "b"})

    def test_why_present(self):
        self.assertTrue(all(it.get("why") for r in self.rows for it in r["items"]))
        self.assertNotIn("rating_ts", self.by["top"]["items"][0])   # internals stripped


class Dials(unittest.TestCase):
    def test_clean_weights_bounds_and_filtering(self):
        c = recommend.clean_weights({"genre": 5, "fresh": -2, "similar": "x", "bogus": 1, "surprise": 1.5})
        self.assertEqual(c.get("genre"), 3.0)
        self.assertEqual(c.get("fresh"), 0.0)
        self.assertNotIn("similar", c)
        self.assertNotIn("bogus", c)

    def test_effective_weights_merges_defaults(self):
        w = recommend.effective_weights({"genre": 2.0})
        self.assertEqual(w["genre"], 2.0)
        self.assertEqual(w["fresh"], 1.0)

    def test_fresh_dial_overrides_taste(self):
        cards = [movie("alien", "Alien", rating=1, rating_ts=NOW, mtime=1),
                 movie("blade", "Blade Runner", mtime=100),
                 movie("notebook", "The Notebook", mtime=50)]
        off = {"genre": 0, "similar": 0, "surprise": 0, "fresh": 3}
        top = ids(rows_by_key(recommend.recommend_rows(cards, tags_for, NOW, weights=off))["top"])
        self.assertEqual(top[0], "blade")               # taste muted, freshest wins

    def test_profile_summary(self):
        s = recommend.profile_summary(self.__cards(), tags_for, True, NOW)
        self.assertEqual(s["ratedUp"], 2)
        self.assertEqual(s["ratedDown"], 1)
        self.assertGreaterEqual(s["finished"], 1)
        self.assertIn("Scifi", s["topGenres"])

    def __cards(self):
        return [movie("alien", "Alien", rating=1, rating_ts=NOW),
                movie("blade", "Blade Runner", rating=1, rating_ts=NOW),
                movie("dune", "Dune", rating=-1), movie("evil", "Evil Dead", watched=True)]


if __name__ == "__main__":
    unittest.main(verbosity=2)
