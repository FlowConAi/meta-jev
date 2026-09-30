from __future__ import annotations

import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Barrier, BrokenBarrierError, Thread

from system_one_meta_builder import cli


def test_independent_reviews_reach_provider_together_and_keep_separate_receipts(tmp_path, monkeypatch, capsys):
    """The provider refuses a serial batch; no timing comparison or fake client needed."""
    barrier = Barrier(2)
    arrivals = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            arrivals.append(payload)
            try:
                barrier.wait(timeout=2)
            except BrokenBarrierError:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b'{"error":"second review never arrived concurrently"}')
                return
            body = json.dumps(
                {
                    "model": "jev-test",
                    "answers": {key: {"type": "noul", "noul": 0.1} for key in payload["questions"]},
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TYPESAFE_API_KEY", "paid-provider-test-seam")
    monkeypatch.setenv("TYPESAFE_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "state": {"message": "Cancel my subscription and send a refund."},
                "questions": {
                    key: {"type": "noul", "instructions": f"Does `message` request {action}?"}
                    for key, action in [("cancel", "cancellation"), ("refund", "a refund")]
                },
            }
        )
    )
    output = tmp_path / "receipts.jsonl"
    try:
        result = cli.main(["guard", str(candidate), "--output", str(output)])
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    capsys.readouterr()
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    successes = [row for row in rows if row.get("kind") == "review" and row.get("status") == "ok"]
    assert result == 3
    assert len(arrivals) == len(successes) == 2
    assert {row["candidate_question_id"] for row in successes} == {"cancel", "refund"}
    for receipt in successes:
        attempt = [row for row in rows if row.get("attempt_id") == receipt["attempt_id"]]
        wire = next(row for row in attempt if row.get("event") == "http_response")
        assert json.loads(base64.b64decode(wire["body_base64"])) == receipt["response"]
        assert attempt[0]["status"] == "started"
