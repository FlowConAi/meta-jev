from __future__ import annotations

from system_one_meta_builder.consumer import inspect_python_consumer
from system_one_meta_builder.review import review_requests

QUESTIONS = {
    "risk": {"type": "noul", "instructions": "Does the supplied message contain risk?"},
    "route": {"type": "choice", "instructions": "Which route applies?", "criteria": {"review": None, "publish": None}},
}


def test_answer_roots_aliases_and_declared_reads_resolve_question_provenance() -> None:
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

    code = (
        "STALE_PARTS = ('risk',)\n"
        "def consume(answers):\n"
        "    probabilities = {name: result.probability for name, result in answers.checks.items()}\n"
        "    picks = {name: pick.confidence for name, pick in answers.picks.items()}\n"
        "    combined = min(probabilities[q] for q in STALE_PARTS)\n"
        "    publish(probabilities, picks, combined)"
    )
    bindings = [
        {"line": 3, "expression": "result.probability", "answer_field": "noul", "question_ids": ["risk"]},
        {"line": 4, "expression": "pick.confidence", "answer_field": "confidence", "question_ids": ["route"]},
        {"line": 5, "expression": "probabilities[q]", "answer_field": "noul", "question_ids": ["risk"]},
    ]
    document = {"request": {"state": {}, "questions": QUESTIONS}, "workflow": {"consumer_code": code}}
    assert review_requests(document)[-1]["status"] == "not_reviewed"
    document["workflow"]["answer_bindings"] = bindings
    workflow = review_requests(document)[-1]
    sites = workflow["submitted"]["state"]["consumer_sites"]
    reads = [site for site in sites if site["kind"] == "answer_read"]
    assert [(site["expression"], site["answer_fields"], list(site["relevant_questions"])) for site in reads] == [
        ("result.probability", ["noul"], ["risk"]),
        ("pick.confidence", ["confidence"], ["route"]),
        ("probabilities[q]", ["noul"], ["risk"]),
    ]
    assert all(site["binding_provenance"] == "host_declared" for site in reads)
    assert len(reads[0]["downstream_uses"]) == 2
    assert "publish(probabilities, picks, combined)" in reads[0]["downstream_uses"]
    composition = next(site for site in sites if site["kind"] == "composition")
    assert composition["operation"] == "min"
    assert list(composition["relevant_questions"]) == ["risk"]
    assert composition["binding_provenance"] == ["host_declared"]
    assert "required_condition_hidden_by_compensation__0" in workflow["submitted"]["questions"]
    context = workflow["workflow_coverage"]["source_contexts"][0]
    assert context["referenced_constants"] == {"STALE_PARTS": "STALE_PARTS = ('risk',)"}
    assert context["unresolved_dependencies"] == ["publish"]
    assert "consumer_code" not in workflow["submitted"]["state"]

    for invalid in (
        {**bindings[0], "question_ids": ["absent"]},
        {**bindings[0], "answer_field": "confidence"},
        {**bindings[0], "expression": "missing.probability"},
        {**bindings[0], "line": 4},
    ):
        document["workflow"]["answer_bindings"] = [invalid, bindings[1]]
        refused = review_requests(document)[-1]
        assert refused["status"] == "not_reviewed"
        assert "answer_bindings" in refused["reason"]


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
