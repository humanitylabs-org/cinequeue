from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cinequeue import server
from cinequeue.core import MovieStore, WatchStateConflict, normalize_watch_date


def _seed(path):
    records = [
        {"id": "alpha", "title": "Alpha", "watched": False, "added_at": "2026-01-01"},
        {"id": "legacy", "title": "Legacy", "watched": True, "watched_at": "2026-06-24T16:58:26+00:00"},
        {"id": "omega", "title": "Omega", "watched": False, "added_at": "2026-01-03"},
    ]
    path.write_text(json.dumps(records))
    return records


def test_legacy_watch_state_projects_without_rewriting_file(tmp_path):
    path = tmp_path / "movies.json"
    _seed(path)
    before = path.read_bytes()
    movies = MovieStore(path).all_projected()

    assert path.read_bytes() == before
    alpha = next(movie for movie in movies if movie["id"] == "alpha")
    legacy = next(movie for movie in movies if movie["id"] == "legacy")
    assert alpha["queued"] is True
    assert alpha["watched"] is False
    assert alpha["watch_history"] == []
    assert legacy["queued"] is False
    assert legacy["watched"] is True
    assert legacy["watch_history"][0]["watched_on"] == "2026-06-24"
    assert legacy["latest_watched_on"] == "2026-06-24"


def test_legacy_utc_timestamp_projects_to_the_configured_calendar_date(monkeypatch):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    import cinequeue.core as core

    try:
        bangkok = ZoneInfo("Asia/Bangkok")
    except ZoneInfoNotFoundError:
        import pytest

        pytest.skip("no IANA timezone database in this runtime")
    monkeypatch.setattr(core, "WATCH_TIMEZONE", bangkok)
    assert normalize_watch_date("2026-07-11T17:22:06+00:00") == "2026-07-12"
    assert normalize_watch_date("2026-07-11") == "2026-07-11"
    monkeypatch.setattr(core, "WATCH_TIMEZONE", core.timezone.utc)
    assert normalize_watch_date("2026-07-11T17:22:06+00:00") == "2026-07-11"


def test_watch_again_preserves_history_and_second_watch_accumulates(tmp_path):
    path = tmp_path / "movies.json"
    _seed(path)
    store = MovieStore(path)

    first = store.mark_watched("alpha", "2026-07-02")
    assert first["queued"] is False
    assert first["watched"] is True
    assert len(first["watch_history"]) == 1
    first_event_id = first["watch_history"][0]["id"]

    queued = store.queue_again("alpha")
    assert queued["queued"] is True
    assert queued["watch_history"] == first["watch_history"]
    assert store.all()[0]["id"] == "alpha"

    second = store.mark_watched("alpha", "2026-07-25")
    assert second["queued"] is False
    assert second["watched"] is True
    assert len(second["watch_history"]) == 2
    assert second["latest_watched_on"] == "2026-07-25"
    assert {event["watched_on"] for event in second["watch_history"]} == {"2026-07-02", "2026-07-25"}

    edited = store.edit_watch_date("alpha", first_event_id, "2026-06-30")
    assert {event["watched_on"] for event in edited["watch_history"]} == {"2026-06-30", "2026-07-25"}
    assert edited["latest_watched_on"] == "2026-07-25"


def test_watch_mutations_validate_dates_and_ids(tmp_path):
    path = tmp_path / "movies.json"
    _seed(path)
    store = MovieStore(path)

    with pytest.raises(ValueError):
        store.mark_watched("alpha", "25/07/2026")
    with pytest.raises(KeyError):
        store.mark_watched("missing", "2026-07-25")
    with pytest.raises(KeyError):
        store.edit_watch_date("legacy", "missing-event", "2026-07-25")


def test_watch_event_delete_recovers_queue_and_imported_duplicate_dates_get_unique_ids(tmp_path):
    path = tmp_path / "movies.json"
    path.write_text(json.dumps([{
        "id": "alpha", "title": "Alpha", "watched": True, "queued": False,
        "watch_history": ["2026-07-01", "2026-07-01"],
    }]))
    store = MovieStore(path)
    movie = store.get_projected("alpha")
    assert movie is not None
    event_ids = [event["id"] for event in movie["watch_history"]]
    assert len(set(event_ids)) == 2

    remaining = store.delete_watch_event("alpha", event_ids[0])
    assert remaining["watch_count"] == 1
    assert remaining["queued"] is False
    recovered = store.delete_watch_event("alpha", event_ids[1])
    assert recovered["watch_count"] == 0
    assert recovered["watched"] is False
    assert recovered["queued"] is True


def test_legacy_toggle_conflicts_instead_of_inventing_history(tmp_path):
    path = tmp_path / "movies.json"
    _seed(path)
    store = MovieStore(path)
    before = store.get_projected("legacy")
    with pytest.raises(WatchStateConflict):
        store.toggle_watched("legacy")
    assert store.get_projected("legacy") == before


def _start(data_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", data_path)
    handler = lambda *args, **kwargs: server.CineQueueHandler(*args, directory=str(server.STATIC), **kwargs)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _post(port, path, payload=None):
    body = json.dumps(payload or {}).encode()
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as response:
        return response.status, json.loads(response.read())


def _get(port, path):
    with urlopen(f"http://127.0.0.1:{port}{path}") as response:
        return json.loads(response.read())


def test_watch_history_http_lifecycle_and_legacy_toggle(tmp_path, monkeypatch):
    path = tmp_path / "movies.json"
    _seed(path)
    httpd = _start(path, monkeypatch)
    try:
        port = httpd.server_address[1]
        status, marked = _post(port, "/api/watch/alpha", {"watched_on": "2026-07-02"})
        assert status == 200
        assert marked["movie"]["queued"] is False
        event_id = marked["movie"]["watch_history"][0]["id"]

        status, queued = _post(port, "/api/watch-again/alpha")
        assert status == 200
        assert queued["movie"]["queued"] is True
        assert len(queued["movie"]["watch_history"]) == 1

        status, marked_again = _post(port, "/api/watch/alpha", {"watched_on": "2026-07-25"})
        assert status == 200
        assert marked_again["movie"]["queued"] is False
        assert len(marked_again["movie"]["watch_history"]) == 2

        status, edited = _post(port, f"/api/watch-date/alpha/{event_id}", {"watched_on": "2026-06-30"})
        assert status == 200
        assert {event["watched_on"] for event in edited["movie"]["watch_history"]} == {"2026-06-30", "2026-07-25"}

        status, removed = _post(port, f"/api/watch-delete/alpha/{event_id}")
        assert status == 200
        assert removed["movie"]["watch_count"] == 1

        # A stale shell cannot reinterpret "unwatch" as a history mutation.
        with pytest.raises(HTTPError) as error:
            _post(port, "/api/toggle/alpha")
        assert error.value.status == 409

        status, queued_again = _post(port, "/api/watch-again/alpha")
        assert status == 200
        assert queued_again["movie"]["queued"] is True
        assert len(queued_again["movie"]["watch_history"]) == 1

        projected = _get(port, "/api/movies")["movies"]
        alpha = next(movie for movie in projected if movie["id"] == "alpha")
        assert alpha["queued"] is True
        assert alpha["latest_watched_on"] == "2026-07-25"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_watch_history_http_rejects_bad_date(tmp_path, monkeypatch):
    path = tmp_path / "movies.json"
    _seed(path)
    httpd = _start(path, monkeypatch)
    try:
        port = httpd.server_address[1]
        with pytest.raises(HTTPError) as error:
            _post(port, "/api/watch/alpha", {"watched_on": "tomorrow-ish"})
        assert error.value.status == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
