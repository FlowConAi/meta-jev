from __future__ import annotations

import json
from pathlib import Path

import pytest
from typesafe_sdk import TypeSafeError

from system_one_meta_builder import cli
from system_one_meta_builder.guard import (
    SCORING_POLICY_VERSION,
    actionable_feedback,
    reusable_reviews,
    route,
    routing_policy,
    score_reviews,
    scoring_policy,
)
from system_one_meta_builder.io import json_line
from system_one_meta_builder.receipts import request_sha256, review_binding_id, success_receipt
from system_one_meta_builder.review import PER_QUESTION_CHECKS, review_requests


def _candidate(state: str = "cancel it") -> dict:
    return {
        "request": {
            "state": {"message": state},
            "questions": {
                "cancel": {
                    "type": "noul",
                    "instructions": "Does `message` ask to cancel?",
                    "criteria": {"true": "Cancellation requested", "false": "Not requested"},
                }
            },
        }
    }


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _low_response(submitted: dict) -> dict:
    return {
        "model": "jev-1.13.0",
        "answers": {name: {"type": "noul", "noul": 0.05} for name in submitted["questions"]},
        "usage": {"input_tokens": 10, "output_tokens": 3},
    }


def test_review_failure_is_appended_and_returns_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "receipts.jsonl"
    _write(candidate, _candidate())

    def fail_call(*_args: object, **_kwargs: object) -> object:
        raise TypeSafeError("provider unavailable")

    monkeypatch.setattr(cli, "call_once", fail_call)
    assert cli.main(["review", str(candidate), "--output", str(output)]) == 1
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    attempt = [row for row in rows if row.get("attempt_id")]
    assert [row["status"] for row in attempt] == ["started", "error"]
    assert attempt[0]["attempt_id"] == attempt[1]["attempt_id"]
    assert attempt[1]["kind"] == "review"
    assert attempt[1]["error"]["type"] == "TypeSafeError"
    assert any(row["status"] == "not_reviewed" for row in rows)


def test_guard_reuses_only_exact_successful_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = _candidate()
    prepared = review_requests(document)
    item = prepared[0]
    reused = success_receipt(
        kind="review",
        submitted=item["submitted"],
        response=_low_response(item["submitted"]),
        seconds=0.1,
        scope="question",
        candidate_question_id="cancel",
        review_fingerprint=item["review_fingerprint"],
    )
    prior = tmp_path / "prior.jsonl"
    prior.write_text(json_line(reused) + "\n", encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "guard.jsonl"
    _write(candidate, document)

    def unexpected_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("exact successful review should have been reused")

    monkeypatch.setattr(cli, "call_once", unexpected_call)
    assert (
        cli.main(
            [
                "guard",
                str(candidate),
                "--output",
                str(output),
                "--reuse",
                str(prior),
                "--clear-below",
                "0.2",
                "--flag-at",
                "0.8",
            ]
        )
        == 3
    )
    report = json.loads(output.read_text(encoding="utf-8").splitlines()[-1])
    assert report["route"] == "review_required"
    assert report["policy_conclusions"]["reused_alias_version_unverified"] is True
    assert "signals" not in report
    assert {signal["source"] for signal in report["model_observations"]} == {"reused"}
    assert {signal["response_model"] for signal in report["model_observations"]} == {"jev-1.13.0"}
    assert set(report["dimensions"]) == {
        "question_clarity",
        "state_clarity",
        "primitive_suitability",
        "evidence_sufficiency",
        "task_suitability",
    }
    assert report["model_observations"][0]["typed_answer"] == {"type": "noul", "noul": 0.05}
    assert all(
        report["principles"][source["content_id"]]["id"] == source["id"]
        for observation in report["model_observations"]
        for source in observation["principle_references"]
    )
    assert report["scoring"]["policy"]["version"] == SCORING_POLICY_VERSION
    assert report["scoring"]["workflow"]["status"] == "not_reviewed"
    assert len(report["candidate_request_sha256"]) == 64
    assert report["policy_conclusions"]["recommended_next_action"] == "review_required"
    assert {item["disposition"] for item in report["feedback"]} == {"not_flagged"}
    assert all(item["recommended_action"] is None for item in report["feedback"])


def test_changed_state_invalidates_review_and_error_receipt_is_not_reusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _candidate()
    item = review_requests(original)[0]
    failed = {
        "kind": "review",
        "status": "error",
        "review_fingerprint": item["review_fingerprint"],
    }
    assert reusable_reviews([failed]) == {}

    changed = tmp_path / "changed.json"
    prior = tmp_path / "prior.jsonl"
    output = tmp_path / "output.jsonl"
    _write(changed, _candidate("please keep it"))
    prior.write_text(json_line(failed) + "\n", encoding="utf-8")
    calls = 0

    def fresh_call(submitted: dict, _questions: dict, **_kwargs: object) -> tuple[dict, float]:
        nonlocal calls
        calls += 1
        return _low_response(submitted), 0.2

    monkeypatch.setattr(cli, "call_once", fresh_call)
    assert cli.main(["guard", str(changed), "--output", str(output), "--reuse", str(prior)]) == 3
    assert calls == 1


def test_review_fingerprint_covers_candidate_model_and_reviewer_rubric(monkeypatch: pytest.MonkeyPatch) -> None:
    original = review_requests(_candidate())[0]["review_fingerprint"]
    changed_state = review_requests(_candidate("please keep it"))[0]["review_fingerprint"]
    changed_question = _candidate()
    changed_question["request"]["questions"]["cancel"]["instructions"] = "Does `message` forbid cancellation?"
    changed_question_fingerprint = review_requests(changed_question)[0]["review_fingerprint"]
    changed_model = review_requests(_candidate(), "jev-pinned-version")[0]["review_fingerprint"]

    changed_rubric = dict(PER_QUESTION_CHECKS["question_reference_is_ambiguous"])
    changed_rubric["criteria"] = {
        "true": {"what": "Two independently variable judgments are forced into one answer."},
        "false": {"what": "Exactly one judgment is requested."},
    }
    monkeypatch.setitem(PER_QUESTION_CHECKS, "question_reference_is_ambiguous", changed_rubric)
    changed_rubric_fingerprint = review_requests(_candidate())[0]["review_fingerprint"]

    assert (
        len(
            {
                original,
                changed_state,
                changed_question_fingerprint,
                changed_model,
                changed_rubric_fingerprint,
            }
        )
        == 5
    )


def test_guard_checks_output_before_provider_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = tmp_path / "candidate.json"
    _write(candidate, _candidate())
    called = False

    def paid_call(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(cli, "call_once", paid_call)
    assert cli.main(["guard", str(candidate), "--output", str(tmp_path)]) == 2
    assert called is False


@pytest.mark.parametrize("mutation", ["empty_answers", "missing_answer", "changed_submitted", "boolean_probability"])
def test_malformed_cached_review_fails_locally_without_calling_provider(
    mutation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _candidate()
    item = review_requests(document)[0]
    cached = success_receipt(
        kind="review",
        submitted=item["submitted"],
        response=_low_response(item["submitted"]),
        seconds=0.1,
        scope="question",
        candidate_question_id="cancel",
        review_fingerprint=item["review_fingerprint"],
    )
    if mutation == "empty_answers":
        cached["response"]["answers"] = {}
    elif mutation == "missing_answer":
        cached["response"]["answers"].pop(next(iter(cached["response"]["answers"])))
    elif mutation == "changed_submitted":
        cached["submitted"]["state"]["request_state"] = {"message": "changed after review"}
    else:
        first_answer = next(iter(cached["response"]["answers"].values()))
        first_answer["noul"] = True

    candidate = tmp_path / "candidate.json"
    prior = tmp_path / "prior.jsonl"
    output = tmp_path / "guard.jsonl"
    _write(candidate, document)
    prior.write_text(json_line(cached) + "\n", encoding="utf-8")
    called = False

    def paid_call(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("malformed cache must fail before a provider call")

    monkeypatch.setattr(cli, "call_once", paid_call)
    assert cli.main(["guard", str(candidate), "--output", str(output), "--reuse", str(prior)]) == 2
    assert called is False


def test_fresh_review_with_missing_answers_is_an_error_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "guard.jsonl"
    _write(candidate, _candidate())

    def incomplete_response(submitted: dict, _questions: dict, **_kwargs: object) -> tuple[dict, float]:
        response = _low_response(submitted)
        response["answers"] = {}
        return response, 0.1

    monkeypatch.setattr(cli, "call_once", incomplete_response)
    assert cli.main(["guard", str(candidate), "--output", str(output)]) == 1
    receipt = next(
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("status") == "invalid_response"
    )
    assert receipt["response"]["answers"] == {}
    assert receipt["error"]["type"] == "InputError"


def test_missing_atomicity_coverage_does_not_hide_critical_evidence_signal() -> None:
    receipt = {
        "scope": "question",
        "candidate_question_id": "candidate",
        "review_fingerprint": "review-1",
        "submitted": {"questions": {"requires_missing_case_fact": {}}},
    }
    signals = [
        {
            "scope": "question",
            "candidate_question_id": "candidate",
            "check_id": "requires_missing_case_fact",
            "probability": 0.81,
            "dimension": "evidence_sufficiency",
            "review_fingerprint": "review-1",
            "review_binding_id": review_binding_id(receipt),
        }
    ]
    scored = score_reviews([receipt], signals, scoring_policy())
    assert scored["request"]["design_score"] is None
    assert "atomicity" in scored["questions"][0]["coverage"]["missing_dimensions"]
    assert route(signals, routing_policy(0.2, 0.8)) == "gather_evidence"


@pytest.mark.parametrize(
    "threshold_args",
    [
        ["--clear-below", "0.2"],
        ["--flag-at", "0.8"],
        ["--clear-below", "0.8", "--flag-at", "0.2"],
        ["--clear-below", "nan", "--flag-at", "0.8"],
        ["--clear-below", "0.2", "--flag-at", "nan"],
    ],
)
def test_invalid_routing_thresholds_fail_before_provider_call(
    threshold_args: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "guard.jsonl"
    _write(candidate, _candidate())
    called = False

    def paid_call(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("invalid thresholds must fail before a provider call")

    monkeypatch.setattr(cli, "call_once", paid_call)
    assert cli.main(["guard", str(candidate), "--output", str(output), *threshold_args]) == 2
    assert called is False
    assert not output.exists()


def test_feedback_disposition_distinguishes_repairs_from_raw_observations() -> None:
    signals = [
        {
            "scope": "question",
            "candidate_question_id": "q",
            "check_id": "question_reference_is_ambiguous",
            "probability": probability,
            "dimension": "question_clarity",
            "source": "fresh",
        }
        for probability in (0.1, 0.5, 0.9)
    ]
    thresholded = actionable_feedback(signals, routing_policy(0.2, 0.8))
    assert [item["disposition"] for item in thresholded] == ["not_flagged", "uncertain", "flagged"]
    assert [item["recommended_action"] for item in thresholded] == [None, None, "identify_question_reference"]
    unthresholded = actionable_feedback(signals[:1], routing_policy(None, None))
    assert unthresholded[0]["disposition"] == "unthresholded"
    assert unthresholded[0]["recommended_action"] is None


def test_feedback_preserves_a_string_review_instruction_as_the_proposition() -> None:
    signal = {
        "scope": "question",
        "candidate_question_id": "q",
        "check_id": "question_reference_is_ambiguous",
        "probability": 0.5,
        "dimension": "question_clarity",
        "source": "fresh",
        "review_context": {
            "review_question": {"type": "noul", "instructions": "Is the exact reference ambiguous?"},
            "scope_limit": None,
            "request_state_reference": {"sha256": "state"},
        },
    }
    feedback = actionable_feedback([signal], routing_policy(None, None))[0]
    assert feedback["reviewed_proposition"] == "Is the exact reference ambiguous?"


def test_invalid_scoring_policy_fails_before_provider_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = tmp_path / "candidate.json"
    policy = tmp_path / "policy.json"
    output = tmp_path / "guard.jsonl"
    _write(candidate, _candidate())
    _write(policy, {"question_dimension_weights": {"atomicity": 1.0}})
    called = False

    def paid_call(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(cli, "call_once", paid_call)
    assert cli.main(["guard", str(candidate), "--output", str(output), "--policy", str(policy)]) == 2
    assert called is False


def test_request_sha256_uses_state_and_questions_only() -> None:
    submitted = {
        "state": {"café": "München"},
        "questions": {"q": {"type": "noul", "instructions": "Hi"}},
        "model": "jev-latest",
    }
    assert request_sha256(submitted) == "d1e55e3ff973edcaf2ad4d0b1657c5a9be0a4e8db906806d7f38e2e26c323fed"
    assert request_sha256({**submitted, "model": "jev-1.13.0"}) == request_sha256(submitted)


def test_workflow_weighting_score_stays_separate_from_question_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _candidate()
    document["workflow"] = {
        "purpose": "Queue low-preservation cases for review using a documented policy.",
        "consumer_code": 'risk = answers["cancel"].noul * 0.7; queue_review(risk)',
    }
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "guard.jsonl"
    _write(candidate, document)

    def response(submitted: dict, _questions: dict, **_kwargs: object) -> tuple[dict, float]:
        raw = _low_response(submitted)
        for check_id, answer in raw["answers"].items():
            if check_id.startswith("answer_weights_lack_explicit_policy__"):
                answer["noul"] = 0.9
        return raw, 0.1

    monkeypatch.setattr(cli, "call_once", response)
    assert (
        cli.main(
            [
                "guard",
                str(candidate),
                "--output",
                str(output),
                "--clear-below",
                "0.2",
                "--flag-at",
                "0.8",
            ]
        )
        == 3
    )
    report = json.loads(output.read_text(encoding="utf-8").splitlines()[-1])
    assert report["route"] == "review_integration"
    assert report["scoring"]["request"]["design_score"] is None
    assert report["scoring"]["questions"][0]["coverage"]["missing_dimensions"] == ["atomicity"]
    assert report["scoring"]["workflow"]["score"] == 61.0
    assert report["scoring"]["workflow"]["dimensions"]["workflow_weighting"]["risk"] == 0.9
