"""Managed-app contracts: health, config, MCP tools, origin guard, fresh install. Synthetic data only."""
from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import cinequeue.server as server
from cinequeue import mcp_api


@pytest.fixture()
def app(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "DATA", tmp_path / "movies.json")
    monkeypatch.setattr(server, "ADD_REQUESTS", tmp_path / "add_requests.json")
    monkeypatch.setattr(server, "BASE_PATH", "")
    monkeypatch.setattr(server, "ADMIT", "disabled")
    monkeypatch.setattr(server, "WIZARD_ORIGIN", "")
    monkeypatch.setenv("CINEQUEUE_WATCH_REGION", "")
    handler = lambda *a, **k: server.CineQueueHandler(*a, directory=str(server.STATIC), **k)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", tmp_path
    httpd.shutdown()


def get(url):
    with urlopen(url) as res:
        return res.status, json.loads(res.read())


def post(url, body=None, headers=None):
    data = json.dumps(body if body is not None else {}).encode()
    req = Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(req) as res:
            raw = res.read()
            return res.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def mcp(base, method, params=None, key=1):
    status, body = post(f"{base}/mcp", {"jsonrpc": "2.0", "id": key, "method": method, "params": params or {}})
    assert status == 200
    return body


def tool(base, name, **args):
    body = mcp(base, "tools/call", {"name": name, "arguments": args})
    result = body["result"]
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


def test_fresh_install_is_empty_healthy_and_honest(app):
    base, data = app
    assert get(f"{base}/healthz") == (200, {"ok": True, "version": server.VERSION, "movies": 0})
    assert get(f"{base}/api/movies")[1] == {"movies": []}
    status, config = get(f"{base}/api/config")
    assert config["agent"]["ready"] is False and config["watch"]["enabled"] is False
    assert (data / "movies.json").read_text() == "[]"
    status, body = post(f"{base}/api/request-add", {"text": "Heat 1995"})
    assert status == 503 and body["request"]["status"] == "not_sent"
    with urlopen(f"{base}/") as res:
        assert b"CineQueue" in res.read()


def test_mcp_lists_tools_and_drives_the_full_queue_lifecycle(app):
    base, _ = app
    assert mcp(base, "initialize")["result"]["serverInfo"] == {"name": "cinequeue", "version": server.VERSION}
    names = {t["name"] for t in mcp(base, "tools/list")["result"]["tools"]}
    assert {"cinequeue_list", "cinequeue_add", "cinequeue_mark_watched", "cinequeue_bump", "cinequeue_history",
            "cinequeue_watch_again", "cinequeue_update", "cinequeue_get"} <= names

    added = tool(base, "cinequeue_add", text="Stalker 1979, Heat 1995")
    assert added["count"] == 2
    queue = tool(base, "cinequeue_list")["movies"]
    heat = next(m for m in queue if m["title"] == "Heat")
    stalker = next(m for m in queue if m["title"] == "Stalker")
    tool(base, "cinequeue_bump", id=stalker["id"])
    assert tool(base, "cinequeue_list")["movies"][0]["id"] == stalker["id"]

    updated = tool(base, "cinequeue_update", id=heat["id"], fields={"runtime_minutes": 170, "notes": "Big screen."})
    assert updated["movie"]["runtime_minutes"] == 170

    tool(base, "cinequeue_mark_watched", id=stalker["id"], watched_on="2026-10-01")
    assert [m["id"] for m in tool(base, "cinequeue_list")["movies"]] == [heat["id"]]
    history = tool(base, "cinequeue_history")["history"]
    assert history[0]["movie_id"] == stalker["id"] and history[0]["watched_on"] == "2026-10-01"
    tool(base, "cinequeue_watch_again", id=stalker["id"])
    got = tool(base, "cinequeue_get", id=stalker["id"])["movie"]
    assert got["queued"] is True and got["watch_count"] == 1 and got["queue_position"] == 1

    request = tool(base, "cinequeue_request", text="that Tarkovsky space one")
    assert request["sent"] is False and request["saved"] is True


def test_mcp_rejects_bad_tools_arguments_and_fields(app):
    base, _ = app
    assert mcp(base, "tools/call", {"name": "nope", "arguments": {}})["result"]["isError"] is True
    assert mcp(base, "tools/call", {"name": "cinequeue_bump", "arguments": {}})["result"]["isError"] is True
    added = tool(base, "cinequeue_add", title="Heat", year=1995)
    movie_id = added["added"][0]["id"]
    bad = mcp(base, "tools/call", {"name": "cinequeue_update", "arguments": {"id": movie_id, "fields": {"watch_history": []}}})
    assert bad["result"]["isError"] is True
    assert mcp(base, "nope")["error"]["code"] == -32601
    status, _ = post(f"{base}/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert status == 202


def test_cross_site_browser_writes_are_refused(app):
    base, _ = app
    status, body = post(f"{base}/api/add", {"text": "Heat"}, {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert status == 403
    req = Request(f"{base}/api/add", data=b"text=Heat", method="POST",
                  headers={"Content-Type": "text/plain", "Origin": base})
    with pytest.raises(HTTPError) as exc:
        urlopen(req)
    assert exc.value.code == 415
    status, body = post(f"{base}/api/add", {"text": "Heat"}, {"Origin": base})
    assert status == 200 and body["count"] == 1
    assert get(f"{base}/api/movies")[1]["movies"][0]["title"] == "Heat"


def test_dns_rebinding_hosts_are_refused_for_reads_and_writes(app, monkeypatch):
    base, _ = app
    port = base.rsplit(":", 1)[1]
    for path in ("/api/movies", "/", "/api/config"):
        req = Request(f"{base}{path}", headers={"Host": f"evil.example:{port}"})
        with pytest.raises(HTTPError) as exc:
            urlopen(req)
        assert exc.value.code == 421, path
    status, _ = post(f"{base}/api/add", {"text": "Heat"}, {"Host": f"evil.example:{port}", "Origin": f"http://evil.example:{port}"})
    assert status == 403
    status, _ = post(f"{base}/api/add", {"text": "Heat"}, {"Host": "127.0.0.1:9234", "Origin": "http://127.0.0.1:8080"})
    assert status == 403
    # The agent at the App Manager's host-published port, and the configured Wizard origin, still work.
    assert post(f"{base}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {"Host": "127.0.0.1:9234"})[0] == 200
    monkeypatch.setattr(server, "ORIGINS", {"https://wizard.example.ts.net"})
    monkeypatch.setattr(server, "ORIGIN_HOSTS", {"wizard.example.ts.net"})
    req = Request(f"{base}/api/movies", headers={"Host": "wizard.example.ts.net"})
    with urlopen(req) as res:
        assert res.status == 200
    status, _ = post(f"{base}/api/add", {"text": "Heat"}, {"Host": "wizard.example.ts.net", "Origin": "https://wizard.example.ts.net"})
    assert status == 200


def test_store_writes_hold_an_advisory_lock_file(app):
    base, data = app
    post(f"{base}/api/add", {"text": "Heat"})
    assert (data / "movies.json.lock").exists()
    assert not list(data.glob("*.tmp"))


def test_mcp_module_is_the_single_tool_catalog():
    assert len({t["name"] for t in mcp_api.TOOLS}) == len(mcp_api.TOOLS)
