from __future__ import annotations

import html
import json
import re
from typing import Any

from cinequeue.imdb_ratings import RATING_KEYS, extract_imdb_id, imdb_url, normalize_imdb_id

JSONLD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
SYNOPSIS_RE = re.compile(r'<section class="production-synopsis">.*?<div class="truncate"[^>]*>\s*<p>(.*?)</p>', re.S)
TRAILER_RE = re.compile(r'href="(?:https?:)?//www\.youtube\.com/embed/([^"?&]+)[^"]*"')
RUNTIME_FOOTER_RE = re.compile(r'<p[^>]*class="[^"]*text-link[^"]*text-footer[^"]*"[^>]*>(.*?)</p>', re.S | re.I)
RUNTIME_TEXT_RE = re.compile(r'^([0-9]{1,4}) +mins', re.I)
TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(value: str) -> str:
    value = TAG_RE.sub(" ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _as_people_names(value: Any, limit: int | None = None) -> list[str]:
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]).strip())
        elif isinstance(item, str):
            names.append(item.strip())
    names = [name for name in names if name]
    return names[:limit] if limit else names


def _jsonld_payload(source: str) -> dict[str, Any]:
    match = JSONLD_RE.search(source)
    if not match:
        return {}
    text = html.unescape(match.group(1)).strip()
    text = re.sub(r"^/\*\s*<!\[CDATA\[\s*\*/\s*", "", text)
    text = re.sub(r"/\*\s*\]\]>\s*\*/\s*$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def parse_letterboxd_details(source: str, cast_limit: int = 3) -> dict[str, Any]:
    data = _jsonld_payload(source)
    synopsis = ""
    synopsis_match = SYNOPSIS_RE.search(source)
    if synopsis_match:
        synopsis = _clean_text(synopsis_match.group(1))
    elif data.get("description"):
        synopsis = _clean_text(str(data["description"]))

    trailer_url = ""
    trailer_match = TRAILER_RE.search(source)
    if trailer_match:
        trailer_url = f"https://www.youtube.com/watch?v={trailer_match.group(1)}"

    imdb_id = extract_imdb_id(source)

    genres = data.get("genre") or []
    if isinstance(genres, str):
        genres = [genres]

    runtime_minutes = None
    runtime_footer = RUNTIME_FOOTER_RE.search(source)
    runtime_text = _clean_text(runtime_footer.group(1)) if runtime_footer else ""
    runtime_match = RUNTIME_TEXT_RE.search(runtime_text)
    if runtime_match:
        try:
            runtime_minutes = int(runtime_match.group(1))
        except (TypeError, ValueError):
            runtime_minutes = None

    return {
        "description": synopsis,
        "genres": [str(g).strip() for g in genres if str(g).strip()],
        "directors": _as_people_names(data.get("director")),
        "cast": _as_people_names(data.get("actors"), limit=cast_limit),
        "trailer_url": trailer_url,
        "imdb_id": imdb_id,
        "imdb_url": imdb_url(imdb_id) if imdb_id else "",
        "runtime_minutes": runtime_minutes,
        "poster": data.get("image") or "",
    }


def merge_letterboxd_details(movie: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    """Merge metadata while preventing an IMDb identity/score mismatch."""
    old_imdb_id = normalize_imdb_id(movie.get("imdb_id"))
    new_imdb_id = normalize_imdb_id(details.get("imdb_id"))
    if new_imdb_id and new_imdb_id != old_imdb_id:
        for key in RATING_KEYS:
            movie.pop(key, None)
    for key, value in details.items():
        if value in (None, "", []):
            continue
        if key == "poster" and movie.get("poster"):
            continue
        movie[key] = value
    return movie
