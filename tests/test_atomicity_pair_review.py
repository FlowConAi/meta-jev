from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from system_one_meta_builder.io import InputError
from system_one_meta_builder.preflight import code_preflight
from system_one_meta_builder.review import review_requests

LABELLED_ROOT = Path(__file__).parents[1] / "examples" / "labelled-question-design"


PAIR = {
    "pair_id": "mechanism_and_impact",
    "proposition_a": {
        "id": "mechanism_present",
        "text": "The source contains the mechanism described by the finding.",
        "source_anchor": "finding.mechanism",
    },
    "proposition_b": {
        "id": "claimed_impact_occurs",
        "text": "The mechanism causes the impact claimed by the finding.",
        "source_anchor": "finding.impact",
    },
    "consumer_outputs": {
        "a": "Report whether the named mechanism is present.",
        "b": "Report whether the claimed impact follows.",
    },
    "independence_evidence": {
        "case_ref": "mechanism_without_claimed_impact",
        "source_anchor": "labelled-question-design/labels.json#mechanism_without_claimed_impact",
        "a_truth": True,
        "b_truth": False,
    },
}


def _document(question_id: str, instructions: str) -> dict:
    return {
        "request": {
            "state": {"source": "The named call is present, but the guarded return prevents the claimed impact."},
            "questions": {question_id: {"type": "noul", "instructions": instructions}},
        },
        "intended_uses": {question_id: "Keep mechanism presence and claimed impact as separate consumer outputs."},
        "review_context": {"questions": {question_id: {"atomicity_pairs": [deepcopy(PAIR)]}}},
    }


def test_matched_broad_and_narrow_questions_submit_the_same_unlabelled_pair() -> None:
    broad = review_requests(
        _document(
            "defect_present",
            "Is the defect described by the finding present in `source`?",
        )
    )[0]
    narrow = review_requests(
        _document(
            "mechanism_shown",
            "Does `source` contain the mechanism described by the finding?",
        )
    )[0]

    for prepared in (broad, narrow):
        questions = prepared["submitted"]["questions"]
        assert {
            "atomicity_requires_proposition_a__0",
            "atomicity_requires_proposition_b__0",
        } <= set(questions)
        for check_id in (
            "atomicity_requires_proposition_a__0",
            "atomicity_requires_proposition_b__0",
        ):
            assert "selected_atomicity_pair" not in questions[check_id]["instructions"]
        assert prepared["submitted"]["state"]["atomicity_pairs"] == [
            {
                "proposition_a": {"id": PAIR["proposition_a"]["id"], "text": PAIR["proposition_a"]["text"]},
                "proposition_b": {"id": PAIR["proposition_b"]["id"], "text": PAIR["proposition_b"]["text"]},
            }
        ]
        assert "consumer_outputs" not in prepared["submitted"]["state"]["atomicity_pairs"][0]
        assert "independence_evidence" not in prepared["submitted"]["state"]["atomicity_pairs"][0]
        assert prepared["atomicity_pair_coverage"] == {"status": "reviewed", "pairs": [PAIR]}


def test_missing_pair_is_explicitly_not_reviewed_without_a_generic_atomicity_question() -> None:
    document = _document("mechanism_shown", "Does `source` contain the named mechanism?")
    del document["review_context"]

    prepared = review_requests(document)[0]

    assert prepared["atomicity_pair_coverage"] == {"status": "not_reviewed", "pairs": []}
    assert "atomicity_pair_review" in prepared["skipped_checks"]
    assert not {
        check_id
        for check_id in prepared["submitted"]["questions"]
        if check_id.startswith("atomicity_") or check_id == "collapses_independent_properties"
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda pair: pair["consumer_outputs"].pop("b"),
            "consumer_outputs.b must be a nonempty string",
        ),
        (
            lambda pair: pair["independence_evidence"].update({"b_truth": True}),
            "independence_evidence must be a mixed-truth case",
        ),
        (
            lambda pair: pair["proposition_a"].update({"source_anchor": ""}),
            "proposition_a.source_anchor must be a nonempty string",
        ),
        (
            lambda pair: pair["proposition_b"].update({"id": "mechanism_present"}),
            "must name two distinct propositions",
        ),
        (
            lambda pair: pair["consumer_outputs"].update({"b": "Report whether the named mechanism is present."}),
            "consumer_outputs must name two distinct outputs or actions",
        ),
    ],
)
def test_invalid_or_unsubstantiated_pair_is_rejected(mutate, message: str) -> None:
    document = _document("defect_present", "Is the described defect present in `source`?")
    pair = document["review_context"]["questions"]["defect_present"]["atomicity_pairs"][0]
    mutate(pair)

    with pytest.raises(InputError, match=message):
        review_requests(document)


def test_labelled_set_keeps_labels_outside_candidates_and_uses_matched_pairs() -> None:
    labels = json.loads((LABELLED_ROOT / "labels.json").read_text())
    grouped_pairs: dict[str, list[dict]] = {}
    expected_by_group: dict[str, set[bool]] = {}

    for case in labels["cases"]:
        candidate = json.loads((LABELLED_ROOT / case["candidate"]).read_text())
        assert "expected_requires_both_independent_propositions" not in json.dumps(candidate)
        question_id = next(iter(candidate["request"]["questions"]))
        pair = candidate["review_context"]["questions"][question_id]["atomicity_pairs"][0]
        grouped_pairs.setdefault(case["group"], []).append(pair)
        expected_by_group.setdefault(case["group"], set()).add(case["expected_requires_both_independent_propositions"])

        prepared = review_requests(candidate)[0]
        assert prepared["atomicity_pair_coverage"]["status"] == "reviewed"
        assert prepared["state_path_coverage"]["review_question_unresolved_paths"] == []
        assert {
            "atomicity_requires_proposition_a__0",
            "atomicity_requires_proposition_b__0",
        } <= set(prepared["submitted"]["questions"])
        preflight = code_preflight(candidate, [prepared], request_sha256="offline-test")
        assert preflight["route"] == "review_required"
        assert not [finding for finding in preflight["findings"] if finding["severity"] == "error"]

    assert expected_by_group and all(expected == {False, True} for expected in expected_by_group.values())
    assert all(pairs and all(pair == pairs[0] for pair in pairs[1:]) for pairs in grouped_pairs.values())
