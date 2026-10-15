"""Public first-install example. Never merge into or reset an existing owner store."""
from cinequeue.core import MovieStore

BATMAN_BEGINS = {
    "id": "batman-begins-2005", "title": "Batman Begins", "year": 2005,
    "poster": "https://upload.wikimedia.org/wikipedia/en/a/af/Batman_Begins_Poster.jpg",
    "letterboxd_url": "https://letterboxd.com/film/batman-begins/",
    "imdb_id": "tt0372784", "imdb_url": "https://www.imdb.com/title/tt0372784/",
    "description": "Bruce Wayne becomes Batman and confronts Ra's al Ghul and the Scarecrow as they threaten Gotham City.",
    "directors": ["Christopher Nolan"],
    "cast": ["Christian Bale", "Michael Caine", "Liam Neeson", "Katie Holmes", "Gary Oldman", "Cillian Murphy"],
    "genres": ["Action", "Crime", "Drama"], "runtime_minutes": 140,
    "source": "https://en.wikipedia.org/wiki/Batman_Begins",
    "notes": "", "watched": False, "queued": True, "watch_history": [],
    "added_at": "2005-06-15T00:00:00+00:00"
}


def initialize(path):
    # Lock before MovieStore creates the file, so simultaneous first starts cannot
    # duplicate the seed. An existing [] represents an intentional empty queue.
    from cinequeue.core import _store_lock
    path.parent.mkdir(parents=True, exist_ok=True)
    with _store_lock(path):
        fresh = not path.exists()
        store = MovieStore(path)
        if fresh:
            store.save([BATMAN_BEGINS])
        return store
