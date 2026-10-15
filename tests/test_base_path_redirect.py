"""Focused test: slashless base path must redirect to trailing slash."""
from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

import cinequeue.server as server

ROOT = Path(__file__).resolve().parents[1]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _start_server():
    handler = lambda *args, **kwargs: server.CineQueueHandler(  # noqa: E731
        *args, directory=str(server.STATIC), **kwargs
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def test_slashless_base_path_redirects_to_trailing_slash(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DATA", tmp_path / "movies.json")
    monkeypatch.setattr(server, "BASE_PATH", "/cinequeue-kimi")
    httpd = _start_server()
    try:
        port = httpd.server_address[1]
        opener = build_opener(_NoRedirect())

        # Slashless exact base path -> 301 to trailing slash.
        req = Request(f"http://127.0.0.1:{port}/cinequeue-kimi")
        try:
            opener.open(req)
            raise AssertionError("expected redirect")
        except HTTPError as exc:
            assert exc.status == 301
            assert exc.headers["Location"] == "/cinequeue-kimi/"

        # Trailing-slash home serves the app.
        with opener.open(f"http://127.0.0.1:{port}/cinequeue-kimi/") as res:
            assert res.status == 200
            assert b"Movies" in res.read()

        # API works under the prefix.
        with opener.open(f"http://127.0.0.1:{port}/cinequeue-kimi/api/movies") as res:
            assert res.status == 200
            assert b'"movies"' in res.read()

        # Static assets resolve under the prefix.
        with opener.open(f"http://127.0.0.1:{port}/cinequeue-kimi/app.js") as res:
            assert res.status == 200

        # Deep link serves the SPA shell.
        with opener.open(f"http://127.0.0.1:{port}/cinequeue-kimi/movie/some-id") as res:
            assert res.status == 200
            assert b"Movies" in res.read()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_root_mode_is_unchanged_by_redirect(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DATA", tmp_path / "movies.json")
    monkeypatch.setattr(server, "BASE_PATH", "")
    httpd = _start_server()
    try:
        port = httpd.server_address[1]
        with build_opener().open(f"http://127.0.0.1:{port}/") as res:
            assert res.status == 200
        with build_opener().open(f"http://127.0.0.1:{port}/api/movies") as res:
            assert res.status == 200
    finally:
        httpd.shutdown()
        httpd.server_close()
