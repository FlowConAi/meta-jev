"""Compare one host-named requirement in isolated question components."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .io import InputError, fingerprint, question_review_context, resolve_path
from .principles import principle_provenance, selected_principles
from .receipts import review_binding_id
from .sdk import DEFAULT_MODEL

CHECK_ID = "component_requires_condition"
PRINCIPLE_ID = "instructions_align_with_criteria"
QUESTION = {
    "type": "noul",
    "instructions": {
        "question": "Does `component` require `condition` for a yes answer?",
        "focus": (
            "Read only this component's requirement. The request_state resolves its field references. "
            "Judge whether the condition is required, not whether it is true in request_state."
        ),
    },
    "criteria": {
        "true": "Under this component, a yes answer requires the condition to hold.",
        "false": "This component permits a yes answer without that condition, or does not require it.",
    },
}
CHECK_SPEC = {
    "principle_ids": [PRINCIPLE_ID],
    "guidance": "Compare this requirement with the separately reviewed component; a difference needs inspection.",
    "advisory_only": True,
}


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{name} must be nonempty text")
    return value


def _conditions(document: Mapping[str, Any], question_id: str) -> list[Mapping[str, Any]]:
    context = question_review_context(document, question_id)
    values = context.get("criteria_conditions", [])
    if not isinstance(values, list) or any(not isinstance(value, Mapping) for value in values):
        raise InputError(f"criteria_conditions for {question_id!r} must be an array of objects")
    return values


def condition_review_requests(
    document: Mapping[str, Any],
    question_id: str,
    question: Mapping[str, Any],
    request_state: Any,
    model: str | None,
) -> list[dict[str, Any]]:
    """Use the normal review transport, with sibling components excluded from each request."""
    conditions = _conditions(document, question_id)
    if not conditions:
        return []
    criteria = question.get("criteria")
    if question.get("type") != "noul" or not isinstance(criteria, Mapping) or criteria.get("true") is None:
        raise InputError("criteria_conditions requires a Noul with a true criterion")
    prepared = []
    seen: set[str] = set()
    for raw in conditions:
        condition_id = _text(raw.get("condition_id"), "condition_id")
        if condition_id in seen:
            raise InputError(f"duplicate criteria condition {condition_id!r}")
        seen.add(condition_id)
        condition = _text(raw.get("condition"), "condition")
        source_path = _text(raw.get("source_path"), "source_path")
        source_quote = _text(raw.get("source_quote"), "source_quote")
        if not source_path.startswith("candidate_question."):
            raise InputError("condition source_path must start with candidate_question.")
        try:
            source = resolve_path({"candidate_question": question}, source_path)
        except (KeyError, IndexError) as error:
            raise InputError(f"condition source_path does not resolve: {source_path!r}") from error
        if not isinstance(source, str) or source_quote not in source:
            raise InputError("condition source_quote must occur in the selected source text")
        for side, component in (("instructions", question["instructions"]), ("true_criterion", criteria["true"])):
            component_path = "instructions" if side == "instructions" else "criteria.true"
            submitted = {
                "model": model or DEFAULT_MODEL,
                "state": {
                    "component": component,
                    "condition": condition,
                    "request_state": request_state,
                    "principles": selected_principles({PRINCIPLE_ID}),
                },
                "questions": {CHECK_ID: QUESTION},
            }
            prepared.append(
                {
                    "scope": "criteria_condition",
                    "candidate_question_id": question_id,
                    "condition_comparison": {
                        "condition_id": condition_id,
                        "condition": condition,
                        "side": side,
                        "component_path": f"candidate_question.{component_path}",
                        "component": component,
                        "source_path": source_path,
                        "source_quote": source_quote,
                    },
                    "policy_role": "advisory_unvalidated",
                    "principle_provenance": principle_provenance({PRINCIPLE_ID}),
                    "review_fingerprint": fingerprint(submitted),
                    "submitted": submitted,
                }
            )
    return prepared


def _requirement_band(probability: float | None, policy: Mapping[str, Any]) -> str:
    if probability is None:
        return "missing"
    if policy["kind"] == "no_threshold_policy":
        return "unthresholded"
    if probability >= policy["flag_at"]:
        return "required"
    if probability <= policy["clear_below"]:
        return "not_required"
    return "uncertain"


def compose_conditions(
    receipts: Iterable[Mapping[str, Any]], observations: list[dict[str, Any]], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Keep both observations and compose a review direction, never a defect probability."""
    indexed = {item["review_binding_id"]: item for item in observations if item["check_id"] == CHECK_ID}
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for receipt in receipts:
        if receipt.get("scope") != "criteria_condition":
            continue
        contract = receipt["condition_comparison"]
        key = (receipt["candidate_question_id"], contract["condition_id"])
        group = groups.setdefault(
            key,
            {
                "question": key[0],
                "condition_id": key[1],
                "condition": contract["condition"],
                "source_path": contract["source_path"],
                "source_quote": contract["source_quote"],
                "components": {},
            },
        )
        observation = indexed.get(review_binding_id(receipt))
        probability = observation["probability"] if observation else None
        group["components"][contract["side"]] = {
            "path": contract["component_path"],
            "content": contract["component"],
            "probability": probability,
            "requirement": _requirement_band(probability, policy),
            "observation_id": observation["observation_id"] if observation else None,
        }
    results = []
    for group in groups.values():
        bands = [
            group["components"].get(side, {}).get("requirement", "missing")
            for side in ("instructions", "true_criterion")
        ]
        if "missing" in bands:
            outcome = "incomplete"
        elif "unthresholded" in bands:
            outcome = "unthresholded"
        elif "uncertain" in bands:
            outcome = "uncertain"
        else:
            outcome = "same_requirement" if bands[0] == bands[1] else "asymmetric_requirement"
        results.append(
            {
                **group,
                "outcome": outcome,
                "policy_role": "advisory_unvalidated",
                "message": (
                    f"Compare {group['condition']!r} in the two displayed components. "
                    "If the extra requirement is intended, state it in the instruction; otherwise revise "
                    "the criterion. A criterion may legitimately clarify the instruction."
                    if outcome == "asymmetric_requirement"
                    else "Inspect the separate requirement observations; this comparison does not certify the question."
                ),
                "affects_design_score": False,
                "affects_route": False,
            }
        )
    return results
