"""Unit tests for the recommendation engine (src/kadmu/recommend.py).

Pure: drives the scorer with synthetic catalog cards + a stub genres_for, no DB,
no network. Run:  python3 src/kadmu/tests/test_recommend.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from kadmu import recommend  # noqa: E402

GENRES = {
    "alien": ["scifi"], "blade": ["scifi"], "notebook": ["romance"],
    "dune": ["action"], "evil": ["horror"], "foundation": ["scifi"], "gigli": ["comedy"],
}
def genres_for(cid): return GENRES.get(cid, [])

# Catalog cards (shows carry watched=int/episodeCount; movies watched=bool/position).
def movie(cid, name, rating=0, watched=False, position=0, mtime=0):
    return {"id": cid, "kind": "movie", "name": name, "rating": rating,
            "watched": watched, "position": position, "duration": 100, "mtime": mtime}
def show(cid, name, episodeCount, watched, rating=0, mtime=0, lastWatched=0):
    return {"id": cid, "kind": "show", "name": name, "episodeCount": episodeCount,
            "seasonCount": 1, "watched": watched, "rating": rating, "mtime": mtime,
            "lastWatched": lastWatched}

def cards():
    return [
        movie("alien", "Alien", rating=1, mtime=100),          # liked, scifi, eligible seed
        movie("blade", "Blade Runner", mtime=90),              # scifi candidate
        movie("notebook", "The Notebook", mtime=80),           # romance candidate
        movie("dune", "Dune", rating=-1, mtime=70),            # disliked → excluded
        movie("evil", "Evil Dead", watched=True, mtime=60),    # finished → excluded
        show("foundation", "Foundation", 10, 3, mtime=50),     # in-progress → keep watching
        movie("gigli", "Gigli", position=50, mtime=40),        # started → keep watching
    ]

def rows_by_key(rows):
    return {r["key"]: r for r in rows}
def ids(row):
    return [it["id"] for it in row["items"]]


class StateHelpers(unittest.TestCase):
    def test_finished_eligible_inprogress(self):
        self.assertTrue(recommend._finished(movie("m", "M", watched=True)))
        self.assertTrue(recommend._finished(show("s", "S", 5, 5)))
        self.assertFalse(recommend._finished(show("s", "S", 5, 2)))
        self.assertTrue(recommend._in_progress(show("s", "S", 5, 2)))
        self.assertTrue(recommend._in_progress(movie("m", "M", position=10)))
        self.assertFalse(recommend._eligible(movie("m", "M", rating=-1)))
        self.assertFalse(recommend._eligible(movie("m", "M", watched=True)))
        self.assertTrue(recommend._eligible(movie("m", "M", rating=1)))


class Rows(unittest.TestCase):
    def setUp(self):
        self.rows = recommend.recommend_rows(cards(), genres_for, now=1000)
        self.by = rows_by_key(self.rows)

    def test_keep_watching(self):
        self.assertIn("continue", self.by)
        s = set(ids(self.by["continue"]))
        self.assertEqual(s, {"foundation", "gigli"})

    def test_top_picks_excludes_disliked_finished_and_keepwatching(self):
        top = ids(self.by["top"])
        self.assertNotIn("dune", top)        # disliked
        self.assertNotIn("evil", top)        # finished
        self.assertNotIn("foundation", top)  # already in Keep watching
        self.assertNotIn("gigli", top)
        # scifi-liked taste ranks the two scifi titles above the romance one
        self.assertEqual(set(top[:2]), {"alien", "blade"})
        self.assertEqual(top[-1], "notebook")

    def test_because_you_liked(self):
        key = "because:alien"
        self.assertIn(key, self.by)
        self.assertEqual(self.by[key]["title"], "Because you liked Alien")
        items = ids(self.by[key])
        self.assertIn("blade", items)        # scifi → similar
        self.assertIn("foundation", items)   # scifi show → similar
        self.assertNotIn("notebook", items)  # romance → not similar
        self.assertNotIn("alien", items)     # never recommend the seed itself

    def test_no_signal_fallback_title(self):
        plain = [movie("a", "A movie", mtime=2), movie("b", "B movie", mtime=1)]
        rows = recommend.recommend_rows(plain, genres_for=lambda cid: [], now=1000)
        by = rows_by_key(rows)
        self.assertIn("top", by)
        self.assertEqual(by["top"]["title"], "New & unwatched")
        self.assertEqual(set(ids(by["top"])), {"a", "b"})

    def test_no_metadata_still_ranks_by_taste_tokens(self):
        # No genres at all: a thumbs-up on "Iron Man" should still surface "Iron Man 2"
        # above an unrelated title via title/franchise token overlap.
        c = [movie("im1", "Iron Man", rating=1, mtime=5),
             movie("im2", "Iron Man 2", mtime=4),
             movie("zz", "Casablanca", mtime=3)]
        rows = recommend.recommend_rows(c, genres_for=lambda cid: [], now=1000)
        because = rows_by_key(rows).get("because:im1")
        self.assertIsNotNone(because)
        self.assertEqual(ids(because)[0], "im2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
