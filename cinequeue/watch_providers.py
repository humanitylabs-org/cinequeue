from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import threading
import unicodedata
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

JUSTWATCH_ENDPOINT = "https://apis.justwatch.com/graphql"
JUSTWATCH_ROOT = "https://www.justwatch.com"
DEFAULT_REGION = "TH"
REGION_NAMES = {
    "TH": "Thailand", "US": "the United States", "GB": "the United Kingdom", "AU": "Australia",
    "CA": "Canada", "DE": "Germany", "FR": "France", "NZ": "New Zealand", "IE": "Ireland",
    "SG": "Singapore", "JP": "Japan", "IN": "India", "ES": "Spain", "IT": "Italy", "NL": "the Netherlands",
}
REGION_RE = re.compile(r"^[A-Z]{2}$")
CACHE_TTL = dt.timedelta(hours=24)
IMDB_ID_RE = re.compile(r"^tt\d{7,10}$")

JUSTWATCH_QUERY = """
query CineQueueWatchProviders(
  $country: Country!
  $language: Language!
  $first: Int!
  $filter: TitleFilter!
) {
  popularTitles(country: $country, first: $first, filter: $filter) {
    edges {
      node {
        id
        objectType
        content(country: $country, language: $language) {
          title
          fullPath
          originalReleaseYear
          externalIds { imdbId }
        }
        offers(country: $country, platform: WEB) {
          monetizationType
          presentationType
          standardWebURL
          package { packageId clearName }
        }
      }
    }
  }
}
""".strip()

GROUPS = (
    ("FLATRATE", "stream", "Stream"),
    ("FREE", "free", "Free"),
    ("ADS", "ads", "Free with ads"),
    ("RENT", "rent", "Rent"),
    ("BUY", "buy", "Buy"),
)


class WatchProviderError(RuntimeError):
    pass


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def configured_region() -> str:
    """Watch region from CINEQUEUE_WATCH_REGION; empty/off disables third-party availability lookups.

    Unset keeps the original single-owner default (TH); packaged installs pass the install-form value.
    """
    raw = os.environ.get("CINEQUEUE_WATCH_REGION")
    region = (DEFAULT_REGION if raw is None else raw).strip().upper()
    return region if REGION_RE.fullmatch(region) else ""


def region_name(region: str) -> str:
    return REGION_NAMES.get(region, region)


def _default_cache_path() -> Path:
    if os.environ.get("CINEQUEUE_WATCH_CACHE"):
        return Path(os.environ["CINEQUEUE_WATCH_CACHE"])
    if os.environ.get("CINEQUEUE_DATA"):
        return Path(os.environ["CINEQUEUE_DATA"]) / "watch-providers.json"
    return Path(__file__).resolve().parents[1] / "data" / "watch-providers.json"


def _normalize_title(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())


def _normalize_imdb_id(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if IMDB_ID_RE.fullmatch(text) else ""


def _safe_https_url(value: object) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    return text if parsed.scheme == "https" and parsed.netloc else ""


def _justwatch_search_url(title: str, region: str) -> str:
    country = region.lower()
    return f"{JUSTWATCH_ROOT}/{quote(country)}/search?{urlencode({'q': title})}"


def fetch_justwatch(title: str, region: str) -> dict:
    payload = json.dumps(
        {
            "query": JUSTWATCH_QUERY,
            "variables": {
                "country": region,
                "language": "en",
                "first": 10,
                "filter": {"searchQuery": title},
            },
        }
    ).encode("utf-8")
    request = Request(
        JUSTWATCH_ENDPOINT,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 CineQueue/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=12) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise WatchProviderError("JustWatch request failed") from exc
    if result.get("errors") or not isinstance(result.get("data"), dict):
        raise WatchProviderError("JustWatch returned an invalid response")
    return result


def _nodes(response: dict) -> list[dict]:
    edges = (((response.get("data") or {}).get("popularTitles") or {}).get("edges") or [])
    return [edge.get("node") for edge in edges if isinstance(edge, dict) and isinstance(edge.get("node"), dict)]


def _expected_object_type(movie: dict) -> str:
    media_type = str(movie.get("media_type") or "").strip().lower()
    return "SHOW" if media_type in {"series", "show", "tv", "tv_series"} else "MOVIE"


def select_match(movie: dict, response: dict) -> dict | None:
    candidates = _nodes(response)
    wanted_imdb = _normalize_imdb_id(movie.get("imdb_id"))
    if wanted_imdb:
        for node in candidates:
            content = node.get("content") or {}
            external_ids = content.get("externalIds") or {}
            if _normalize_imdb_id(external_ids.get("imdbId")) == wanted_imdb:
                return node
        return None

    wanted_title = _normalize_title(movie.get("title"))
    expected_type = _expected_object_type(movie)
    wanted_year = movie.get("year") if isinstance(movie.get("year"), int) else None
    scored: list[tuple[int, int, dict]] = []
    for index, node in enumerate(candidates):
        content = node.get("content") or {}
        if _normalize_title(content.get("title")) != wanted_title:
            continue
        if str(node.get("objectType") or "") != expected_type:
            continue
        candidate_year = content.get("originalReleaseYear")
        year_score = 0
        if wanted_year and isinstance(candidate_year, int):
            difference = abs(wanted_year - candidate_year)
            if difference > 1:
                continue
            year_score = 2 - difference
        scored.append((year_score, -index, node))
    return max(scored, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]


def _source_url(node: dict | None, title: str, region: str) -> str:
    full_path = str(((node or {}).get("content") or {}).get("fullPath") or "")
    if full_path.startswith("/"):
        return f"{JUSTWATCH_ROOT}{full_path}"
    return _justwatch_search_url(title, region)


def present_result(movie: dict, node: dict | None, region: str, fetched_at: str) -> dict:
    title = str(movie.get("title") or "").strip()
    source_url = _source_url(node, title, region)
    services_by_group: dict[str, list[dict]] = {key: [] for _, key, _ in GROUPS}
    seen: dict[str, set[tuple[object, str]]] = {key: set() for _, key, _ in GROUPS}
    group_lookup = {raw: key for raw, key, _ in GROUPS}

    for offer in (node or {}).get("offers") or []:
        if not isinstance(offer, dict):
            continue
        group_key = group_lookup.get(str(offer.get("monetizationType") or "").upper())
        package = offer.get("package") or {}
        name = str(package.get("clearName") or "").strip()
        if not group_key or not name:
            continue
        identity = (package.get("packageId"), name.casefold())
        if identity in seen[group_key]:
            continue
        seen[group_key].add(identity)
        services_by_group[group_key].append(
            {
                "name": name,
                "url": _safe_https_url(offer.get("standardWebURL")) or source_url,
            }
        )

    groups = [
        {"key": key, "label": label, "services": services_by_group[key]}
        for _, key, label in GROUPS
        if services_by_group[key]
    ]
    content = (node or {}).get("content") or {}
    return {
        "movie_id": str(movie.get("id") or ""),
        "region": region,
        "region_name": region_name(region),
        "available": bool(groups),
        "availability_known": node is not None,
        "groups": groups,
        "matched": {
            "justwatch_id": str((node or {}).get("id") or ""),
            "title": str(content.get("title") or ""),
            "year": content.get("originalReleaseYear"),
        }
        if node
        else None,
        "source": {"name": "JustWatch", "url": source_url},
        "fetched_at": fetched_at,
        "cached": False,
        "stale": False,
    }


class WatchProviderService:
    def __init__(
        self,
        *,
        cache_path: Path | str | None = None,
        fetcher: Callable[[str, str], dict] = fetch_justwatch,
        now: Callable[[], dt.datetime] = _utc_now,
        ttl: dt.timedelta = CACHE_TTL,
    ) -> None:
        self.cache_path = Path(cache_path) if cache_path is not None else _default_cache_path()
        self.fetcher = fetcher
        self.now = now
        self.ttl = ttl
        self._lock = threading.Lock()

    def _load_cache(self) -> dict:
        if not self.cache_path.exists():
            return {"version": 1, "entries": {}}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "entries": {}}
        if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
            return {"version": 1, "entries": {}}
        return data

    def _save_cache(self, data: dict) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.cache_path)

    def _cached_payload(self, entry: dict, now: dt.datetime) -> tuple[dict | None, bool]:
        payload = entry.get("payload")
        try:
            fetched_at = dt.datetime.fromisoformat(str(entry.get("fetched_at") or ""))
        except ValueError:
            return None, False
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=dt.timezone.utc)
        if not isinstance(payload, dict):
            return None, False
        return copy.deepcopy(payload), now - fetched_at <= self.ttl

    def lookup(self, movie: dict, region: str = DEFAULT_REGION) -> dict:
        region = str(region or DEFAULT_REGION).strip().upper()
        if not REGION_RE.fullmatch(region):
            raise ValueError(f"unsupported watch region: {region}")
        title = str(movie.get("title") or "").strip()
        movie_id = str(movie.get("id") or "").strip()
        if not title or not movie_id:
            raise ValueError("movie id and title are required")

        now = self.now().astimezone(dt.timezone.utc)
        cache_key = f"{region}:{movie_id}"
        with self._lock:
            cache = self._load_cache()
            stale_payload, is_fresh = self._cached_payload(cache.get("entries", {}).get(cache_key, {}), now)
        if stale_payload is not None and is_fresh:
            stale_payload["cached"] = True
            stale_payload["stale"] = False
            return stale_payload

        try:
            response = self.fetcher(title, region)
            node = select_match(movie, response)
            fetched_at = now.isoformat()
            payload = present_result(movie, node, region, fetched_at)
        except Exception as exc:
            if stale_payload is not None:
                stale_payload["cached"] = True
                stale_payload["stale"] = True
                return stale_payload
            if isinstance(exc, WatchProviderError):
                raise
            raise WatchProviderError("Watch availability lookup failed") from exc

        with self._lock:
            cache = self._load_cache()
            cache.setdefault("entries", {})[cache_key] = {
                "fetched_at": fetched_at,
                "payload": payload,
            }
            self._save_cache(cache)
        return payload
