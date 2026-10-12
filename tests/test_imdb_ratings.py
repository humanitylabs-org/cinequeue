from __future__ import annotations

import gzip
from copy import deepcopy

import pytest

from cinequeue.imdb_ratings import (
    apply_imdb_ratings,
    parse_imdb_ratings,
    verify_only_score_fields_changed,
)


def ratings_blob(*rows: str) -> bytes:
    text = "tconst\taverageRating\tnumVotes\n" + "\n".join(rows) + "\n"
    return gzip.compress(text.encode("utf-8"))


def test_parse_imdb_ratings_filters_to_wanted_ids():
    ratings = parse_imdb_ratings(
        ratings_blob("tt0000001\t5.7\t2100", "tt0000002\t8.3\t987654"),
        wanted_ids={"tt0000002"},
    )

    assert ratings == {"tt0000002": (8.3, 987654)}


def test_parse_imdb_ratings_rejects_short_dataset_and_zero_vote_rows():
    blob = ratings_blob("tt0000001\t5.7\t0", "tt0000002\t8.3\t12")

    with pytest.raises(ValueError, match="only 2 rows"):
        parse_imdb_ratings(blob, min_rows=3)
    assert parse_imdb_ratings(blob) == {"tt0000002": (8.3, 12)}


def test_apply_imdb_ratings_replaces_letterboxd_score_and_preserves_other_fields():
    movies = [
        {
            "id": "matched",
            "title": "Matched",
            "year": 2020,
            "imdb_id": "tt0000002",
            "rating": 3.91,
            "rating_count": 12345,
            "poster": "poster.jpg",
            "watch_history": [{"id": "watch-1", "watched_on": "2026-07-25"}],
        },
        {
            "id": "unrated",
            "title": "Unrated",
            "year": 2027,
            "imdb_id": "tt0000003",
            "rating": 4.42,
            "rating_count": 99,
        },
    ]
    before = deepcopy(movies)

    summary = apply_imdb_ratings(movies, {"tt0000002": (8.3, 987654)})

    assert summary == {"movies": 2, "imdb_ids": 2, "rated": 1, "unrated": 1}
    assert movies[0]["rating"] == 8.3
    assert movies[0]["rating_count"] == 987654
    assert movies[0]["rating_source"] == "imdb"
    assert movies[0]["imdb_url"] == "https://www.imdb.com/title/tt0000002/"
    assert movies[0]["poster"] == before[0]["poster"]
    assert movies[0]["watch_history"] == before[0]["watch_history"]
    assert "rating" not in movies[1]
    assert "rating_count" not in movies[1]
    assert "rating_source" not in movies[1]
    assert movies[1]["imdb_url"] == "https://www.imdb.com/title/tt0000003/"


def test_apply_imdb_ratings_clears_unmatched_legacy_score():
    movies = [{"id": "legacy", "title": "Legacy", "rating": 4.8, "rating_count": 1000}]

    summary = apply_imdb_ratings(movies, {})

    assert summary == {"movies": 1, "imdb_ids": 0, "rated": 0, "unrated": 1}
    assert movies == [{"id": "legacy", "title": "Legacy"}]


def test_verify_only_score_fields_changed_accepts_new_identity_and_score():
    before = [{"id": "film", "title": "Film", "watch_history": [{"watched_on": "2026-07-25"}]}]
    after = [{**before[0], "imdb_id": "tt1234567", "imdb_url": "https://www.imdb.com/title/tt1234567/", "rating": 8.1, "rating_count": 42, "rating_source": "imdb"}]

    verify_only_score_fields_changed(before, after)


@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        ([{"id": "a"}], [{"id": "a"}, {"id": "b"}], "movie count changed"),
        ([{"id": "a"}, {"id": "b"}], [{"id": "b"}, {"id": "a"}], "movie order/id changed"),
        ([{"id": "a", "queued": True}], [{"id": "a", "queued": False}], "non-score fields changed"),
        ([{"id": "a", "imdb_id": "tt1234567"}], [{"id": "a", "imdb_id": "tt7654321"}], "existing IMDb ID changed"),
    ],
)
def test_verify_only_score_fields_changed_rejects_data_drift(before, after, message):
    with pytest.raises(ValueError, match=message):
        verify_only_score_fields_changed(before, after)