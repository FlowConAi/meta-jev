from __future__ import annotations

import json

from system_one_meta_builder import cli
from system_one_meta_builder.io import InputError
from system_one_meta_builder.observations import inspect


def _program() -> dict:
    return {
        "decisions": [
            {
                "id": "mentions_failure",
                "kind": "noul",
                "instructions": "Does the report state that the check failed?",
                "criteria": {"true": "A failure is stated.", "false": "No failure is stated."},
            }
        ],
        "reduce": {
            "kind": "rules",
            "rules": [{"when": [{"id": "mentions_failure", "op": "gte", "value": 0.8}], "then": "review"}],
            "otherwise": "clear",
        },
        "residual": "",
        "dropped": [],
    }


def test_compile_program_crosses_real_jevc_cli_and_sdk_boundary(tmp_path, capsys) -> None:
    program = tmp_path / "program.json"
    state = tmp_path / "state.json"
    program.write_text(json.dumps(_program()), encoding="utf-8")
    state.write_text(json.dumps({"report": "the check failed"}), encoding="utf-8")

    assert cli.main(["compile-program", str(program), "--state", str(state)]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["compiler"]["package"] == "jev-compiler"
    assert result["compiler"]["version"] == "0.1.0"
    assert result["request"] == {
        "model": "jev-latest",
        "state": {"report": "the check failed"},
        "questions": {
            "mentions_failure": {
                "type": "noul",
                "instructions": "Does the report state that the check failed?",
                "criteria": {"true": "A failure is stated.", "false": "No failure is stated."},
            }
        },
    }


def test_run_program_keeps_meta_receipts_and_uses_jevc_reducer(tmp_path, monkeypatch, capsys) -> None:
    program = tmp_path / "program.json"
    state = tmp_path / "state.json"
    receipts = tmp_path / "receipts.jsonl"
    program.write_text(json.dumps(_program()), encoding="utf-8")
    state.write_text(json.dumps({"report": "the check failed"}), encoding="utf-8")

    def fake_call_once(submitted, _questions, **_kwargs):
        return {
            "model": "jev-1.13.0",
            "answers": {"mentions_failure": {"type": "noul", "noul": 0.91}},
            "usage": {"input_tokens": 12, "output_tokens": 1},
        }, 0.02

    monkeypatch.setattr(cli, "call_once", fake_call_once)
    assert (
        cli.main(
            ["run-program", str(program), "--state", str(state), "--output", str(receipts)]
        )
        == 0
    )
    capsys.readouterr()

    rows = [json.loads(line) for line in receipts.read_text(encoding="utf-8").splitlines()]
    attempt_rows = [row for row in rows if row.get("kind") == "run"]
    assert [row["status"] for row in attempt_rows] == ["started", "received", "ok"]
    assert attempt_rows[-1]["verdict"] == "review"
    assert attempt_rows[-1]["program"] == _program()
    assert attempt_rows[-1]["compiler"]["program_sha256"]
    measured = inspect(rows)
    assert measured["observation_count"] == 1
    assert measured["row_applicability"]["applied_rows"] == [3]


def test_run_program_retains_received_response_when_reducer_fails(tmp_path, monkeypatch, capsys) -> None:
    program = tmp_path / "program.json"
    state = tmp_path / "state.json"
    receipts = tmp_path / "receipts.jsonl"
    program.write_text(json.dumps(_program()), encoding="utf-8")
    state.write_text(json.dumps({"report": "the check failed"}), encoding="utf-8")
    response = {
        "model": "jev-1.13.0",
        "answers": {"mentions_failure": {"type": "noul", "noul": 0.91}},
        "usage": {"input_tokens": 12, "output_tokens": 1},
    }

    def fake_call_once(_submitted, _questions, *, record_event):
        record_event(
            {
                "event": "http_response",
                "status_code": 200,
                "body_base64": "eyJhbnN3ZXJzIjp7fX0=",
                "body_sha256": "raw-response-sha256",
            }
        )
        return response, 0.02

    def fail_reducer(_program, _answers):
        raise InputError("reducer rejected retained answers")

    monkeypatch.setattr(cli, "call_once", fake_call_once)
    monkeypatch.setattr(cli, "reduce_program", fail_reducer)

    assert (
        cli.main(
            ["run-program", str(program), "--state", str(state), "--output", str(receipts)]
        )
        == 1
    )
    capsys.readouterr()

    rows = [json.loads(line) for line in receipts.read_text(encoding="utf-8").splitlines()]
    assert [row["status"] for row in rows if row.get("kind") == "run"] == [
        "started",
        "received",
        "reduction_failed",
    ]
    assert next(row for row in rows if row.get("status") == "received")["response"] == response
    assert next(row for row in rows if row.get("event") == "http_response")["body_base64"] == (
        "eyJhbnN3ZXJzIjp7fX0="
    )
    terminal = rows[-1]
    assert terminal["response"] == response
    assert terminal["error"] == {
        "type": "InputError",
        "message": "reducer rejected retained answers",
    }
