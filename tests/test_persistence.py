from __future__ import annotations

import base64
import contextlib
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from system_one_meta_builder import cli
from system_one_meta_builder.sdk import call_once, normalize_request, validated_questions


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_actual_sdk_transport_has_no_client_deadline(monkeypatch):
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            time.sleep(5.2)
            body = json.dumps(
                {
                    "model": "jev-test",
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                    "answers": {"slow": {"type": "noul", "noul": 0.9}},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError):
                self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TYPESAFE_API_KEY", "paid-provider-test-seam")
    monkeypatch.setenv("TYPESAFE_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    submitted, questions = normalize_request(
        {
            "state": {"message": "This intentionally slow local response is still valid."},
            "questions": {"slow": {"type": "noul", "instructions": "Is `message` a statement?"}},
        }
    )
    events = []
    try:
        response, elapsed = call_once(
            submitted,
            validated_questions(submitted["questions"]),
            record_event=events.append,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert len(captured) == 1
    assert response["answers"]["slow"] == {"type": "noul", "noul": 0.9}
    assert elapsed >= 5.0
    assert [event["event"] for event in events] == ["http_request", "http_response"]


@pytest.mark.parametrize("mode", ["success", "missing_answers", "invalid_sdk_shape", "non_json", "http_error"])
@pytest.mark.parametrize("command", ["review", "run"])
def test_actual_sdk_keeps_request_and_response_before_validation(tmp_path, monkeypatch, mode, command):
    output = tmp_path / "journal.jsonl"
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "state": {"message": "cancel"},
                "questions": {"cancel": {"type": "noul", "instructions": "Does `message` request cancellation?"}},
            }
        )
    )
    captured = []
    snapshots = []
    bodies = {
        "missing_answers": b'{"model":"jev-test","answers":{},"usage":{"input_tokens":123,"output_tokens":4}}',
        "invalid_sdk_shape": b'{"model":"jev-test","answers":{"x":{"type":"noul","noul":7}}}',
        "non_json": b"not JSON\x00\xff",
        "http_error": b'{"error":"provider failed after processing"}',
        "success": b"",
    }
    body = bodies[mode]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal body
            captured.append(self.rfile.read(int(self.headers["Content-Length"])))
            snapshots.append(rows(output))
            if mode == "success":
                body = json.dumps(
                    {
                        "model": "jev-test",
                        "usage": {"input_tokens": 123, "output_tokens": 4},
                        "answers": {
                            name: {"type": "noul", "noul": 0.3} for name in json.loads(captured[-1])["questions"]
                        },
                    }
                ).encode()
            self.send_response(503 if mode == "http_error" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("x-typesafe-request-id", "test-response-id")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TYPESAFE_API_KEY", "paid-provider-test-seam")
    monkeypatch.setenv("TYPESAFE_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        assert cli.main([command, str(candidate), "--output", str(output)]) == (0 if mode == "success" else 1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert len(captured) == 1
    persisted = rows(output)
    started = [row for row in snapshots[0] if row.get("status") == "started"]
    assert len(started) == 1
    actual_state = started[0]["submitted"]["state"]
    assert (actual_state["request_state"] if command == "review" else actual_state) == {"message": "cancel"}
    request_events = [row for row in snapshots[0] if row.get("event") == "http_request"]
    assert base64.b64decode(request_events[0]["body_base64"]) == captured[0]
    response_events = [row for row in persisted if row.get("event") == "http_response"]
    assert len(response_events) == 1
    assert base64.b64decode(response_events[0]["body_base64"]) == body
    assert response_events[0]["request_id"] == "test-response-id"
    final = [row for row in persisted if row.get("status") in ("ok", "invalid_response", "error")]
    assert len(final) == 1
    assert final[0]["attempt_id"] == started[0]["attempt_id"] == response_events[0]["attempt_id"]
    if mode == "missing_answers":
        assert final[0]["status"] == "invalid_response"
        assert final[0]["response"] == json.loads(body)
        assert final[0]["usage"]["input_tokens"] == 123
        assert final[0]["response_model"] == "jev-test"
    if mode == "success":
        assert final[0]["status"] == "ok"
        assert final[0]["response"] == json.loads(body)
        received = [row for row in persisted if row.get("status") == "received"]
        assert received[0]["response"] == final[0]["response"]


def test_programming_failure_keeps_attempt_without_inventing_provider_failure(tmp_path, monkeypatch, capsys):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "state": "hello",
                "questions": {
                    "greeting": {"type": "noul", "instructions": "Is this a greeting?"},
                },
            }
        )
    )
    output = tmp_path / "journal.jsonl"

    def fail_inside_code(*_args, **_kwargs):
        assert rows(output)[0]["status"] == "started"
        raise KeyError("broken implementation")

    monkeypatch.setattr(cli, "call_once", fail_inside_code)
    assert cli.main(["run", str(candidate), "--output", str(output)]) == 4
    captured = capsys.readouterr()
    assert "KeyError: 'broken implementation'" in captured.err
    assert [row["status"] for row in rows(output)] == ["started"]
