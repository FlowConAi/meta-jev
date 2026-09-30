"""Policy tests use provider responses as inputs; they do not validate Jev's judgments."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from system_one_meta_builder import cli
from system_one_meta_builder.io import InputError
from system_one_meta_builder.review import review_requests


def candidate():
    return {
        "request": {
            "model": "jev-latest",
            "state": {"run": {"started": True, "finished": False}},
            "questions": {
                "ran": {
                    "type": "noul",
                    "instructions": "Has `run` started?",
                    "criteria": {"true": "The run started and finished.", "false": "The run has not started."},
                }
            },
        },
        "review_context": {
            "questions": {
                "ran": {
                    "criteria_conditions": [
                        {
                            "condition_id": "completion",
                            "condition": "The run has finished.",
                            "source_path": "candidate_question.criteria.true",
                            "source_quote": "finished",
                        }
                    ]
                }
            }
        },
    }


@pytest.mark.parametrize("context", [None, {"questions": None}, {"questions": {"ran": None}}])
def test_optional_null_context_prepares_without_condition_review(tmp_path, capsys, context):
    document = candidate()
    document["review_context"] = context
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(document))
    assert cli.main(["prepare", str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert all(item["scope"] != "criteria_condition" for item in result["requests"])


def test_components_are_isolated_and_the_unchanged_question_is_not_rewritten():
    document = candidate()
    original = deepcopy(document)
    prepared = [item for item in review_requests(document) if item["scope"] == "criteria_condition"]
    assert len(prepared) == 2
    assert document == original
    instruction_state, criterion_state = [item["submitted"]["state"] for item in prepared]
    assert instruction_state["component"] == "Has `run` started?"
    assert criterion_state["component"] == "The run started and finished."
    for state in (instruction_state, criterion_state):
        assert state["request_state"] == document["request"]["state"]
        assert "candidate_question" not in state
        assert "expected" not in state
        assert "source_quote" not in state
        assert "side" not in state
    assert all(item["policy_role"] == "advisory_unvalidated" for item in prepared)


@pytest.mark.parametrize("field,value", [("source_quote", "invented phrase"), ("source_path", "request_state.run")])
def test_condition_binding_is_checked_before_provider_spend(tmp_path, monkeypatch, capsys, field, value):
    document = candidate()
    document["review_context"]["questions"]["ran"]["criteria_conditions"][0][field] = value
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(document))
    called = []
    monkeypatch.setattr(cli, "call_once", lambda *args, **kwargs: called.append(args))
    assert cli.main(["guard", str(source), "--output", str(tmp_path / "receipts.jsonl")]) == 2
    assert not called
    assert "condition" in json.loads(capsys.readouterr().out)["error"]["message"]


def test_duplicate_condition_id_and_wrong_primitive_are_input_errors():
    document = candidate()
    conditions = document["review_context"]["questions"]["ran"]["criteria_conditions"]
    conditions.append(deepcopy(conditions[0]))
    with pytest.raises(InputError, match="duplicate criteria condition"):
        review_requests(document)
    document = candidate()
    document["request"]["questions"]["ran"]["type"] = "choice"
    with pytest.raises(InputError, match="requires a Noul"):
        review_requests(document)


@pytest.mark.parametrize(
    "instruction,criterion,outcome",
    [
        (0.03, 0.97, "asymmetric_requirement"),
        (0.97, 0.97, "same_requirement"),
        (0.03, 0.03, "same_requirement"),
        (0.5, 0.97, "uncertain"),
    ],
)
def test_cli_returns_the_pair_without_promoting_it_into_a_defect_or_score(
    tmp_path,
    monkeypatch,
    capsys,
    instruction,
    criterion,
    outcome,
):
    document = candidate()
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(document))
    output = tmp_path / "receipts.jsonl"

    def provider(submitted, *_args, **_kwargs):
        value = instruction if submitted["state"].get("component") == "Has `run` started?" else criterion
        return {
            "model": "jev-test",
            "answers": {
                key: {"type": "noul", "noul": value if key == "component_requires_condition" else 0.01}
                for key in submitted["questions"]
            },
        }, 0.01

    monkeypatch.setattr(cli, "call_once", provider)
    assert cli.main(["guard", str(source), "--output", str(output), "--clear-below", "0.2", "--flag-at", "0.8"]) == 3
    report = json.loads(capsys.readouterr().out)
    (comparison,) = report["criteria_condition_assessments"]
    assert comparison["outcome"] == outcome
    assert comparison["components"]["instructions"]["probability"] == instruction
    assert comparison["components"]["true_criterion"]["probability"] == criterion
    assert comparison["source_quote"] == "finished"
    assert not comparison["affects_design_score"]
    assert not comparison["affects_route"]
    assert report["route"] == "review_required"
    assert report["scoring"]["request"]["design_score"] is None
    assert len(report["scoring"]["questions"]) == 1
    assert report["policy_conclusions"]["critical_conditions"] == []
    observations = {item["observation_id"]: item for item in report["model_observations"]}
    for component in comparison["components"].values():
        observation = observations[component["observation_id"]]
        assert observation["typed_answer"]["noul"] == component["probability"]
        assert observation["review_context"]["inspected_content"]["component"] == component["content"]
        assert observation["principle_references"]
    saved = [json.loads(row) for row in output.read_text().splitlines()]
    requests = [row for row in saved if row.get("scope") == "criteria_condition" and row.get("status") == "ok"]
    assert len(requests) == 2


def test_reused_identical_components_keep_both_current_source_bindings(tmp_path, monkeypatch, capsys):
    document = candidate()
    document["request"]["questions"]["ran"]["instructions"] = "The run started and finished."
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(document))
    output = tmp_path / "receipts.jsonl"

    def provider(submitted, *_args, **_kwargs):
        return {
            "model": "jev-test",
            "answers": {key: {"type": "noul", "noul": 0.95} for key in submitted["questions"]},
        }, 0.01

    monkeypatch.setattr(cli, "call_once", provider)
    cli.main(["guard", str(source), "--output", str(output)])
    capsys.readouterr()

    def must_reuse(*_args, **_kwargs):
        pytest.fail("the exact request already has a retained response")

    monkeypatch.setattr(cli, "call_once", must_reuse)
    assert cli.main(["guard", str(source), "--reuse", str(output), "--output", str(tmp_path / "reused.jsonl")]) == 3
    report = json.loads(capsys.readouterr().out)
    (comparison,) = report["criteria_condition_assessments"]
    assert set(comparison["components"]) == {"instructions", "true_criterion"}
    assert comparison["outcome"] == "unthresholded"


def test_identical_components_keep_each_paid_answer_and_source_binding(tmp_path, monkeypatch, capsys):
    from threading import Lock

    document = candidate()
    document["request"]["questions"]["ran"]["instructions"] = "The run started and finished."
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(document))
    output = tmp_path / "receipts.jsonl"
    values = iter([0.91, 0.93])
    lock = Lock()

    def provider(submitted, *_args, **_kwargs):
        with lock:
            value = next(values) if "component" in submitted["state"] else 0.01
        return {
            "model": "jev-test",
            "answers": {key: {"type": "noul", "noul": value} for key in submitted["questions"]},
        }, 0.01

    monkeypatch.setattr(cli, "call_once", provider)
    assert cli.main(["guard", str(source), "--output", str(output)]) == 3
    report = json.loads(capsys.readouterr().out)
    comparison = report["criteria_condition_assessments"][0]
    saved = [json.loads(line) for line in output.read_text().splitlines()]
    receipts = [row for row in saved if row.get("scope") == "criteria_condition" and row.get("status") == "ok"]
    observations = {row["observation_id"]: row for row in report["model_observations"]}
    assert len({part["observation_id"] for part in comparison["components"].values()}) == 2
    for receipt in receipts:
        side = receipt["condition_comparison"]["side"]
        part = comparison["components"][side]
        assert part["probability"] == receipt["response"]["answers"]["component_requires_condition"]["noul"]
        observation = observations[part["observation_id"]]
        assert observation["review_context"]["inspected_content"]["side"] == side
        assert observation["probability"] == part["probability"]
        reviewed = report["review_inputs"][observation["review_input_reference"]]
        assert reviewed["provider_attempt_id"] == receipt["attempt_id"]
        assert reviewed["condition_comparison"] == receipt["condition_comparison"]


def test_equal_requests_for_two_question_ids_do_not_mix_their_scores(tmp_path, monkeypatch, capsys):
    from threading import Lock

    document = candidate()
    del document["review_context"]
    document["request"]["questions"]["other_id"] = deepcopy(document["request"]["questions"]["ran"])
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(document))
    output = tmp_path / "receipts.jsonl"
    values = iter([0.1, 0.3])
    lock = Lock()

    def provider(submitted, *_args, **_kwargs):
        with lock:
            value = next(values)
        return {
            "model": "jev-test",
            "answers": {key: {"type": "noul", "noul": value} for key in submitted["questions"]},
        }, 0.01

    monkeypatch.setattr(cli, "call_once", provider)
    assert cli.main(["guard", str(source), "--output", str(output)]) == 3
    report = json.loads(capsys.readouterr().out)
    saved = [json.loads(line) for line in output.read_text().splitlines()]
    receipts = [row for row in saved if row.get("scope") == "question" and row.get("status") == "ok"]
    scores = {row["question"]: row for row in report["scoring"]["questions"]}
    for receipt in receipts:
        expected = next(iter(receipt["response"]["answers"].values()))["noul"]
        score = scores[receipt["candidate_question_id"]]
        assert score["dimensions"]["question_clarity"]["risk"] == expected
    assert len(report["review_inputs"]) == 2
    for observation in report["model_observations"]:
        reviewed = report["review_inputs"][observation["review_input_reference"]]
        assert reviewed["candidate_question_id"] == observation["candidate_question_id"]
