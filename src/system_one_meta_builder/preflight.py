"""Free structural checks over the canonical prepared request; no semantic claims."""

from collections.abc import Mapping
from typing import Any

from .io import fingerprint
from .principles import principle_provenance


def _analysis_ownership(prepared: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate facts established by code from prepared semantic checks and gaps."""
    code_known = [
        {
            "kind": "structural_finding",
            **finding,
        }
        for finding in findings
    ]
    semantic: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []

    for item in prepared:
        scope = item.get("scope")
        if item.get("status") == "not_reviewed":
            incomplete.append(
                {
                    "scope": scope,
                    "kind": "review_coverage",
                    "reason": item["reason"],
                    "affects": ["workflow_score", "full_workflow_readiness"],
                }
            )
            continue

        submitted = item.get("submitted", {})
        submitted_questions = submitted.get("questions", {})
        semantic.append(
            {
                "scope": scope,
                "candidate_question_id": item.get("candidate_question_id"),
                "review_fingerprint": item.get("review_fingerprint"),
                "check_ids": sorted(submitted_questions),
            }
        )

        if scope == "criteria_condition":
            code_known.append(
                {
                    "kind": "criteria_condition_binding",
                    **item["condition_comparison"],
                    "candidate_question_id": item["candidate_question_id"],
                    "policy_role": "advisory_unvalidated",
                }
            )
            continue

        if scope == "question":
            coverage = item.get("atomicity_pair_coverage", {})
            if coverage.get("status") != "reviewed":
                incomplete.append(
                    {
                        "scope": "question",
                        "candidate_question_id": item.get("candidate_question_id"),
                        "kind": "atomicity_pair_coverage",
                        "reason": item.get("skipped_checks", {}).get("atomicity_pair_review"),
                        "affects": ["question_design_score", "full_request_readiness"],
                    }
                )
            contrast_coverage = item.get("semantic_term_contrast_coverage", {})
            if contrast_coverage.get("status") != "reviewed":
                incomplete.append(
                    {
                        "scope": "question",
                        "candidate_question_id": item.get("candidate_question_id"),
                        "kind": "semantic_term_contrast_coverage",
                        "reason": item.get("skipped_checks", {}).get("decision_term_semantic_contrast"),
                        "affects": ["semantic_term_contrast_advisory"],
                    }
                )
            for contrast in contrast_coverage.get("contrasts", []):
                code_known.append(
                    {
                        "kind": "semantic_term_contrast_binding",
                        "candidate_question_id": item.get("candidate_question_id"),
                        "contrast_id": contrast["contrast_id"],
                        "selected_path": contrast["selected_path"],
                        "quoted_term": contrast["quoted_term"],
                        "occurrence_index": contrast["occurrence_index"],
                        "definition_provenance": {
                            "a": contrast["definition_a"]["provenance"],
                            "b": contrast["definition_b"]["provenance"],
                        },
                        "differing_answer_case": contrast["differing_answer_case"],
                        "policy_role": "advisory_unvalidated",
                    }
                )
            continue

        state = submitted.get("state", {})
        for site in state.get("consumer_sites", []):
            observation = {
                "kind": "python_consumer_site",
                "site_id": site["site_id"],
                "site_kind": site["kind"],
                "line": site["line"],
                "expression": site["expression"],
                "answer_fields": list(site["answer_fields"]),
                "question_ids": sorted(site["relevant_questions"]),
                "branch_conditions": list(site["branch_conditions"]),
                "downstream_uses": list(site["downstream_uses"]),
            }
            if "operation" in site:
                observation["operation"] = site["operation"]
            code_known.append(observation)

    for finding in findings:
        if finding["severity"] == "error":
            incomplete.append(
                {
                    "scope": "question",
                    "candidate_question_id": finding.get("question"),
                    "kind": finding["code"],
                    "reason": finding["message"],
                    "affects": ["semantic_review", "full_request_readiness"],
                }
            )

    principle_id = "deterministic_rules_stay_in_code"
    return {
        "code_known": code_known,
        "semantic": semantic,
        "incomplete": incomplete,
        "source_references": [{"id": principle_id, **principle_provenance({principle_id})[principle_id]}],
        "meaning": (
            "Code-known entries are structural observations, not claims that the program's "
            "meaning is certified. Semantic entries are the exact checks prepared for model "
            "judgment. Incomplete entries name evidence or coverage still required."
        ),
    }


def code_preflight(document: Mapping[str, Any], prepared: list[dict[str, Any]], request_sha256: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    questions = document.get("request", document)["questions"]
    for item in prepared:
        if item.get("scope") != "question":
            continue
        question_id = item["candidate_question_id"]
        for path in item["state_path_coverage"]["unresolved_backticked_paths"]:
            principle_id = "identify_question_references"
            reference = principle_provenance({principle_id})[principle_id]
            findings.append(
                {
                    "code": "unresolved_state_reference",
                    "severity": "error",
                    "question": question_id,
                    "state_path": path,
                    "action": "resolve_state_reference",
                    "message": (
                        f"Question {question_id!r} refers to `{path}`, but that path is absent from request.state. "
                        "Supply that value or correct the reference. If this names literal code instead of "
                        "a state field, describe it without a backticked field reference."
                    ),
                    "source_references": [{"id": principle_id, **reference}],
                }
            )
        if "criteria" not in questions[question_id]:
            principle_id = "noul_criteria_are_optional"
            reference = principle_provenance({principle_id})[principle_id]
            findings.append(
                {
                    "code": "criteria_not_supplied",
                    "severity": "info",
                    "question": question_id,
                    "action": "inspect_answer_boundary",
                    "message": (
                        f"Question {question_id!r} has no criteria. Criteria are optional; verify its instructions "
                        "alone define the intended answer, and add descriptions only if a distinction needs them."
                    ),
                    "source_references": [{"id": principle_id, **reference}],
                }
            )
    return {
        "schema_version": 1,
        "kind": "preflight",
        "status": "complete",
        "document_fingerprint": fingerprint(document),
        "candidate_request_sha256": request_sha256,
        "provider_calls": 0,
        "route": "gather_evidence" if any(item["severity"] == "error" for item in findings) else "review_required",
        "findings": findings,
        "analysis_ownership": _analysis_ownership(prepared, findings),
        "scoring": None,
        "meaning": "Code-only structural checks. Question meaning and workflow behavior have not been judged.",
    }
