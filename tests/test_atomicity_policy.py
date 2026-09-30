from copy import deepcopy

import pytest

from system_one_meta_builder.guard import guard_report, review_signals, routing_policy, scoring_policy
from system_one_meta_builder.review import check_metadata, review_requests


def paired_candidate():
    return {
        "state": {"message": "Cancel the renewal; keep my existing purchase."},
        "questions": {
            "cancel_and_refund": {"type": "noul", "instructions": "Does `message` request cancellation and a refund?"}
        },
        "review_context": {
            "questions": {
                "cancel_and_refund": {
                    "atomicity_pairs": [
                        {
                            "pair_id": "cancel_refund",
                            "proposition_a": {
                                "id": "cancel",
                                "text": "The message requests cancellation.",
                                "source_anchor": "request.questions.cancel_and_refund.instructions",
                            },
                            "proposition_b": {
                                "id": "refund",
                                "text": "The message requests a refund.",
                                "source_anchor": "request.questions.cancel_and_refund.instructions",
                            },
                            "consumer_outputs": {"a": "stop renewal", "b": "send refund request"},
                            "independence_evidence": {
                                "case_ref": "constructed-cancel-without-refund",
                                "source_anchor": "request.state.message",
                                "a_truth": True,
                                "b_truth": False,
                            },
                        }
                    ]
                }
            }
        },
    }


def report(a, b, probabilities=None, document=None):
    document = document if document is not None else paired_candidate()
    receipt = deepcopy(review_requests(document)[0])
    receipt["response_model"] = "jev-test"
    receipt["response"] = {
        "model": "jev-test",
        "answers": {
            key: {"type": "noul", "noul": (probabilities or {}).get(key, 0.01)}
            for key in receipt["submitted"]["questions"]
        },
    }
    for side, probability in (("a", a), ("b", b)):
        receipt["response"]["answers"][f"atomicity_requires_proposition_{side}__0"]["noul"] = probability
    signals = review_signals([receipt], {"question": check_metadata("question")})
    return guard_report(
        document=document,
        receipts=[receipt],
        signals=signals,
        route_policy=routing_policy(0.2, 0.8),
        score_policy=scoring_policy(),
        candidate_request_sha256="fixture",
    )


@pytest.mark.parametrize("a,b", [(0.95, 0.05), (0.05, 0.95), (0.05, 0.05)])
def test_one_required_proposition_does_not_trigger_a_bundling_repair(a, b):
    result = report(a, b)
    assert result["route"] == "ready_for_small_trial_questions_only"
    assert result["policy_conclusions"]["critical_conditions"] == []
    assert result["atomicity_assessments"][0]["minimum_support_index"] == 0.05
    raw = [item for item in result["feedback"] if item["check"].startswith("atomicity_requires")]
    assert all(item["recommended_action"] is None for item in raw)
    assert result["scoring"]["request"]["design_score"] == 98.2


def test_both_required_propositions_expose_code_composition_and_specific_repair():
    result = report(0.95, 0.91)
    assert result["route"] == "revise_questions"
    assessment = result["atomicity_assessments"][0]
    assert assessment["minimum_support_index"] == 0.91
    assert "probability" not in assessment
    assert list(assessment["inputs"].values()) == [0.95, 0.91]
    finding = next(item for item in result["feedback"] if item["check"] == "requires_both_independent_propositions")
    assert finding["evidence_status"] == "code_composed"
    assert finding["recommended_action"] == "split_required_outputs"
    assert "stop renewal" in finding["message"]
    assert "send refund request" in finding["message"]
    assert finding["principle_references"]


def test_uncertain_pair_is_visible_without_automatic_repair():
    result = report(0.95, 0.5)
    assert result["route"] == "review_required"
    assert result["policy_conclusions"]["critical_conditions"] == []
    assert result["policy_conclusions"]["uncertain_conditions"][0]["minimum_support_index"] == 0.5


def test_combined_feedback_resolves_each_pair_and_its_actual_model_observations():
    document = paired_candidate()
    document["questions"]["cancel_and_refund"]["instructions"] = (
        "Does `message` request cancellation, a refund, and an emailed receipt?"
    )
    pairs = document["review_context"]["questions"]["cancel_and_refund"]["atomicity_pairs"]
    second = deepcopy(pairs[0])
    second["pair_id"] = "cancel_receipt"
    second["proposition_b"].update(id="receipt", text="The message requests an emailed receipt.")
    second["consumer_outputs"]["b"] = "email receipt"
    pairs.append(second)
    result = report(0.95, 0.91, document=document)
    observations = {item["observation_id"]: item for item in result["model_observations"]}
    assessments = {item["assessment_id"]: item for item in result["atomicity_assessments"]}
    assert len(assessments) == 2
    feedback = [item for item in result["feedback"] if item["evidence_status"] == "code_composed"]
    assert len(feedback) == 2
    for item in feedback:
        assert "observation_id" not in item
        assessment = assessments[item["assessment_id"]]
        assert item["pair_id"] == assessment["pair_id"]
        assert len(assessment["input_observation_ids"]) == 2
        inputs = [observations[identity] for identity in assessment["input_observation_ids"]]
        assert assessment["minimum_support_index"] == min(value["probability"] for value in inputs)
        assert {value["check_id"] for value in inputs} == set(assessment["inputs"])


def test_atomicity_feedback_targets_the_named_proposition_instead_of_a_state_component():
    result = report(0.95, 0.91)
    observations = [item for item in result["model_observations"] if item["check_id"].startswith("atomicity_requires")]
    assert [item["inspection_target"]["path"] for item in observations] == [
        "atomicity_pairs[0].proposition_a.text",
        "atomicity_pairs[0].proposition_b.text",
    ]


def test_design_index_can_remain_high_while_required_evidence_stops_the_trial():
    low = report(0.05, 0.05)
    elevated = report(0.05, 0.05, {"requires_missing_case_fact": 0.81})
    assert 80 < elevated["scoring"]["request"]["design_score"] < low["scoring"]["request"]["design_score"]
    assert elevated["route"] == "gather_evidence"
    assert any(
        finding["check"] == "requires_missing_case_fact"
        for finding in elevated["policy_conclusions"]["critical_conditions"]
    )


def test_advisory_condition_model_and_cache_identity_cannot_downgrade_core_route():
    document = paired_candidate()
    document["questions"]["cancel_and_refund"]["criteria"] = {
        "true": "The message requests cancellation and a refund.",
        "false": "Neither is requested.",
    }
    document["review_context"]["questions"]["cancel_and_refund"]["criteria_conditions"] = [
        {
            "condition_id": "refund",
            "condition": "A refund is requested.",
            "source_path": "candidate_question.criteria.true",
            "source_quote": "refund",
        }
    ]
    receipts = []
    for prepared in review_requests(document):
        if "submitted" not in prepared:
            continue
        receipt = deepcopy(prepared)
        advisory = receipt["scope"] == "criteria_condition"
        receipt["response_model"] = "jev-advisory" if advisory else "jev-core"
        receipt["guard_source"] = "reused" if advisory else "fresh"
        receipt["response"] = {
            "model": receipt["response_model"],
            "answers": {key: {"type": "noul", "noul": 0.01} for key in receipt["submitted"]["questions"]},
        }
        receipts.append(receipt)
    signals = review_signals(receipts, {scope: check_metadata(scope) for scope in ("question", "criteria_condition")})
    result = guard_report(
        document=document,
        receipts=receipts,
        signals=signals,
        route_policy=routing_policy(0.2, 0.8),
        score_policy=scoring_policy(),
        candidate_request_sha256="fixture",
    )
    assert result["route"] == "ready_for_small_trial_questions_only"
    assert result["policy_conclusions"]["served_models"] == ["jev-core"]
    assert result["policy_conclusions"]["all_observation_served_models"] == ["jev-advisory", "jev-core"]
    assert result["policy_conclusions"]["reused_alias_version_unverified"] is False
    assert result["policy_conclusions"]["mixed_served_models"] is False
    (comparison,) = result["criteria_condition_assessments"]
    assert comparison["outcome"] == "same_requirement"
    assert result["scoring"]["request"]["design_score"] == report(0.01, 0.01)["scoring"]["request"]["design_score"]
