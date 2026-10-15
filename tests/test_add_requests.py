import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cinequeue.server as server
from cinequeue.server import (
    AddRequestDispatchError,
    AdmissionError,
    build_cinequeue_add_prompt,
    dispatch_add_request,
    load_add_requests,
    queue_add_request,
    queue_and_dispatch_add_request,
    retry_add_request,
    update_add_request,
)


def test_add_request_prompt_tells_the_agent_to_enrich_through_the_app_not_files():
    prompt = build_cinequeue_add_prompt("Stalker 1979")

    assert prompt.startswith("Add this to the owner's Movies: Stalker 1979")
    assert "Resolve exact-title candidates" in prompt
    assert "cinequeue_add" in prompt and "cinequeue_update" in prompt
    assert "cinequeue_request_update" in prompt
    assert "IMDb's official `title.ratings.tsv.gz`" in prompt
    assert "never hand-copy or relabel a Letterboxd score" in prompt
    assert "featured_episodes" in prompt
    assert "notes" in prompt
    # Portable: no owner, host, path or port assumptions.
    for leak in ("/home/", "127.0.0.1", "8765", "systemd"):
        assert leak not in prompt


def test_queue_add_request_logs_only_to_cinequeue_queue(tmp_path: Path):
    log_path = tmp_path / "add_requests.json"
    record = queue_add_request("Stalker 1979", request_log_path=log_path)

    assert record["status"] == "queued"
    assert record["source_app"] == "Movies"
    assert record["agent"]
    assert record["text"] == "Stalker 1979"
    assert "prompt" in record
    assert "command_center" not in "\n".join(record.keys())
    saved = load_add_requests(log_path)
    assert saved[0]["id"] == record["id"]


def test_queue_add_request_rejects_empty_text(tmp_path: Path):
    log_path = tmp_path / "add_requests.json"
    try:
        queue_add_request("   ", request_log_path=log_path)
    except ValueError as exc:
        assert "request text is required" in str(exc)
    else:
        raise AssertionError("empty request should fail")

    assert not log_path.exists()


def test_queue_and_dispatch_marks_request_dispatched(tmp_path: Path):
    log_path = tmp_path / "add_requests.json"
    seen = []

    record = queue_and_dispatch_add_request(
        "Stalker 1979",
        request_log_path=log_path,
        dispatcher=lambda item: seen.append(item) or {"status": "accepted"},
    )

    assert seen[0]["id"] == record["id"]
    assert record["status"] == "dispatched"
    assert record["dispatch_response"] == {"status": "accepted"}
    saved = load_add_requests(log_path)[0]
    assert saved["status"] == "dispatched"
    assert saved["dispatched_at"]


def test_queue_and_dispatch_persists_truthful_failure(tmp_path: Path):
    log_path = tmp_path / "add_requests.json"

    def fail(_item):
        raise RuntimeError("worker launch unavailable")

    try:
        queue_and_dispatch_add_request(
            "Stalker 1979",
            request_log_path=log_path,
            dispatcher=fail,
        )
    except AddRequestDispatchError as exc:
        assert exc.record["status"] == "dispatch_failed"
    else:
        raise AssertionError("dispatch failure should reach the caller")

    saved = load_add_requests(log_path)[0]
    assert saved["status"] == "dispatch_failed"
    assert saved["dispatch_error"] == "worker launch unavailable"


def test_update_add_request_records_terminal_status(tmp_path: Path):
    log_path = tmp_path / "add_requests.json"
    record = queue_add_request("Stalker 1979", request_log_path=log_path)

    updated = update_add_request(
        record["id"],
        "completed",
        detail="Added and verified through the live API",
        request_log_path=log_path,
    )

    assert updated["status"] == "completed"
    assert updated["status_detail"] == "Added and verified through the live API"
    assert updated["updated_at"] != record["updated_at"]


def test_disabled_integration_saves_request_and_reports_not_sent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(server, "ADMIT", "disabled")
    log_path = tmp_path / "add_requests.json"
    try:
        queue_and_dispatch_add_request("Stalker 1979", request_log_path=log_path)
    except AddRequestDispatchError as exc:
        assert exc.record["status"] == "not_sent"
        assert "not configured" in exc.record["status_detail"]
    else:
        raise AssertionError("a disabled integration must not claim a send")
    assert load_add_requests(log_path)[0]["text"] == "Stalker 1979"


def test_stub_and_fail_modes_never_contact_an_agent():
    assert dispatch_add_request({"id": "x"}, mode="stub")["run_id"] == "stub_run"
    try:
        dispatch_add_request({"id": "x"}, mode="fail")
    except AdmissionError as exc:
        assert "stubbed outage" in str(exc)
    else:
        raise AssertionError("fail mode must raise")


def test_live_admission_uses_wizard_session_then_run(monkeypatch):
    calls = []

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, body, self.headers.get("Idempotency-Key")))
            raw = json.dumps({"run_id": "run_123"} if self.path.endswith("/runs") else {"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(server, "WIZARD_ORIGIN", f"http://127.0.0.1:{fake.server_port}")
        response = dispatch_add_request({"id": "cinequeue-add-1", "text": "Heat", "prompt": build_cinequeue_add_prompt("Heat")}, mode="live")
    finally:
        fake.shutdown()
    assert [c[0] for c in calls] == ["/wizard/hermes/api/sessions", "/wizard/hermes/v1/runs"]
    assert calls[0][1]["source"] == "wizard-mobile"
    assert calls[1][1]["session_id"] == calls[0][1]["id"]
    assert "Movies request ID: cinequeue-add-1" in calls[1][1]["input"]
    assert calls[1][2]
    assert response == {"status": "accepted", "session_id": calls[0][1]["id"], "run_id": "run_123", "mode": "live"}


def test_live_without_origin_is_not_configured(monkeypatch):
    monkeypatch.setattr(server, "WIZARD_ORIGIN", "")
    try:
        dispatch_add_request({"id": "x"}, mode="live")
    except AdmissionError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("live without an origin must not send")


def test_retry_sends_a_saved_request_once(tmp_path: Path):
    log_path = tmp_path / "add_requests.json"

    def fail(_item):
        raise RuntimeError("outage")

    try:
        queue_and_dispatch_add_request("Heat", request_log_path=log_path, dispatcher=fail)
    except AddRequestDispatchError as exc:
        request_id = exc.record["id"]
    sent = retry_add_request(request_id, request_log_path=log_path, dispatcher=lambda item: {"status": "accepted"})
    assert sent["status"] == "dispatched"
    again = retry_add_request(request_id, request_log_path=log_path, dispatcher=fail)
    assert again["status"] == "dispatched"


def test_dispatch_ack_does_not_clobber_fast_worker_completion(tmp_path: Path):
    log_path = tmp_path / "add_requests.json"

    def complete_before_ack(item):
        update_add_request(
            item["id"],
            "completed",
            detail="Worker finished before dispatcher returned",
            request_log_path=log_path,
        )
        return {"status": "accepted"}

    record = queue_and_dispatch_add_request(
        "Stalker 1979",
        request_log_path=log_path,
        dispatcher=complete_before_ack,
    )

    assert record["status"] == "completed"
    assert record["dispatch_response"] == {"status": "accepted"}
    assert load_add_requests(log_path)[0]["status"] == "completed"
