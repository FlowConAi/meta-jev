from __future__ import annotations

from system_one_meta_builder.consumer import inspect_python_consumer

QUESTIONS = {
    "risk": {"type": "noul", "instructions": "Does the supplied message contain risk?"},
    "route": {"type": "choice", "instructions": "Which route applies?"},
}


def test_official_answer_roots_and_common_local_aliases_resolve_question_provenance() -> None:
    result = inspect_python_consumer(
        "\n".join(
            (
                "answer_map = response.answers",
                'risk_answer = answer_map["risk"]',
                'route_answer = answers.get("route")',
                "if risk_answer.noul > threshold:",
                "    publish(route_answer.confidence)",
            )
        ),
        QUESTIONS,
    )

    assert result["status"] == "reviewed"
    assert {
        (site["expression"], tuple(site["relevant_questions"]))
        for site in result["sites"]
        if site["kind"] == "answer_read"
    } == {
        ("risk_answer.noul", ("risk",)),
        ("route_answer.confidence", ("route",)),
    }


def test_foreign_attributes_and_shadowed_names_are_not_candidate_answers() -> None:
    result = inspect_python_consumer(
        "\n".join(
            (
                "def unrelated(risk):",
                "    return risk.noul",
                "foreign = metrics.risk.noul",
                'foreign_answer = metrics.answers["risk"].noul',
            )
        ),
        QUESTIONS,
    )

    assert result == {
        "status": "not_reviewed",
        "reason": "workflow.consumer_code has no resolvable typed-answer reads",
        "sites": [],
    }


def test_bare_question_name_is_not_enough_to_claim_answer_provenance() -> None:
    result = inspect_python_consumer("if risk.noul > threshold:\n    block()", QUESTIONS)

    assert result["status"] == "not_reviewed"
    assert result["sites"] == []


def test_canonical_answer_parameter_is_supported_but_a_local_shadow_is_not() -> None:
    supported = inspect_python_consumer(
        'def consume(answers):\n    return answers["risk"].noul',
        QUESTIONS,
    )
    shadowed = inspect_python_consumer(
        'def consume():\n    answers = metrics\n    return answers["risk"].noul',
        QUESTIONS,
    )

    assert supported["status"] == "reviewed"
    assert shadowed["status"] == "not_reviewed"


def test_dynamic_answer_lookup_is_explicitly_unreviewed_even_beside_a_resolved_read() -> None:
    result = inspect_python_consumer(
        "\n".join(
            (
                'known = response.answers["risk"]',
                "selected = response.answers[question_id]",
                "route(known.noul, selected.confidence)",
            )
        ),
        QUESTIONS,
    )

    assert result == {
        "status": "not_reviewed",
        "reason": "workflow.consumer_code has unresolved typed-answer reads at lines [3]",
        "sites": [],
    }


def test_control_flow_alias_with_different_possible_answer_sources_is_unreviewed() -> None:
    result = inspect_python_consumer(
        "\n".join(
            (
                'selected = answers["risk"]',
                "if use_route:",
                '    selected = answers["route"]',
                "publish(selected.confidence)",
            )
        ),
        QUESTIONS,
    )

    assert result == {
        "status": "not_reviewed",
        "reason": "workflow.consumer_code has unresolved typed-answer reads at lines [4]",
        "sites": [],
    }


def test_loop_alias_with_different_possible_answer_sources_is_unreviewed() -> None:
    result = inspect_python_consumer(
        "\n".join(
            (
                'selected = answers["risk"]',
                "for _ in candidates:",
                '    selected = answers["route"]',
                "publish(selected.confidence)",
            )
        ),
        QUESTIONS,
    )

    assert result == {
        "status": "not_reviewed",
        "reason": "workflow.consumer_code has unresolved typed-answer reads at lines [4]",
        "sites": [],
    }


def test_downstream_uses_stay_in_the_answer_assignment_lexical_scope() -> None:
    result = inspect_python_consumer(
        "\n".join(
            (
                "def first(response):",
                '    risk = response.answers["risk"].noul',
                "    return risk",
                "",
                "def unrelated(risk):",
                "    return risk > threshold",
            )
        ),
        QUESTIONS,
    )

    site = next(site for site in result["sites"] if site["expression"] == "response.answers['risk'].noul")
    assert site["downstream_uses"] == ["return risk"]
