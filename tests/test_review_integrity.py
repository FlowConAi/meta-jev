from __future__ import annotations

from system_one_meta_builder.review import (
    ATOMICITY_PAIR_CHECKS,
    PER_QUESTION_CHECKS,
    SEMANTIC_CONTRAST_CHECKS,
    STATE_COMPONENT_CHECKS,
    WORKFLOW_CHECKS,
    review_requests,
)


def _noul_document() -> dict:
    return {
        "request": {
            "state": {
                "record": {"text": "Retain the cause", "count": 4, "period": "week"},
                "policy": {"required": "The diagnostic names the failure cause."},
            },
            "questions": {
                "diagnostic": {
                    "type": "noul",
                    "instructions": ("Does `record.text` satisfy `policy.required` and is it complete?"),
                    "criteria": {
                        "true": {"what": "The diagnostic satisfies the requirement."},
                        "false": {"what": "The diagnostic does not satisfy the requirement."},
                    },
                }
            },
        },
        "intended_uses": {"diagnostic": "Route each independently failed diagnostic obligation to an engineer."},
        "review_context": {
            "questions": {
                "diagnostic": {
                    "atomicity_pairs": [
                        {
                            "pair_id": "requirement_and_completeness",
                            "proposition_a": {
                                "id": "requirement_satisfied",
                                "text": "The diagnostic satisfies `policy.required`.",
                                "source_anchor": "request.questions.diagnostic.instructions",
                            },
                            "proposition_b": {
                                "id": "diagnostic_complete",
                                "text": "The diagnostic is complete.",
                                "source_anchor": "request.questions.diagnostic.instructions",
                            },
                            "consumer_outputs": {
                                "a": "Route a failed policy requirement to its owner.",
                                "b": "Route an incomplete diagnostic to its owner.",
                            },
                            "independence_evidence": {
                                "case_ref": "diagnostic_missing_context",
                                "source_anchor": "tests/test_review_integrity.py::_noul_document",
                                "a_truth": True,
                                "b_truth": False,
                            },
                        }
                    ]
                }
            }
        },
    }


def test_question_reviewer_sees_the_actual_candidate_input_without_id_or_intended_use() -> None:
    document = _noul_document()
    prepared = review_requests(document)[0]
    state = prepared["submitted"]["state"]

    assert state["request_state"] == document["request"]["state"]
    assert state["candidate_question"] == document["request"]["questions"]["diagnostic"]
    assert "candidate_question_id" not in state
    assert "intended_use" not in state

    questions = prepared["submitted"]["questions"]
    atomicity = questions["atomicity_requires_proposition_a__0"]["instructions"]
    assert state["atomicity_pairs"] == [
        {
            "proposition_a": {"id": "requirement_satisfied", "text": "The diagnostic satisfies `policy.required`."},
            "proposition_b": {"id": "diagnostic_complete", "text": "The diagnostic is complete."},
        }
    ]
    assert atomicity["inspect"] == ["candidate_question", "atomicity_pairs[0].proposition_a.text"]
    assert "consumer_outputs" not in state["atomicity_pairs"][0]
    assert "independence_evidence" not in state["atomicity_pairs"][0]
    assert "candidate_intended_use" not in questions["question_wording_is_hard_to_understand"]["instructions"]
    assert prepared["state_path_coverage"]["review_question_unresolved_paths"] == []

    component_instructions = questions["state_component_role_is_unclear__0"]["instructions"]
    assert "`state_components[0]`" in component_instructions["question"]
    assert "selected_component" not in str(component_instructions)


def test_question_review_has_independent_comprehension_ambiguity_atomicity_and_state_checks() -> None:
    prepared = review_requests(_noul_document())[0]
    questions = prepared["submitted"]["questions"]

    expected = {
        "atomicity_requires_proposition_a__0",
        "atomicity_requires_proposition_b__0",
        "question_wording_is_hard_to_understand",
        "question_meaning_is_unrecoverable",
        "question_reference_is_ambiguous",
        "state_reference_target_is_ambiguous",
        "instructions_conflict_with_criteria",
    }
    assert expected <= set(questions)
    assert prepared["skipped_checks"]["decision_term_semantic_contrast"]
    assert "decision_term_is_ambiguous" not in questions

    component_paths = [component["path"] for component in prepared["submitted"]["state"]["state_components"]]
    assert component_paths == ["record.text", "policy.required"]
    for component_index in range(2):
        assert {
            f"state_component_wording_is_hard_to_understand__{component_index}",
            f"state_component_role_is_unclear__{component_index}",
            f"state_component_entity_is_unclear__{component_index}",
            f"state_component_unit_is_unclear__{component_index}",
            f"state_component_timeframe_is_unclear__{component_index}",
        } <= set(questions)


def test_meta_questions_define_both_sides_and_controls_in_structured_criteria() -> None:
    checks = {
        **ATOMICITY_PAIR_CHECKS,
        **SEMANTIC_CONTRAST_CHECKS,
        **PER_QUESTION_CHECKS,
        **STATE_COMPONENT_CHECKS,
        **WORKFLOW_CHECKS,
    }
    for check_id, check in checks.items():
        criteria = check["criteria"]
        assert set(criteria) == {"true", "false"}, check_id
        for side in ("true", "false"):
            assert set(criteria[side]) == {"what", "not_for", "examples"}, (check_id, side)
            assert criteria[side]["what"], (check_id, side)
            assert criteria[side]["examples"], (check_id, side)


def test_workflow_review_is_built_from_exact_python_answer_consumption_sites() -> None:
    document = {
        "request": {
            "state": {"message": "Preserve the cause and context."},
            "questions": {
                "cause_present": {
                    "type": "noul",
                    "instructions": "Does `message` name the cause?",
                },
                "context_present": {
                    "type": "noul",
                    "instructions": "Does `message` name the context?",
                },
            },
        },
        "workflow": {
            "language": "python",
            "purpose": "Publish only when both required facts are established.",
            "consumer_code": (
                'combined = answers["cause_present"].noul * answers["context_present"].noul\n'
                "if combined > threshold:\n"
                '    publish("complete")\n'
            ),
        },
    }

    workflow = next(item for item in review_requests(document) if item.get("scope") == "workflow")
    state = workflow["submitted"]["state"]
    assert state["workflow_coverage"]["status"] == "reviewed"
    assert state["consumer_sites"]
    assert {question_id for site in state["consumer_sites"] for question_id in site["relevant_questions"]} == {
        "cause_present",
        "context_present",
    }
    assert state["consumer_sites"][0]["downstream_uses"] == ["if combined > threshold:\n    publish('complete')"]
    assert workflow["state_path_coverage"]["review_question_unresolved_paths"] == []
    assert (
        "`consumer_sites[0]`"
        in workflow["submitted"]["questions"]["consumer_site_overclaims_evidence__0"]["instructions"]["question"]
    )
    assert "selected_site" not in str(workflow["submitted"]["questions"])
    assert "noul_product_claimed_joint_probability__0" in workflow["submitted"]["questions"]
    assert "required_condition_hidden_by_compensation__0" in workflow["submitted"]["questions"]


def test_non_python_consumer_is_explicitly_not_reviewed() -> None:
    document = _noul_document()
    document["workflow"] = {
        "language": "typescript",
        "purpose": "Route a result.",
        "consumer_code": "if (answer.noul > threshold) route();",
    }

    workflow = review_requests(document)[-1]
    assert workflow["status"] == "not_reviewed"
    assert workflow["reason"] == "workflow language 'typescript' is not supported; only Python is reviewed"
