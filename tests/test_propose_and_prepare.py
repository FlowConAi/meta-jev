from __future__ import annotations

from jsonschema import Draft202012Validator

from system_one_meta_builder.io import InputError, loads_json
from system_one_meta_builder.propose import proposal_brief
from system_one_meta_builder.review import review_requests


def test_proposal_contract_resolves_official_question_schema() -> None:
    brief = proposal_brief(
        question="Which parts of this request need independent answers?",
        goal=None,
        setup=None,
        evidence=[],
    )
    contract = brief["candidate_contract"]
    Draft202012Validator.check_schema(contract)
    Draft202012Validator(contract).validate(
        {
            "request": {
                "state": {"request": "Cancel the order"},
                "questions": {
                    "asks_to_cancel": {
                        "type": "noul",
                        "instructions": {"question": "Does `request` ask to cancel the order?"},
                        "criteria": {
                            "true": {"what": "Cancellation is requested"},
                            "false": {"what": "Cancellation is not requested"},
                        },
                    },
                    "route": {
                        "type": "choice",
                        "instructions": "Which route applies?",
                        "criteria": {"orders": None, "billing": None},
                    },
                },
            }
        }
    )


def test_prepare_preserves_structured_fields_and_skips_inapplicable_checks() -> None:
    document = {
        "request": {
            "state": {"message": "Please cancel"},
            "questions": {
                "cancel": {
                    "type": "noul",
                    "instructions": {
                        "question": "Does `message` ask to cancel?",
                        "inspect": "message",
                    },
                }
            },
        }
    }
    prepared = review_requests(document)
    question_review = prepared[0]
    assert question_review["submitted"]["state"]["candidate_question"]["instructions"] == {
        "question": "Does `message` ask to cancel?",
        "inspect": "message",
    }
    assert "has_conflicting_criteria" not in question_review["submitted"]["questions"]
    assert "choice_has_nonexclusive_properties" not in question_review["submitted"]["questions"]
    assert question_review["skipped_checks"]["has_conflicting_criteria"]
    assert question_review["submitted"]["state"]["principles"]
    assert all(
        set(principle) == {"rule", "source_excerpt"}
        for principle in question_review["submitted"]["state"]["principles"].values()
    )
    assert all("source_url" in source for source in question_review["principle_provenance"].values())
    assert all("source_path" in source for source in question_review["principle_provenance"].values())
    assert all("passage_kind" in source for source in question_review["principle_provenance"].values())
    assert question_review["atomicity_pair_coverage"]["status"] == "not_reviewed"
    assert prepared[-1]["status"] == "not_reviewed"


def test_duplicate_question_key_is_rejected_before_validation() -> None:
    payload = '{"request":{"state":{},"questions":{"q":{"type":"noul"},"q":{"type":"noul"}}}}'
    try:
        loads_json(payload)
    except InputError as error:
        assert error.args == ("duplicate JSON key: 'q'",)
    else:  # pragma: no cover - makes the behavioral claim explicit
        raise AssertionError("duplicate JSON key was accepted")
