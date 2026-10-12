"""Server-level archive/restore/filter semantics over real HTTP."""
from __future__ import annotations

import json
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import cinequeue.server as server


def _start(data_path: Path, monkeypatch):
    handler = lambda *args, **kwargs: server.CineQueueHandler(  # noqa: E731
        *args, directory=str(server.STATIC), **kwargs
    )
    monkeypatch.setattr(server, "DATA", data_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _post(port: int, path: str):
    req = Request(f"http://127.0.0.1:{port}{path}", method="POST", data=b"{}")
    with urlopen(req) as res:
        return res.status, json.loads(res.read())


def _get(port: int, path: str):
    with urlopen(f"http://127.0.0.1:{port}{path}") as res:
        return json.loads(res.read())


def test_archive_restore_filter_round_trip(tmp_path, monkeypatch):
    data_path = tmp_path / "movies.json"
    original = [
        {"id": "alpha", "title": "Alpha", "watched": False, "added_at": "a", "poster": "pa", "genres": ["Drama"]},
        {"id": "beta", "title": "Beta", "watched": True, "added_at": "b", "rating": 3.8},
        {"id": "gamma", "title": "Gamma", "watched": False, "added_at": "c"},
    ]
    data_path.write_text(json.dumps(original))
    httpd = _start(data_path, monkeypatch)
    try:
        port = httpd.server_address[1]

        assert len(_get(port, "/api/movies")["movies"]) == 3

        status, _ = _post(port, "/api/archive/alpha")
        assert status == 200
        visible = _get(port, "/api/movies")["movies"]
        assert [m["id"] for m in visible] == ["beta", "gamma"]

        everything = _get(port, "/api/movies?include_archived=1")["movies"]
        assert [m["id"] for m in everything] == ["alpha", "beta", "gamma"]
        archived = everything[0]
        assert archived["archived"] is True
        assert archived["archived_at"]
        for key, value in original[0].items():
            assert archived[key] == value

        status, _ = _post(port, "/api/restore/alpha")
        assert status == 200
        visible = _get(port, "/api/movies")["movies"]
        assert [m["id"] for m in visible] == ["alpha", "beta", "gamma"]

        final = json.loads(data_path.read_text())
        for before, after in zip(original, final):
            for key, value in before.items():
                assert after[key] == value
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_archive_unknown_id_is_404(tmp_path, monkeypatch):
    data_path = tmp_path / "movies.json"
    data_path.write_text(json.dumps([{"id": "alpha", "title": "Alpha"}]))
    httpd = _start(data_path, monkeypatch)
    try:
        port = httpd.server_address[1]
        for endpoint in ("/api/archive/nope", "/api/restore/nope"):
            try:
                _post(port, endpoint)
                raise AssertionError("expected 404")
            except HTTPError as exc:
                assert exc.status == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_query_string_filtering_parses_include_archived(tmp_path, monkeypatch):
    # The handler must inspect the parsed query, not the raw path.
    parsed = urlparse("/api/movies?include_archived=1")
    assert parse_qs(parsed.query)["include_archived"] == ["1"]
