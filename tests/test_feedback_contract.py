from __future__ import annotations

import json

from system_one_meta_builder import cli


def candidate(workflow=None):
    document = {
        "request": {
            "state": {"subject_function": "def read(): return helper()"},
            "questions": {
                "skips_invalid": {
                    "type": "noul",
                    "instructions": "Does `subject_function` discard invalid entries?",
                }
            },
        }
    }
    if workflow is not None:
        document["workflow"] = workflow
    return document


def run_guard(tmp_path, monkeypatch, document, probabilities=None):
    path = tmp_path / "candidate.json"
    output = tmp_path / "receipts.jsonl"
    path.write_text(json.dumps(document))
    probabilities = probabilities or {}

    def provider(submitted, *_args, **_kwargs):
        return {
            "model": "jev-test",
            "answers": {key: {"type": "noul", "noul": probabilities.get(key, 0.01)} for key in submitted["questions"]},
        }, 0.01

    monkeypatch.setattr(cli, "call_once", provider)
    assert cli.main(["guard", str(path), "--output", str(output), "--clear-below", "0.2", "--flag-at", "0.8"]) == 3
    return json.loads(output.read_text().splitlines()[-1])


def test_feedback_links_signal_to_question_state_and_documentation(tmp_path, monkeypatch):
    report = run_guard(tmp_path, monkeypatch, candidate(), {"requires_missing_case_fact": 0.93})
    finding = next(item for item in report["feedback"] if item["check"] == "requires_missing_case_fact")
    assert finding["location"] == {
        "question_path": "request.questions.skips_invalid",
        "state_paths": ["subject_function"],
    }
    assert finding["probability"] == 0.93
    assert finding["recommended_action"] == "supply_evidence"
    assert finding["evidence_status"] == "model_suspected"
    principle_ref = finding["principle_references"][0]
    assert principle_ref["id"] == "supply_case_evidence"
    principle = report["principles"][principle_ref["content_id"]]
    assert principle["source_url"].endswith("#decompose-the-input-state")
    assert principle["rule"]
    assert "subject_function" in finding["message"]
    assert "does not identify which fact" in finding["message"]
    assert finding["request_sha256"] in report["review_request_sha256"]
    assert report["route"] == "gather_evidence"
    assert report["scoring"]["request"]["design_score"] is None
    assert report["scoring"]["questions"][0]["coverage"]["missing_dimensions"] == ["atomicity"]
    signal = next(item for item in report["model_observations"] if item["check_id"] == finding["check"])
    assert signal["typed_answer"] == {"type": "noul", "noul": 0.93}
    assert "principle_provenance" not in signal
    assert "source_references" not in finding
    assert finding["typed_answer"] == signal["typed_answer"]
    assert finding["response_model"] == "jev-test"
    assert finding["observation_id"] == signal["observation_id"]
    context = signal["review_context"]
    assert "candidate_question" not in context
    review_input = report["review_inputs"][signal["review_input_reference"]]
    assert review_input["candidate_question"] == candidate()["request"]["questions"]["skips_invalid"]
    assert len(report["review_inputs"]) == 1
    assert context["review_question"]["instructions"]["question"] == (
        "Does the substantive judgment require a case-specific fact absent from `request_state`?"
    )
    assert context["scope_limit"]
    assert context["inspect_paths"]
    assert review_input["request_state_reference"]["selected_paths"] == ["subject_function"]
    assert len(review_input["request_state_reference"]["sha256"]) == 64
    assert "not model rationale" in finding["meaning"]
    assert principle["source_excerpt"]
    assert finding["reviewed_proposition"] == context["review_question"]["instructions"]["question"]
    assert finding["observation_id"] == signal["observation_id"]
    assert "scope_limit" not in finding
    assert "reviewed_input_reference" not in finding
    component = next(
        item for item in report["model_observations"] if item["check_id"] == "state_component_role_is_unclear__0"
    )
    assert component["review_context"]["inspected_content"] == {
        "kind": "state_component",
        "content": {"path": "subject_function", "value": "def read(): return helper()"},
    }


def test_unreviewed_consumer_preserves_actual_reason_in_report(tmp_path, monkeypatch):
    report = run_guard(
        tmp_path,
        monkeypatch,
        candidate({"language": "javascript", "consumer_code": "if (answers.skips_invalid.noul > .8) act();"}),
    )
    reason = report["scoring"]["workflow"]["coverage"]["reason"]
    assert reason == "workflow language 'javascript' is not supported; only Python is reviewed"
    assert report["policy_conclusions"]["missing_information"][-1]["workflow"] == reason


def test_unresolved_consumer_read_is_not_reported_as_absent_code(tmp_path, monkeypatch):
    report = run_guard(
        tmp_path,
        monkeypatch,
        candidate({"language": "python", "consumer_code": "if before['skips_invalid'] > .8: act()"}),
    )
    reason = report["scoring"]["workflow"]["coverage"]["reason"]
    assert "no resolvable typed-answer reads" in reason
    assert "not supplied" not in reason


def test_full_guard_preserves_the_code_semantic_and_incomplete_division(tmp_path, monkeypatch):
    report = run_guard(
        tmp_path,
        monkeypatch,
        candidate(
            {
                "language": "python",
                "purpose": "Queue likely defects for review.",
                "consumer_code": 'if answers["skips_invalid"].noul > threshold: queue_review()',
            }
        ),
    )

    ownership = report["analysis_ownership"]
    criteria_finding = next(
        item
        for item in ownership["code_known"]
        if item["kind"] == "structural_finding" and item["code"] == "criteria_not_supplied"
    )
    assert criteria_finding["action"] == "inspect_answer_boundary"
    assert "Criteria are optional" in criteria_finding["message"]
    assert criteria_finding["source_references"][0]["id"] == "noul_criteria_are_optional"
    assert (
        next(item for item in ownership["code_known"] if item["kind"] == "python_consumer_site")["expression"]
        == "answers['skips_invalid'].noul"
    )
    workflow_checks = next(item for item in ownership["semantic"] if item["scope"] == "workflow")
    assert set(workflow_checks["check_ids"]) == {
        "consumer_site_overclaims_evidence__0",
        "missing_evidence_mapped_to_negative__0",
        "noul_probability_used_as_degree__0",
    }
    assert ownership["incomplete"] == [
        {
            "scope": "question",
            "candidate_question_id": "skips_invalid",
            "kind": "atomicity_pair_coverage",
            "reason": (
                "no source-backed atomicity pair with independently needed consumer outputs and mixed-truth evidence"
            ),
            "affects": ["question_design_score", "full_request_readiness"],
        },
        {
            "scope": "question",
            "candidate_question_id": "skips_invalid",
            "kind": "semantic_term_contrast_coverage",
            "reason": "no host-supplied quoted term with two grounded definitions and a differing-answer case",
            "affects": ["semantic_term_contrast_advisory"],
        },
    ]
    consumer_observation = next(
        item for item in report["model_observations"] if item["check_id"] == "consumer_site_overclaims_evidence__0"
    )
    inspected = consumer_observation["review_context"]["inspected_content"]
    assert inspected["kind"] == "consumer_site"
    assert inspected["content"]["expression"] == "answers['skips_invalid'].noul"
    assert inspected["content"]["line"] == 1
    assert report["route"] == "review_required"
    assert report["scoring"]["request"]["status"] == "incomplete"
    missing = report["policy_conclusions"]["missing_information"][0]
    assert missing["missing_dimensions"] == ["atomicity"]
    assert "state references" not in missing["repair"]
    assert missing["repair_actions"] == [
        {
            "action": "provide_atomicity_pair_or_keep_unreviewed",
            "dimension": "atomicity",
            "reason": (
                "no source-backed atomicity pair with independently needed consumer outputs and mixed-truth evidence"
            ),
            "message": (
                "Provide a source-grounded proposition pair tied to two separately needed consumer outputs "
                "and mixed-truth evidence, or keep atomicity explicitly unreviewed."
            ),
        }
    ]
