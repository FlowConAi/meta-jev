from __future__ import annotations

import json

import pytest

from system_one_meta_builder import cli


def test_cli_reports_installed_distribution_version(capsys) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--version"])

    assert stopped.value.code == 0
    assert capsys.readouterr().out.startswith("system-one-meta-builder ")


@pytest.mark.parametrize(
    ("candidate_model", "arguments", "expected_model", "expected_source"),
    [
        ("jev-candidate", [], "jev-candidate", "candidate"),
        ("jev-candidate", ["--model", "jev-cli"], "jev-cli", "cli"),
        (None, [], "jev-latest", "default"),
    ],
)
def test_run_model_precedence_is_visible_in_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys,
    candidate_model: str | None,
    arguments: list[str],
    expected_model: str,
    expected_source: str,
) -> None:
    request = {
        "state": {"message": "hello"},
        "questions": {"greeting": {"type": "noul", "instructions": "Is `message` a greeting?"}},
    }
    if candidate_model is not None:
        request["model"] = candidate_model
    candidate_path = tmp_path / "candidate.json"
    output_path = tmp_path / "receipts.jsonl"
    candidate_path.write_text(json.dumps({"request": request}), encoding="utf-8")
    submitted_requests: list[dict] = []

    def fake_call_once(submitted, _questions, **_kwargs):
        submitted_requests.append(dict(submitted))
        return {
            "model": "jev-1.13.0",
            "answers": {"greeting": {"type": "noul", "noul": 0.9}},
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }, 0.01

    monkeypatch.setattr(cli, "call_once", fake_call_once)

    command = ["run", str(candidate_path), "--output", str(output_path), *arguments]
    assert cli.main(command) == 0
    capsys.readouterr()

    assert submitted_requests[0]["model"] == expected_model
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    run_rows = [row for row in rows if row.get("kind") == "run"]
    assert {row["model_source"] for row in run_rows} == {expected_source}
    assert {row["submitted"]["model"] for row in run_rows} == {expected_model}
