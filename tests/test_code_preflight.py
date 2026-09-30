import json

from system_one_meta_builder import cli
from system_one_meta_builder.io import fingerprint
from system_one_meta_builder.preflight import code_preflight
from system_one_meta_builder.review import review_requests


def test_missing_reference_stops_before_any_provider_call_and_names_exact_repair(tmp_path, monkeypatch):
    document = {
        "state": {"message": "hello"},
        "questions": {"matches": {"type": "noul", "instructions": "Does `message` request `policy.action`?"}},
    }
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(document))
    output = tmp_path / "receipts.jsonl"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("missing reference must be found before paid inference")

    monkeypatch.setattr(cli, "call_once", forbidden)
    assert cli.main(["guard", str(source), "--output", str(output)]) == 3
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 1
    report = rows[0]
    assert report["kind"] == "preflight"
    assert report["provider_calls"] == 0
    assert report["route"] == "gather_evidence"
    finding = next(item for item in report["findings"] if item["code"] == "unresolved_state_reference")
    assert finding["question"] == "matches"
    assert finding["state_path"] == "policy.action"
    assert finding["severity"] == "error"
    assert "policy.action" in finding["message"]
    assert finding["source_references"][0]["source_url"]
    assert report["scoring"] is None


def test_code_only_reports_optional_criteria_without_inventing_invalidity(tmp_path, monkeypatch):
    source = tmp_path / "candidate.json"
    source.write_text(
        json.dumps(
            {
                "state": {"message": "hello"},
                "questions": {"greeting": {"type": "noul", "instructions": "Does `message` greet someone?"}},
            }
        )
    )
    output = tmp_path / "receipts.jsonl"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("code-only must never call the provider")

    monkeypatch.setattr(cli, "call_once", forbidden)
    assert cli.main(["guard", str(source), "--output", str(output), "--code-only"]) == 3
    report = json.loads(output.read_text().splitlines()[-1])
    assert report["route"] == "review_required"
    assert report["provider_calls"] == 0
    criterion = next(item for item in report["findings"] if item["code"] == "criteria_not_supplied")
    assert criterion["severity"] == "info"
    assert "optional" in criterion["message"]
    assert criterion["source_references"][0]["id"] == "noul_criteria_are_optional"
    preserved = next(
        item
        for item in report["analysis_ownership"]["code_known"]
        if item["kind"] == "structural_finding" and item["code"] == "criteria_not_supplied"
    )
    assert preserved["action"] == "inspect_answer_boundary"
    assert preserved["message"] == criterion["message"]
    assert preserved["source_references"] == criterion["source_references"]


def test_preflight_separates_ast_facts_from_actual_semantic_checks_and_missing_coverage():
    document = {
        "request": {
            "state": {"message": "please cancel"},
            "questions": {
                "cancel": {
                    "type": "noul",
                    "instructions": "Does `message` request cancellation?",
                }
            },
        },
        "workflow": {
            "language": "python",
            "purpose": "Queue likely cancellation requests for review.",
            "consumer_code": 'if response.answers["cancel"].noul > threshold:\n    queue_review()',
        },
    }

    prepared = review_requests(document)
    report = code_preflight(document, prepared, fingerprint(document["request"]))
    ownership = report["analysis_ownership"]

    assert next(item for item in ownership["code_known"] if item["kind"] == "python_consumer_site") == {
        "kind": "python_consumer_site",
        "site_id": "site_0",
        "site_kind": "answer_read",
        "line": 1,
        "expression": "response.answers['cancel'].noul",
        "answer_fields": ["noul"],
        "question_ids": ["cancel"],
        "branch_conditions": ["response.answers['cancel'].noul > threshold"],
        "downstream_uses": [],
    }
    workflow_checks = next(item for item in ownership["semantic"] if item["scope"] == "workflow")
    assert "consumer_site_overclaims_evidence__0" in workflow_checks["check_ids"]
    assert "model_used_for_fully_determined_rule__0" not in workflow_checks["check_ids"]
    assert any(item["kind"] == "atomicity_pair_coverage" for item in ownership["incomplete"])
    assert ownership["source_references"][0]["id"] == "deterministic_rules_stay_in_code"
    assert "prepared for model judgment" in ownership["meaning"]
    assert all(
        "deterministic_rules_stay_in_code" not in item.get("submitted", {}).get("state", {}).get("principles", {})
        for item in prepared
    )
