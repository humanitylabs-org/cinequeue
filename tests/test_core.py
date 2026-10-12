import json
import tempfile
import unittest
from pathlib import Path

from cinequeue.core import MovieStore, parse_movie_requests, slugify


class ParseMovieRequestsTest(unittest.TestCase):
    def test_parses_natural_language_movie_list(self):
        text = "Add The Wailing (2016), Stalker 1979 and Project Hail Mary to my watchlist"
        self.assertEqual(
            parse_movie_requests(text),
            [
                {"title": "The Wailing", "year": 2016},
                {"title": "Stalker", "year": 1979},
                {"title": "Project Hail Mary", "year": None},
            ],
        )

    def test_slugify_is_stable_for_duplicates(self):
        self.assertEqual(slugify("The Wailing", 2016), "the-wailing-2016")
        self.assertEqual(slugify("Project Hail Mary", None), "project-hail-mary")


class MovieStoreTest(unittest.TestCase):
    def test_add_movies_deduplicates_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "movies.json"
            store = MovieStore(path)
            added = store.add_many([
                {"title": "The Wailing", "year": 2016, "poster": "poster.jpg", "source": "test"},
                {"title": "The Wailing", "year": 2016, "poster": "poster2.jpg", "source": "test"},
            ])

            self.assertEqual(len(added), 1)
            saved = json.loads(path.read_text())
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["title"], "The Wailing")
            self.assertFalse(saved[0]["watched"])

    def test_title_without_year_matches_existing_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "movies.json"
            store = MovieStore(path)
            store.add_many([{"title": "Project Hail Mary", "year": 2026}])
            added = store.add_many([{"title": "Project Hail Mary", "year": None}])

            self.assertEqual(added, [])
            self.assertEqual(len(json.loads(path.read_text())), 1)

    def test_all_preserves_file_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "movies.json"
            path.write_text(json.dumps([
                {"id": "first", "title": "First", "watched": False, "added_at": "letterboxd-order"},
                {"id": "second", "title": "Second", "watched": True, "added_at": "2026-01-01"},
            ]))
            store = MovieStore(path)

            self.assertEqual([m["id"] for m in store.all()], ["first", "second"])

    def test_toggle_watched_changes_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "movies.json"
            store = MovieStore(path)
            movie = store.add_many([{"title": "Stalker", "year": 1979}])[0]
            updated = store.toggle_watched(movie["id"])
            self.assertTrue(updated["watched"])

    def test_get_returns_movie_by_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "movies.json"
            store = MovieStore(path)
            movie = store.add_many([{"title": "Stalker", "year": 1979}])[0]

            self.assertEqual(store.get(movie["id"])["title"], "Stalker")
            self.assertIsNone(store.get("missing"))

    def test_set_archived_preserves_index_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "movies.json"
            path.write_text(json.dumps([
                {"id": "first", "title": "First", "watched": False, "added_at": "a", "poster": "p1"},
                {"id": "second", "title": "Second", "watched": True, "added_at": "b", "genres": ["Drama"]},
                {"id": "third", "title": "Third", "watched": False, "added_at": "c"},
            ]))
            store = MovieStore(path)
            before = json.loads(path.read_text())

            store.set_archived("second", True)
            after = json.loads(path.read_text())

            self.assertEqual([m["id"] for m in after], ["first", "second", "third"])
            for key in ("title", "watched", "added_at", "genres"):
                self.assertEqual(after[1].get(key), before[1].get(key))
            self.assertTrue(after[1]["archived"])
            self.assertTrue(after[1]["archived_at"])
            self.assertNotIn("archived", after[0])
            self.assertNotIn("archived", after[2])

    def test_archive_restore_round_trips_order_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "movies.json"
            original = [
                {"id": "first", "title": "First", "watched": False, "added_at": "a", "poster": "p1"},
                {"id": "second", "title": "Second", "watched": True, "added_at": "b", "genres": ["Drama"], "rating": 4.5},
            ]
            path.write_text(json.dumps(original))
            store = MovieStore(path)

            store.set_archived("first", True)
            store.set_archived("second", True)
            store.set_archived("first", False)
            store.set_archived("second", False)
            restored = json.loads(path.read_text())

            self.assertEqual([m["id"] for m in restored], ["first", "second"])
            for before, after in zip(original, restored):
                for key, value in before.items():
                    self.assertEqual(after.get(key), value, key)

    def test_set_archived_unknown_id_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "movies.json"
            store = MovieStore(path)
            store.add_many([{"title": "Stalker", "year": 1979}])
            with self.assertRaises(KeyError):
                store.set_archived("missing", True)

    def test_move_to_top_reorders_existing_movie(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "movies.json"
            path.write_text(json.dumps([
                {"id": "first", "title": "First"},
                {"id": "second", "title": "Second"},
                {"id": "third", "title": "Third"},
            ]))
            store = MovieStore(path)

            moved = store.move_to_top("third")

            self.assertEqual(moved["title"], "Third")
            self.assertEqual([m["id"] for m in store.all()], ["third", "first", "second"])


if __name__ == "__main__":
    unittest.main()
