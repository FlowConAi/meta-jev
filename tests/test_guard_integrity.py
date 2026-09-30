from __future__ import annotations

import pytest

from system_one_meta_builder.guard import (
    guard_report,
    review_signals,
    routing_policy,
    scoring_policy,
    validate_review_receipt,
)
from system_one_meta_builder.io import InputError
from system_one_meta_builder.receipts import review_binding_id
from system_one_meta_builder.review import check_metadata, review_requests


def _review_receipt(question_id: str, model: str | None, probability: float, source: str) -> tuple[dict, dict]:
    check_id = "question_reference_is_ambiguous"
    fingerprint = f"review-{question_id}"
    receipt = {
        "scope": "question",
        "candidate_question_id": question_id,
        "review_fingerprint": fingerprint,
        "request_sha256": f"request-{question_id}",
        "submitted": {"questions": {check_id: {}}},
    }
    signal = {
        "scope": "question",
        "candidate_question_id": question_id,
        "check_id": check_id,
        "probability": probability,
        "dimension": "question_clarity",
        "review_fingerprint": fingerprint,
        "response_model": model,
        "review_binding_id": review_binding_id(receipt),
        "source": source,
    }
    return receipt, signal


def test_mixed_concrete_models_are_visible_and_cannot_route_green() -> None:
    first_receipt, first_signal = _review_receipt("first", "jev-1.12.0", 0.05, "reused")
    second_receipt, second_signal = _review_receipt("second", "jev-1.13.0", 0.05, "fresh")
    report = guard_report(
        document={"request": {"state": {}, "questions": {}}},
        receipts=[first_receipt, second_receipt],
        signals=[first_signal, second_signal],
        route_policy=routing_policy(0.2, 0.8),
        score_policy=scoring_policy(),
        candidate_request_sha256="candidate",
    )

    assert report["route"] == "review_required"
    assert report["policy_conclusions"]["served_models"] == ["jev-1.12.0", "jev-1.13.0"]
    assert report["policy_conclusions"]["mixed_served_models"] is True
    assert any(
        item.get("reason") == "review responses came from different concrete model versions"
        for item in report["policy_conclusions"]["missing_information"]
    )


def test_uncertain_observations_remain_visible_alongside_composite_score() -> None:
    receipt, signal = _review_receipt("candidate", "jev-1.13.0", 0.5, "fresh")
    report = guard_report(
        document={"request": {"state": {}, "questions": {}}},
        receipts=[receipt],
        signals=[signal],
        route_policy=routing_policy(0.2, 0.8),
        score_policy=scoring_policy(),
        candidate_request_sha256="candidate",
    )

    assert report["route"] == "review_required"
    assert report["policy_conclusions"]["uncertain_conditions"] == [
        {
            "question": "candidate",
            "check": "question_reference_is_ambiguous",
            "probability": 0.5,
        }
    ]


def test_missing_concrete_response_model_cannot_route_green() -> None:
    receipt, signal = _review_receipt("candidate", None, 0.05, "reused")
    report = guard_report(
        document={"request": {"state": {}, "questions": {}}},
        receipts=[receipt],
        signals=[signal],
        route_policy=routing_policy(0.2, 0.8),
        score_policy=scoring_policy(),
        candidate_request_sha256="candidate",
    )

    assert report["route"] == "review_required"
    assert report["policy_conclusions"]["served_models"] == []
    assert report["policy_conclusions"]["missing_response_model_observations"] == 1
    assert any(
        item.get("reason") == "one or more review observations have no concrete response model"
        for item in report["policy_conclusions"]["missing_information"]
    )


def _prepared_report(policy_path: str, *, reused: bool = False) -> dict:
    document = {
        "state": {"message": "refund", "policy": {"rule": "allow refunds"}},
        "questions": {"allowed": {"type": "noul", "instructions": f"Does `message` satisfy `{policy_path}`?"}},
    }
    receipt = review_requests(document)[0]
    receipt.update(
        {
            "response_model": "jev-1.13.0",
            "guard_source": "reused" if reused else "fresh",
            "response": {
                "model": "jev-1.13.0",
                "answers": {key: {"type": "noul", "noul": 0.01} for key in receipt["submitted"]["questions"]},
            },
        }
    )
    signals = review_signals([receipt], {"question": check_metadata("question")})
    return guard_report(
        document=document,
        receipts=[receipt],
        signals=signals,
        route_policy=routing_policy(0.2, 0.8),
        score_policy=scoring_policy(),
        candidate_request_sha256="candidate",
    )


def test_unresolved_reference_cannot_be_hidden_by_clear_review_answers() -> None:
    report = _prepared_report("polciy.rule")
    assert report["route"] == "review_required"
    assert report["scoring"]["request"]["status"] == "incomplete"
    assert report["scoring"]["request"]["design_score"] is None
    assert report["policy_conclusions"]["missing_information"][0]["unresolved_backticked_paths"] == ["polciy.rule"]


def test_resolved_references_do_not_hide_unreviewed_atomicity() -> None:
    report = _prepared_report("policy.rule")
    assert report["route"] == "review_required"
    assert report["scoring"]["request"]["design_score"] is None
    assert report["scoring"]["questions"][0]["coverage"]["missing_dimensions"] == ["atomicity"]


def test_reused_alias_receipt_does_not_claim_current_model_readiness() -> None:
    report = _prepared_report("policy.rule", reused=True)
    assert report["route"] == "review_required"
    assert report["policy_conclusions"]["reused_alias_version_unverified"] is True
    assert report["scoring"]["request"]["design_score"] is None


@pytest.mark.parametrize("recorded_model", [None, "jev-1.12.0"])
def test_receipt_cannot_mislabel_the_provider_model(recorded_model: str | None) -> None:
    receipt = review_requests(
        {"state": "hello", "questions": {"greeting": {"type": "noul", "instructions": "Is this a greeting?"}}}
    )[0]
    receipt["response"] = {
        "model": "jev-1.13.0",
        "answers": {key: {"type": "noul", "noul": 0.01} for key in receipt["submitted"]["questions"]},
    }
    receipt["response_model"] = recorded_model
    with pytest.raises(InputError, match="response model"):
        validate_review_receipt(receipt)
