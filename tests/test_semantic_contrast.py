from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from system_one_meta_builder import cli
from system_one_meta_builder.guard import guard_report, review_signals, route, routing_policy, scoring_policy
from system_one_meta_builder.io import InputError
from system_one_meta_builder.preflight import code_preflight
from system_one_meta_builder.receipts import request_sha256
from system_one_meta_builder.review import check_metadata, review_requests
from system_one_meta_builder.sdk import normalize_request

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "regressions" / "semantic-contrast-candidate.json"


def candidate() -> dict:
    return json.loads(CANDIDATE.read_text())


@pytest.mark.parametrize(
    "primitive,criteria,answer_a,answer_b,expected_exit",
    [
        ("noul", {"true": "Same call", "false": "Different call"}, {"invented": "shape"}, None, 2),
        ("noul", {"true": "Same call", "false": "Different call"}, False, True, 0),
        ("noul", {"true": "Same call", "false": "Different call"}, 0, 1, 2),
        ("choice", {"same": "Same call", "different": "Different call"}, "same", "missing-option", 2),
        ("choice", {"same": "Same call", "different": "Different call"}, "same", "different", 0),
        ("score", ["No overlap", "Same function", "Same call"], 0, 3, 2),
        ("score", ["No overlap", "Same function", "Same call"], 0, 2, 0),
        ("score", ["No overlap", "Same function", "Same call"], False, 2, 2),
    ],
)
def test_contrast_answers_match_the_question_domain_at_cli_boundary(
    tmp_path, capsys, primitive, criteria, answer_a, answer_b, expected_exit
):
    document = candidate()
    question = document["request"]["questions"]["explicitly_selects_a"]
    question.update(type=primitive, criteria=criteria)
    contrast = document["review_context"]["questions"]["explicitly_selects_a"]["semantic_term_contrasts"][0]
    contrast["differing_answer_case"].update(answer_under_a=answer_a, answer_under_b=answer_b)
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(document))
    assert cli.main(["prepare", str(source)]) == expected_exit
    result = json.loads(capsys.readouterr().out)
    if expected_exit == 2:
        assert result["error"]["type"] == "InputError"
    else:
        assert result["requests"]


def test_prepare_emits_two_independent_advisory_questions_without_host_labels() -> None:
    document = candidate()
    prepared = [item for item in review_requests(document) if item.get("scope") == "question"]

    assert len(prepared) == 3
    for item in prepared:
        semantic_questions = {
            name: question
            for name, question in item["submitted"]["questions"].items()
            if name.startswith("decision_term_rules_out_definition_")
        }
        assert set(semantic_questions) == {
            "decision_term_rules_out_definition_a__0",
            "decision_term_rules_out_definition_b__0",
        }
        assert all(set(question["criteria"]) == {"true", "false"} for question in semantic_questions.values())
        state = item["submitted"]["state"]
        assert len(state["semantic_term_contrasts"]) == 1
        visible = state["semantic_term_contrasts"][0]
        assert visible["selected_path"] == "candidate_question.instructions"
        assert "provenance" not in str(visible)
        assert "differing_answer_case" not in str(state)
        assert "answer_under_a" not in str(item["submitted"])
        assert item["semantic_term_contrast_coverage"]["policy_role"] == "advisory_unvalidated"


def test_preflight_records_host_binding_as_code_known_and_keeps_semantics_advisory() -> None:
    document = candidate()
    prepared = review_requests(document)
    submitted, _ = normalize_request(document, None)
    report = code_preflight(document, prepared, request_sha256(submitted))

    bindings = [
        item for item in report["analysis_ownership"]["code_known"] if item["kind"] == "semantic_term_contrast_binding"
    ]
    assert len(bindings) == 3
    assert {item["selected_path"] for item in bindings} == {"candidate_question.instructions"}
    assert {item["policy_role"] for item in bindings} == {"advisory_unvalidated"}
    assert all(item["definition_provenance"]["a"]["kind"] == "constructed_diagnostic" for item in bindings)
    assert not any(
        item["kind"] == "semantic_term_contrast_coverage" for item in report["analysis_ownership"]["incomplete"]
    )


def test_invalid_selected_occurrence_stops_before_any_review_request() -> None:
    document = candidate()
    contrast = document["review_context"]["questions"]["explicitly_selects_a"]["semantic_term_contrasts"][0]
    contrast["occurrence_index"] = 1

    with pytest.raises(InputError, match="selected occurrence is absent"):
        review_requests(document)


def test_selected_path_uses_the_shared_dotted_and_indexed_path_owner() -> None:
    document = candidate()
    document["request"]["state"]["snippets"] = [
        {"text": "For this check, same operation means the same source call expression."}
    ]
    contrast = document["review_context"]["questions"]["explicitly_selects_a"]["semantic_term_contrasts"][0]
    contrast["selected_path"] = "request_state.snippets[0].text"

    prepared = next(
        item for item in review_requests(document) if item.get("candidate_question_id") == "explicitly_selects_a"
    )
    stored = prepared["semantic_term_contrast_coverage"]["contrasts"][0]
    assert stored["selected_text"] == document["request"]["state"]["snippets"][0]["text"]


def test_high_semantic_contrast_observations_cannot_route_or_change_design_score() -> None:
    document = candidate()
    prepared = [item for item in review_requests(document) if item.get("scope") == "question"]
    receipts = []
    for item in prepared:
        receipt = deepcopy(item)
        answers = {}
        for check_id in item["submitted"]["questions"]:
            probability = 0.99 if check_id.startswith("decision_term_rules_out_definition_") else 0.01
            answers[check_id] = {"type": "noul", "noul": probability}
        receipt.update(
            {
                "response_model": "jev-test",
                "guard_source": "fresh",
                "response": {"model": "jev-test", "answers": answers},
            }
        )
        receipts.append(receipt)
    signals = review_signals(receipts, {"question": check_metadata("question")})
    report = guard_report(
        document=document,
        receipts=receipts,
        signals=signals,
        route_policy=routing_policy(0.2, 0.8),
        score_policy=scoring_policy(),
        candidate_request_sha256="fixture",
    )

    semantic = [item for item in report["model_observations"] if item.get("advisory_only")]
    assert len(semantic) == 6
    assert {item["probability"] for item in semantic} == {0.99}
    critical_checks = {entry["check"] for entry in report["policy_conclusions"]["critical_conditions"]}
    assert all(item["check_id"] not in critical_checks for item in semantic)
    semantic_feedback = [item for item in report["feedback"] if item["evidence_status"] == "model_advisory_unvalidated"]
    assert len(semantic_feedback) == 6
    assert {item["disposition"] for item in semantic_feedback} == {"observation"}
    assert {item["recommended_action"] for item in semantic_feedback} == {None}
    assert {item["dimensions"]["question_clarity"]["risk"] for item in report["scoring"]["questions"]} == {0.01}
    assert (
        route(
            [
                {
                    "scope": "question",
                    "check_id": "decision_term_rules_out_definition_a__0",
                    "probability": 0.99,
                    "advisory_only": True,
                }
            ],
            routing_policy(0.2, 0.8),
        )
        == "ready_for_small_trial"
    )
