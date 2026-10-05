from __future__ import annotations

from system_one_meta_builder.consumer import inspect_python_consumer
from system_one_meta_builder.io import resolve_path
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
        "    publish(probabilities, picks, combined)\n"
        "def summarize(answers):\n"
        "    return max(result.probability for result in answers.checks.values())"
    )
    bindings = [
        {"line": 3, "expression": "result.probability", "answer_field": "noul", "question_ids": ["risk"]},
        {"line": 4, "expression": "pick.confidence", "answer_field": "confidence", "question_ids": ["route"]},
        {"line": 5, "expression": "probabilities[q]", "answer_field": "noul", "question_ids": ["risk"]},
        {"line": 8, "expression": "result.probability", "answer_field": "noul", "question_ids": ["risk"]},
    ]
    document = {"request": {"state": {}, "questions": QUESTIONS}, "workflow": {"consumer_code": code}}
    assert review_requests(document)[-1]["status"] == "not_reviewed"
    document["workflow"]["answer_bindings"] = bindings
    packets = [item for item in review_requests(document) if item["scope"] == "workflow"]
    assert len(packets) == 2
    workflow = packets[0]
    sites = workflow["submitted"]["state"]["consumer_sites"]
    collected = inspect_python_consumer(code, QUESTIONS, bindings)
    assert {site["site_id"] for packet in packets for site in packet["submitted"]["state"]["consumer_sites"]} == {
        site["site_id"] for site in collected["sites"]
    }
    check_ids = [check_id for packet in packets for check_id in packet["submitted"]["questions"]]
    assert len(check_ids) == len(set(check_ids))
    assert set(check_ids) == set(workflow["workflow_check_ids"])
    assert all(packet["state_path_coverage"]["review_question_unresolved_paths"] == [] for packet in packets)
    for packet in packets:
        state = packet["submitted"]["state"]
        assert len(state["workflow_coverage"]["source_contexts"]) == 1
        assert state["workflow_coverage"]["source_contexts"][0] in collected["source_contexts"]
        for check_id, question in packet["submitted"]["questions"].items():
            inspect = question["instructions"]["inspect"]
            paths = [inspect] if isinstance(inspect, str) else inspect
            selected = next(path.split(".")[0] for path in paths if path.startswith("consumer_sites["))
            site = resolve_path(state, selected)
            assert site["site_id"] == f"site_{check_id.rsplit('__', 1)[1]}"
        for site in state["consumer_sites"]:
            assert resolve_path(state, site["source_context_path"]) in collected["source_contexts"]
            assert site["source_context_path"] == "workflow_coverage.source_contexts[0]"
            original = next(item for item in collected["sites"] if item["site_id"] == site["site_id"])
            assert resolve_path(state, site["source_context_path"]) == resolve_path(
                {"workflow_coverage": collected}, original["source_context_path"]
            )
            assert {key: value for key, value in site.items() if key != "source_context_path"} == {
                key: value for key, value in original.items() if key != "source_context_path"
            }
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
