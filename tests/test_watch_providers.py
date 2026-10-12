import datetime as dt

from cinequeue.watch_providers import WatchProviderService


def justwatch_response():
    return {
        "data": {
            "popularTitles": {
                "edges": [
                    {
                        "node": {
                            "id": "tm-wrong",
                            "objectType": "MOVIE",
                            "content": {
                                "title": "Talk to Me",
                                "originalReleaseYear": 1984,
                                "fullPath": "/th/movie/talk-to-me-1984",
                                "externalIds": {"imdbId": "tt0088242"},
                            },
                            "offers": [],
                        }
                    },
                    {
                        "node": {
                            "id": "tm-right",
                            "objectType": "MOVIE",
                            "content": {
                                "title": "Talk to Me",
                                "originalReleaseYear": 2023,
                                "fullPath": "/th/movie/talk-to-me-2022",
                                "externalIds": {"imdbId": "tt10638522"},
                            },
                            "offers": [
                                {
                                    "monetizationType": "FLATRATE",
                                    "presentationType": "SD",
                                    "standardWebURL": "https://www.netflix.com/title/81700507",
                                    "package": {"packageId": 8, "clearName": "Netflix"},
                                },
                                {
                                    "monetizationType": "FLATRATE",
                                    "presentationType": "HD",
                                    "standardWebURL": "https://www.netflix.com/title/81700507",
                                    "package": {"packageId": 8, "clearName": "Netflix"},
                                },
                                {
                                    "monetizationType": "RENT",
                                    "presentationType": "HD",
                                    "standardWebURL": "https://tv.apple.com/th/movie/talk-to-me",
                                    "package": {"packageId": 2, "clearName": "Apple TV Store"},
                                },
                                {
                                    "monetizationType": "BUY",
                                    "presentationType": "HD",
                                    "standardWebURL": "javascript:alert(1)",
                                    "package": {"packageId": 2, "clearName": "Apple TV Store"},
                                },
                            ],
                        }
                    },
                ]
            }
        }
    }


def test_exact_imdb_match_and_thailand_offer_groups(tmp_path):
    requests = []

    def fetcher(title, region):
        requests.append((title, region))
        return justwatch_response()

    service = WatchProviderService(
        cache_path=tmp_path / "watch-providers.json",
        fetcher=fetcher,
        now=lambda: dt.datetime(2026, 9, 4, 12, 0, tzinfo=dt.timezone.utc),
    )
    result = service.lookup(
        {"id": "talk-to-me-2022", "title": "Talk to Me", "year": 2022, "imdb_id": "tt10638522"}
    )

    assert requests == [("Talk to Me", "TH")]
    assert result["region"] == "TH"
    assert result["region_name"] == "Thailand"
    assert result["matched"]["justwatch_id"] == "tm-right"
    assert result["source"] == {
        "name": "JustWatch",
        "url": "https://www.justwatch.com/th/movie/talk-to-me-2022",
    }
    assert result["groups"] == [
        {
            "key": "stream",
            "label": "Stream",
            "services": [
                {"name": "Netflix", "url": "https://www.netflix.com/title/81700507"}
            ],
        },
        {
            "key": "rent",
            "label": "Rent",
            "services": [
                {"name": "Apple TV Store", "url": "https://tv.apple.com/th/movie/talk-to-me"}
            ],
        },
        {
            "key": "buy",
            "label": "Buy",
            "services": [
                {"name": "Apple TV Store", "url": "https://www.justwatch.com/th/movie/talk-to-me-2022"}
            ],
        },
    ]


def test_lookup_uses_fresh_cache(tmp_path):
    calls = 0

    def fetcher(title, region):
        nonlocal calls
        calls += 1
        return justwatch_response()

    clock = dt.datetime(2026, 9, 4, 12, 0, tzinfo=dt.timezone.utc)
    service = WatchProviderService(
        cache_path=tmp_path / "watch-providers.json",
        fetcher=fetcher,
        now=lambda: clock,
    )
    movie = {"id": "talk-to-me-2022", "title": "Talk to Me", "year": 2022, "imdb_id": "tt10638522"}

    first = service.lookup(movie)
    second = service.lookup(movie)

    assert calls == 1
    assert first["groups"] == second["groups"]
    assert second["cached"] is True


def test_unmatched_title_still_returns_thailand_section_and_search_link(tmp_path):
    service = WatchProviderService(
        cache_path=tmp_path / "watch-providers.json",
        fetcher=lambda title, region: {"data": {"popularTitles": {"edges": []}}},
        now=lambda: dt.datetime(2026, 9, 4, 12, 0, tzinfo=dt.timezone.utc),
    )

    result = service.lookup({"id": "future-film", "title": "Future Film", "year": 2028})

    assert result["available"] is False
    assert result["availability_known"] is False
    assert result["region_name"] == "Thailand"
    assert result["groups"] == []
    assert result["source"]["name"] == "JustWatch"
    assert result["source"]["url"].startswith("https://www.justwatch.com/th/search?")
