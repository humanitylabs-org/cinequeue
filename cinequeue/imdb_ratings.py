from __future__ import annotations

import csv
import gzip
import io
import re
from pathlib import Path
from typing import Iterable

IMDB_ID_RE = re.compile(r"^tt\d{7,10}$", re.I)
IMDB_URL_RE = re.compile(r"(?:https?:)?//(?:www\.)?imdb\.com/title/(tt\d{7,10})(?:[/\"'?#]|$)", re.I)
RATING_KEYS = ("rating", "rating_count", "rating_source")


def normalize_imdb_id(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if IMDB_ID_RE.fullmatch(text) else ""


def extract_imdb_id(source: str) -> str:
    matches = {normalize_imdb_id(match) for match in IMDB_URL_RE.findall(source or "")}
    matches.discard("")
    return next(iter(matches)) if len(matches) == 1 else ""


def imdb_url(imdb_id: str) -> str:
    return f"https://www.imdb.com/title/{imdb_id}/"


def parse_imdb_ratings_with_count(
    blob: bytes,
    *,
    wanted_ids: set[str] | None = None,
    min_rows: int = 0,
) -> tuple[dict[str, tuple[float, int]], int]:
    wanted = {normalize_imdb_id(item) for item in wanted_ids} if wanted_ids is not None else None
    if wanted is not None:
        wanted.discard("")
    ratings: dict[str, tuple[float, int]] = {}
    row_count = 0
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as compressed:
        stream = io.TextIOWrapper(compressed, encoding="utf-8", newline="")
        for row in csv.DictReader(stream, delimiter="\t"):
            row_count += 1
            title_id = normalize_imdb_id(row.get("tconst"))
            if not title_id or (wanted is not None and title_id not in wanted):
                continue
            try:
                average = float(row["averageRating"])
                votes = int(row["numVotes"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 < average <= 10 and votes > 0:
                ratings[title_id] = (average, votes)
    if row_count < min_rows:
        raise ValueError(f"IMDb ratings dataset has only {row_count} rows; expected at least {min_rows}")
    return ratings, row_count


def parse_imdb_ratings(
    blob: bytes, *, wanted_ids: set[str] | None = None, min_rows: int = 0
) -> dict[str, tuple[float, int]]:
    ratings, _row_count = parse_imdb_ratings_with_count(
        blob, wanted_ids=wanted_ids, min_rows=min_rows
    )
    return ratings


def read_imdb_ratings_with_count(
    path: Path, *, wanted_ids: set[str] | None = None, min_rows: int = 0
) -> tuple[dict[str, tuple[float, int]], int]:
    return parse_imdb_ratings_with_count(
        path.read_bytes(), wanted_ids=wanted_ids, min_rows=min_rows
    )


def read_imdb_ratings(
    path: Path, *, wanted_ids: set[str] | None = None, min_rows: int = 0
) -> dict[str, tuple[float, int]]:
    ratings, _row_count = read_imdb_ratings_with_count(
        path, wanted_ids=wanted_ids, min_rows=min_rows
    )
    return ratings


def apply_imdb_ratings(
    movies: list[dict], ratings: dict[str, tuple[float, int]]
) -> dict[str, int]:
    rated = 0
    with_ids = 0
    for movie in movies:
        for key in RATING_KEYS:
            movie.pop(key, None)

        title_id = normalize_imdb_id(movie.get("imdb_id"))
        if not title_id:
            title_id = extract_imdb_id(str(movie.get("imdb_url") or ""))
        if not title_id:
            movie.pop("imdb_id", None)
            movie.pop("imdb_url", None)
            continue

        with_ids += 1
        movie["imdb_id"] = title_id
        movie["imdb_url"] = imdb_url(title_id)
        score = ratings.get(title_id)
        if score is None:
            continue
        movie["rating"], movie["rating_count"] = score
        movie["rating_source"] = "imdb"
        rated += 1

    return {
        "movies": len(movies),
        "imdb_ids": with_ids,
        "rated": rated,
        "unrated": len(movies) - rated,
    }


def verify_only_score_fields_changed(before: Iterable[dict], after: Iterable[dict]) -> None:
    allowed = {*RATING_KEYS, "imdb_id", "imdb_url"}
    before_rows = list(before)
    after_rows = list(after)
    if len(before_rows) != len(after_rows):
        raise ValueError("movie count changed during IMDb enrichment")
    for index, (old, new) in enumerate(zip(before_rows, after_rows, strict=True)):
        if old.get("id") != new.get("id"):
            raise ValueError(f"movie order/id changed at index {index}")
        old_imdb_id = normalize_imdb_id(old.get("imdb_id"))
        new_imdb_id = normalize_imdb_id(new.get("imdb_id"))
        if old_imdb_id and old_imdb_id != new_imdb_id:
            raise ValueError(f"existing IMDb ID changed for {old.get('id') or index}")
        old_stable = {key: value for key, value in old.items() if key not in allowed}
        new_stable = {key: value for key, value in new.items() if key not in allowed}
        if old_stable != new_stable:
            raise ValueError(f"non-score fields changed for {old.get('id') or index}")
