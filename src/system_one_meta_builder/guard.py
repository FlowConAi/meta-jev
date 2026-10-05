"""Preflight routing over exact meta-review receipts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import isfinite
from typing import Any

from .atomicity import compose_atomicity, is_pair_observation
from .criteria_conditions import CHECK_ID as CONDITION_CHECK_ID
from .criteria_conditions import compose_conditions
from .io import InputError, fingerprint
from .receipts import review_binding_id
from .review import base_check_id
from .sdk import validate_answer_bindings

QUESTION_DIMENSION_WEIGHTS = {
    "atomicity": 0.20,
    "question_clarity": 0.15,
    "state_clarity": 0.15,
    "primitive_suitability": 0.15,
    "evidence_sufficiency": 0.20,
    "task_suitability": 0.15,
}

WORKFLOW_DIMENSION_WEIGHTS = {"workflow_consumption": 0.60, "workflow_weighting": 0.40}

SCORING_POLICY_VERSION = 2
ROUTING_POLICY_VERSION = 2

CHECK_ACTIONS = {
    CONDITION_CHECK_ID: "inspect_component_requirement",
    "atomicity_requires_proposition_a": "inspect_proposition_requirement",
    "atomicity_requires_proposition_b": "inspect_proposition_requirement",
    "requires_both_independent_propositions": "split_required_outputs",
    "decision_term_rules_out_definition_a": "inspect_semantic_term_contrast",
    "decision_term_rules_out_definition_b": "inspect_semantic_term_contrast",
    "does_not_name_judged_property": "name_judged_property",
    "question_wording_is_hard_to_understand": "rewrite_for_directness",
    "question_meaning_is_unrecoverable": "define_missing_meaning",
    "question_reference_is_ambiguous": "identify_question_reference",
    "state_component_wording_is_hard_to_understand": "rewrite_state_component",
    "state_component_role_is_unclear": "clarify_state_role",
    "state_component_entity_is_unclear": "identify_state_entity",
    "state_component_unit_is_unclear": "identify_state_unit",
    "state_component_timeframe_is_unclear": "identify_state_timeframe",
    "state_reference_target_is_ambiguous": "identify_state_target",
    "requires_missing_case_fact": "supply_evidence",
    "has_conflicting_criteria": "repair_criteria",
    "instructions_conflict_with_criteria": "align_instruction_and_criteria",
    "requires_generated_content": "move_generation_to_host",
    "requires_external_action": "move_action_to_code",
    "noul_lacks_single_proposition": "use_single_proposition_or_change_primitive",
    "choice_has_nonexclusive_properties": "use_independent_nouls",
    "choice_has_no_valid_option_for_case": "add_no_match_option",
    "score_lacks_ordered_degree": "change_primitive_or_order_levels",
    "score_levels_are_abstract_degrees": "describe_score_level_situations",
    "consumer_site_overclaims_evidence": "align_consumer_claims",
    "concentration_used_as_empirical_accuracy": "measure_accuracy_separately",
    "option_probability_mislabeled_as_confidence": "use_correct_uncertainty_field",
    "noul_probability_used_as_degree": "use_score_for_degree",
    "missing_evidence_mapped_to_negative": "preserve_missing_state",
    "answer_weights_lack_explicit_policy": "define_weighting_policy",
    "required_condition_hidden_by_compensation": "separate_required_condition",
    "score_combined_without_normalization": "normalize_score_before_weighting",
    "noul_product_claimed_joint_probability": "rename_or_validate_probability_product",
}


def validate_review_response(submitted: Any, response: Any) -> None:
    """Validate the exact answer set needed for deterministic guard routing."""
    if not isinstance(submitted, Mapping):
        raise InputError("successful review receipt has no submitted request")
    questions = submitted.get("questions")
    if not isinstance(questions, Mapping) or not questions:
        raise InputError("successful review receipt has no submitted review questions")
    if not isinstance(response, Mapping) or not isinstance(response.get("answers"), Mapping):
        raise InputError("successful review receipt has no answer object")
    answers = response["answers"]
    validate_answer_bindings(submitted, response)
    for check_id, answer in answers.items():
        if not isinstance(answer, Mapping) or answer.get("type") != "noul":
            raise InputError(f"review answer {check_id!r} is not a Noul")
        probability = answer.get("noul")
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not isfinite(probability)
            or not 0 <= probability <= 1
        ):
            raise InputError(f"review answer {check_id!r} has no finite probability from 0 to 1")


def validate_review_receipt(receipt: Mapping[str, Any]) -> None:
    submitted = receipt.get("submitted")
    review_fingerprint = receipt.get("review_fingerprint")
    if not isinstance(review_fingerprint, str) or fingerprint(submitted) != review_fingerprint:
        raise InputError("successful review receipt fingerprint does not match its submitted request")
    validate_review_response(submitted, receipt.get("response"))
    response_model = receipt["response"].get("model")
    if not isinstance(response_model, str) or not response_model or receipt.get("response_model") != response_model:
        raise InputError("review receipt response model must match the recorded provider response model")


def scoring_policy(raw: Any = None) -> dict[str, Any]:
    """Return an explicit deterministic scoring policy, validating optional caller weights."""
    if raw is None:
        question_weights: Any = QUESTION_DIMENSION_WEIGHTS
        workflow_weights: Any = WORKFLOW_DIMENSION_WEIGHTS
        kind = "default_experimental_design_weights"
    else:
        allowed = {"question_dimension_weights", "workflow_dimension_weights"}
        if not isinstance(raw, Mapping) or not set(raw) or not set(raw) <= allowed:
            raise InputError("scoring policy may contain question_dimension_weights and workflow_dimension_weights")
        question_weights = raw.get("question_dimension_weights", QUESTION_DIMENSION_WEIGHTS)
        workflow_weights = raw.get("workflow_dimension_weights", WORKFLOW_DIMENSION_WEIGHTS)
        kind = "caller_supplied_experimental_design_weights"

    def validated_weights(name: str, weights: Any, expected: Mapping[str, float]) -> dict[str, float]:
        if not isinstance(weights, Mapping) or set(weights) != set(expected):
            raise InputError(f"{name} must define {sorted(expected)!r}")
        normalized: dict[str, float] = {}
        for dimension, value in weights.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                raise InputError(f"weight for {dimension!r} must be a finite nonnegative number")
            normalized[str(dimension)] = float(value)
        if abs(sum(normalized.values()) - 1.0) > 1e-9:
            raise InputError(f"{name} must sum to 1")
        return normalized

    return {
        "version": SCORING_POLICY_VERSION,
        "kind": kind,
        "question_dimension_weights": validated_weights(
            "question_dimension_weights", question_weights, QUESTION_DIMENSION_WEIGHTS
        ),
        "workflow_dimension_weights": validated_weights(
            "workflow_dimension_weights", workflow_weights, WORKFLOW_DIMENSION_WEIGHTS
        ),
        "formula": "100 * (1 - sum(dimension_weight * dimension_risk_index))",
        "dimension_risk": (
            "Maximum applicable defect probability; atomicity uses the minimum_support_index of each "
            "host-evidenced proposition pair. These indices are not probabilities of a defect or joint truth."
        ),
        "meaning": "Experimental question-design index; not calibrated accuracy, confidence, or certification.",
    }


def routing_policy(clear_below: float | None, flag_at: float | None) -> dict[str, Any]:
    """Validate and describe the caller's experimental routing thresholds."""
    if clear_below is None and flag_at is None:
        return {
            "version": ROUTING_POLICY_VERSION,
            "kind": "no_threshold_policy",
            "note": "Raw advisory signals are returned; no automatic trial route was inferred.",
        }
    values = (clear_below, flag_at)
    if (
        any(value is None or isinstance(value, bool) or not isfinite(value) for value in values)
        or not 0 <= clear_below < flag_at <= 1
    ):
        raise InputError("--clear-below and --flag-at must satisfy 0 <= clear < flag <= 1")
    return {
        "version": ROUTING_POLICY_VERSION,
        "kind": "caller_supplied_experimental_thresholds",
        "clear_below": clear_below,
        "flag_at": flag_at,
        "note": "These thresholds are routing policy, not calibrated accuracy or certification.",
    }


def reusable_reviews(rows: Iterable[Any]) -> dict[str, Mapping[str, Any]]:
    """Index only successful exact-review receipts; provider failures are never reusable."""
    reusable: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("kind") == "review" and row.get("status") == "ok":
            validate_review_receipt(row)
            reusable[str(row["review_fingerprint"])] = row
    return reusable


def _inspection_target(receipt: Mapping[str, Any], scope: str, check_id: str) -> dict[str, Any]:
    if scope == "criteria_condition":
        binding = receipt["condition_comparison"]
        return {
            "path": binding["component_path"],
            "source_path": binding["source_path"],
            "source_quote": binding["source_quote"],
        }
    if "__" not in check_id or not (suffix := check_id.rsplit("__", 1)[1]).isdigit():
        return {}
    index = int(suffix)
    state = receipt["submitted"].get("state", {})
    if not isinstance(state, Mapping):
        return {}
    if is_pair_observation(check_id):
        pairs = state.get("atomicity_pairs", [])
        if not isinstance(pairs, list) or index >= len(pairs):
            return {}
        side = "a" if base_check_id(check_id).endswith("_a") else "b"
        return {"path": f"atomicity_pairs[{index}].proposition_{side}.text"}
    if base_check_id(check_id).startswith("decision_term_rules_out_definition_"):
        contrasts = state.get("semantic_term_contrasts", [])
        if not isinstance(contrasts, list) or index >= len(contrasts):
            return {}
        return {"path": f"semantic_term_contrasts[{index}]"}
    collection = "state_components" if scope == "question" else "consumer_sites"
    values = state.get(collection, [])
    if not isinstance(values, list):
        return {}
    if scope == "workflow":
        selected = next((site for site in values if site.get("site_id") == f"site_{index}"), None)
    else:
        selected = values[index] if index < len(values) else None
    if not isinstance(selected, Mapping):
        return {}
    return {key: selected[key] for key in ("path", "site_id", "line", "expression") if key in selected}


def _observation_id(binding_id: Any, check_id: str) -> str:
    return fingerprint({"review_binding_id": binding_id, "check_id": check_id})


def _matching_inspected_content(
    state: Mapping[str, Any], scope: str, check_id: str, inspection_target: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Return only the exact code-selected fragment, never an inferred semantic explanation."""
    if is_pair_observation(check_id):
        suffix = check_id.rsplit("__", 1)[-1]
        if not suffix.isdigit():
            return None
        pairs = state.get("atomicity_pairs")
        index = int(suffix)
        if isinstance(pairs, list) and index < len(pairs) and isinstance(pairs[index], Mapping):
            return {"kind": "atomicity_pair", "index": index, "content": dict(pairs[index])}
        return None
    if base_check_id(check_id).startswith("decision_term_rules_out_definition_"):
        suffix = check_id.rsplit("__", 1)[-1]
        contrasts = state.get("semantic_term_contrasts")
        if suffix.isdigit() and isinstance(contrasts, list):
            index = int(suffix)
            if index < len(contrasts) and isinstance(contrasts[index], Mapping):
                return {"kind": "semantic_term_contrast", "index": index, "content": dict(contrasts[index])}
        return None
    collection = "state_components" if scope == "question" else "consumer_sites"
    values = state.get(collection)
    if not isinstance(values, list):
        return None
    for value in values:
        if not isinstance(value, Mapping):
            continue
        if any(value.get(key) == inspection_target.get(key) for key in ("path", "site_id") if key in inspection_target):
            return {"kind": collection.removesuffix("s"), "content": dict(value)}
        if "line" in inspection_target and value.get("line") == inspection_target.get("line"):
            return {"kind": collection.removesuffix("s"), "content": dict(value)}
    return None


def _review_context(
    receipt: Mapping[str, Any], scope: str, check_id: str, inspection_target: Mapping[str, Any]
) -> dict[str, Any]:
    submitted = receipt["submitted"]
    state = submitted.get("state", {})
    review_question = submitted["questions"][check_id]
    if not isinstance(state, Mapping):
        state = {}
    instructions = review_question.get("instructions", {}) if isinstance(review_question, Mapping) else {}
    context: dict[str, Any] = {
        "review_question": dict(review_question),
    }
    if scope == "criteria_condition":
        context["inspected_content"] = dict(receipt["condition_comparison"])
    if isinstance(instructions, Mapping):
        context["scope_limit"] = instructions.get("focus")
        inspect = instructions.get("inspect", [])
        context["inspect_paths"] = [inspect] if isinstance(inspect, str) else list(inspect)
    inspected_content = _matching_inspected_content(state, scope, check_id, inspection_target)
    if inspected_content is not None:
        context["inspected_content"] = inspected_content
    return context


def _principle_registry(signals: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    observations = []
    principles: dict[str, Any] = {}
    for signal in signals:
        observation = dict(signal)
        provenance = observation.pop("principle_provenance", {})
        references = []
        if isinstance(provenance, Mapping):
            for principle_id, content in provenance.items():
                if not isinstance(content, Mapping):
                    continue
                principle = {"id": principle_id, **content}
                content_id = fingerprint(principle)
                principles[content_id] = principle
                references.append({"id": principle_id, "content_id": content_id})
        observation["principle_references"] = references
        observations.append(observation)
    return observations, principles


def _review_input_registry(receipts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    inputs = {}
    for receipt in receipts:
        review_fingerprint = str(receipt["review_fingerprint"])
        state = receipt["submitted"].get("state", {})
        if not isinstance(state, Mapping):
            state = {}
        shared_context = {key: state[key] for key in ("purpose", "workflow_coverage") if key in state}
        inputs[review_binding_id(receipt)] = {
            "review_fingerprint": review_fingerprint,
            "provider_attempt_id": receipt.get("attempt_id"),
            **(
                {"condition_comparison": dict(receipt["condition_comparison"])}
                if receipt.get("scope") == "criteria_condition"
                else {}
            ),
            "scope": receipt.get("scope"),
            **({"workflow_coverage": receipt["workflow_coverage"]} if "workflow_coverage" in receipt else {}),
            "candidate_question_id": receipt.get("candidate_question_id"),
            "candidate_question": state.get("candidate_question"),
            "shared_context": shared_context,
            "request_state_reference": {
                "sha256": fingerprint(state.get("request_state")),
                "selected_paths": list(receipt.get("state_path_coverage", {}).get("selected_paths", [])),
            },
            "request_sha256": receipt.get("request_sha256"),
            "response_model": receipt.get("response_model"),
            "source": receipt.get("guard_source", "fresh"),
        }
    return inputs


def review_signals(
    receipts: Iterable[Mapping[str, Any]], metadata: Mapping[str, Mapping[str, Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for receipt in receipts:
        validate_review_receipt(receipt)
        response = receipt["response"]
        scope = str(receipt.get("scope"))
        if scope not in metadata:
            raise InputError(f"review receipt has unknown scope: {scope!r}")
        scope_metadata = metadata[scope]
        for check_id, answer in response["answers"].items():
            probability = answer.get("noul")
            base_id = base_check_id(str(check_id))
            check_metadata = scope_metadata.get(base_id, {})
            receipt_provenance = receipt.get("principle_provenance", {})
            inspection_target = _inspection_target(receipt, scope, str(check_id))
            signals.append(
                {
                    "observation_id": _observation_id(review_binding_id(receipt), str(check_id)),
                    "review_binding_id": review_binding_id(receipt),
                    "scope": scope,
                    "candidate_question_id": receipt.get("candidate_question_id"),
                    "check_id": str(check_id),
                    "check_kind": base_id,
                    "probability": float(probability),
                    "typed_answer": dict(answer),
                    **check_metadata,
                    "review_fingerprint": receipt.get("review_fingerprint"),
                    "request_sha256": receipt.get("request_sha256"),
                    "response_model": receipt.get("response_model"),
                    "principle_provenance": {
                        principle_id: receipt_provenance.get(
                            principle_id, check_metadata.get("principle_provenance", {}).get(principle_id)
                        )
                        for principle_id in check_metadata.get("principle_ids", [])
                    },
                    "source": receipt.get("guard_source", "fresh"),
                    "inspection_target": inspection_target,
                    "state_paths": receipt.get("state_path_coverage", {}).get("selected_paths", []),
                    "review_input_reference": review_binding_id(receipt),
                    "review_context": _review_context(receipt, scope, str(check_id), inspection_target),
                    "meaning": (
                        "Jev's Noul probability for the exact review proposition and prepared input. "
                        "It is not model rationale, measured accuracy, or proof that the named defect exists."
                    ),
                }
            )
    return signals


def _feedback_disposition(probability: float, policy: Mapping[str, Any]) -> str:
    if policy["kind"] == "no_threshold_policy":
        return "unthresholded"
    if probability >= policy["flag_at"]:
        return "flagged"
    if probability <= policy["clear_below"]:
        return "not_flagged"
    return "uncertain"


def actionable_feedback(signals: Iterable[Mapping[str, Any]], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    feedback: list[dict[str, Any]] = []
    for signal in signals:
        check_id = str(signal["check_id"])
        question_id = signal.get("candidate_question_id")
        path = "workflow.consumer_code" if signal.get("scope") == "workflow" else f"request.questions.{question_id}"
        guidance = str(signal.get("inspection_guidance", "Inspect this check before the next trial."))
        advisory_only = bool(signal.get("advisory_only"))
        disposition = (
            "observation"
            if is_pair_observation(check_id) or advisory_only
            else _feedback_disposition(_policy_value(signal), policy)
        )
        prefix = {
            "observation": "Recorded proposition requirement for",
            "flagged": "Repair",
            "uncertain": "Review",
            "not_flagged": "No repair routed for",
            "unthresholded": "No threshold disposition for",
        }[disposition]
        if advisory_only:
            prefix = "Recorded unvalidated advisory contrast for"
        action = CHECK_ACTIONS[base_check_id(check_id)]
        inspection_target = signal.get("inspection_target", {})
        location: dict[str, Any] = {"question_path": path}
        state_paths = signal.get("state_paths", [])
        if state_paths:
            location["state_paths"] = list(state_paths)
            path = f"{path}, using state {', '.join(repr(value) for value in state_paths)}"
        if isinstance(inspection_target, Mapping) and inspection_target:
            location.update(inspection_target)
            if "path" in inspection_target:
                path = f"{path} state component {inspection_target['path']!r}"
            elif "line" in inspection_target:
                path = f"{path} line {inspection_target['line']} expression {inspection_target.get('expression')!r}"
        message = f"{prefix} {path}: {guidance}"
        if base_check_id(check_id) == "requires_missing_case_fact" and disposition != "not_flagged":
            message += (
                " This signal does not identify which fact is missing. Inspect the named state against "
                "the question and add the required source evidence before rerunning the review."
            )
        review_context = signal.get("review_context")
        review_question: Any = None
        if isinstance(review_context, Mapping):
            review_question = review_context.get("review_question")
        instructions = review_question.get("instructions") if isinstance(review_question, Mapping) else None
        feedback.append(
            {
                **(
                    {"assessment_id": signal["assessment_id"], "pair_id": signal["pair_id"]}
                    if "assessment_id" in signal
                    else {
                        "observation_id": signal.get("observation_id")
                        or _observation_id(signal.get("review_binding_id"), check_id)
                    }
                ),
                "question": question_id,
                "check": check_id,
                "action": action,
                "disposition": disposition,
                "recommended_action": action if disposition == "flagged" else None,
                "message": message,
                ("minimum_support_index" if "minimum_support_index" in signal else "probability"): _policy_value(
                    signal
                ),
                "dimension": signal.get("dimension"),
                "source": signal.get("source"),
                "inspection_target": inspection_target,
                "location": location,
                "evidence_status": (
                    "code_composed"
                    if "minimum_support_index" in signal
                    else "model_advisory_unvalidated"
                    if advisory_only
                    else "model_suspected"
                ),
                "request_sha256": signal.get("request_sha256"),
                "review_fingerprint": signal.get("review_fingerprint"),
                "typed_answer": signal.get("typed_answer"),
                "response_model": signal.get("response_model"),
                "reviewed_proposition": (
                    instructions.get("question") if isinstance(instructions, Mapping) else instructions
                ),
                "meaning": signal.get(
                    "meaning",
                    "A code-composed observation over named inputs; inspect its source observations.",
                ),
                "principle_references": list(signal.get("principle_references", [])),
            }
        )
    return feedback


def _score_workflow(
    receipts: list[Mapping[str, Any]],
    by_binding: Mapping[str, list[dict[str, Any]]],
    weights: Mapping[str, float],
    skipped_reviews: Iterable[Mapping[str, Any]],
    expected_checks: Iterable[str],
) -> dict[str, Any]:
    workflow_receipts = [receipt for receipt in receipts if receipt.get("scope") == "workflow"]
    expected = set(expected_checks)
    observed: set[str] = set()
    signals = []
    packets = []
    for receipt in workflow_receipts:
        packet_expected = set(receipt["submitted"]["questions"])
        expected.update(packet_expected)
        expected.update(receipt.get("workflow_check_ids", []))
        packet_signals = by_binding.get(review_binding_id(receipt), [])
        failed = receipt.get("status") not in (None, "ok")
        if failed:
            packet_signals = []
        packet_observed = {signal["check_id"] for signal in packet_signals}
        observed.update(packet_observed)
        signals.extend(packet_signals)
        packets.append(
            {
                "review_binding_id": review_binding_id(receipt),
                "review_fingerprint": receipt["review_fingerprint"],
                "expected_check_ids": sorted(packet_expected),
                "observed_check_ids": sorted(packet_observed),
                "missing_check_ids": sorted(packet_expected - packet_observed),
                "unexpected_check_ids": sorted(packet_observed - packet_expected),
                "unresolved_backticked_paths": list(
                    receipt.get("state_path_coverage", {}).get("unresolved_backticked_paths", [])
                ),
                "status": "incomplete" if failed or packet_expected != packet_observed else "reviewed",
            }
        )
    if not workflow_receipts and not expected:
        reason = next(
            (item["reason"] for item in skipped_reviews if item.get("scope") == "workflow"),
            "workflow.consumer_code was not supplied",
        )
        return {"status": "not_reviewed", "score": None, "weighted_risk": None, "coverage": {"reason": reason}}
    dimensions = {}
    for dimension, weight in weights.items():
        applicable = [
            signal for signal in signals if signal.get("dimension") == dimension and not signal.get("advisory_only")
        ]
        risk = max((signal["probability"] for signal in applicable), default=None)
        dimensions[dimension] = {
            "weight": weight,
            "risk": risk,
            "score": round(100 * (1 - risk), 2) if risk is not None else None,
            "check_ids": sorted({str(signal["check_id"]) for signal in applicable}),
        }
    coverage = {
        "expected_check_ids": sorted(expected),
        "observed_check_ids": sorted(observed),
        "missing_check_ids": sorted(expected - observed),
        "unexpected_check_ids": sorted(observed - expected),
        "missing_dimensions": sorted(dimension for dimension, value in dimensions.items() if value["risk"] is None),
        "packets": sorted(packets, key=lambda packet: packet["review_binding_id"]),
    }
    complete = not any(coverage[key] for key in ("missing_check_ids", "unexpected_check_ids", "missing_dimensions"))
    complete = complete and all(
        packet["status"] == "reviewed" and not packet["unresolved_backticked_paths"] for packet in packets
    )
    weighted_risk = sum(value["weight"] * value["risk"] for value in dimensions.values()) if complete else None
    return {
        "status": "reviewed" if complete else "incomplete",
        "method": "weighted_strongest_applicable_check_per_workflow_dimension",
        "score": round(100 * (1 - weighted_risk), 2) if weighted_risk is not None else None,
        "weighted_risk": round(weighted_risk, 6) if weighted_risk is not None else None,
        "dimensions": dimensions,
        "coverage": coverage,
        "meaning": "Separate integration index; not blended into question design.",
    }


def score_reviews(
    receipts: Iterable[Mapping[str, Any]],
    signals: list[dict[str, Any]],
    policy: Mapping[str, Any],
    skipped_reviews: Iterable[Mapping[str, Any]] = (),
    expected_workflow_checks: Iterable[str] = (),
) -> dict[str, Any]:
    """Score complete per-question reviews and keep workflow review separate."""
    weights = policy["question_dimension_weights"]
    receipts = list(receipts)
    atomicity = compose_atomicity(receipts, signals)
    workflow_weights = policy["workflow_dimension_weights"]
    by_binding: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        by_binding.setdefault(str(signal["review_binding_id"]), []).append(signal)

    question_scores: list[dict[str, Any]] = []
    workflow_grade = _score_workflow(receipts, by_binding, workflow_weights, skipped_reviews, expected_workflow_checks)
    for receipt in receipts:
        if receipt.get("scope") == "criteria_condition":
            continue
        receipt_signals = by_binding.get(review_binding_id(receipt), [])
        expected_checks = {str(check_id) for check_id in receipt["submitted"]["questions"]}
        observed_checks = {str(signal["check_id"]) for signal in receipt_signals}
        coverage = {
            "expected_check_ids": sorted(expected_checks),
            "observed_check_ids": sorted(observed_checks),
            "missing_check_ids": sorted(expected_checks - observed_checks),
            "unexpected_check_ids": sorted(observed_checks - expected_checks),
        }
        if receipt.get("scope") == "workflow":
            continue

        dimensions: dict[str, Any] = {}
        for dimension, weight in weights.items():
            dimension_signals = [
                signal
                for signal in receipt_signals
                if signal.get("dimension") == dimension and not signal.get("advisory_only")
            ]
            if dimension == "atomicity":
                risks = [
                    item["minimum_support_index"]
                    for item in atomicity
                    if item["review_binding_id"] == review_binding_id(receipt)
                    and item["minimum_support_index"] is not None
                ]
            else:
                risks = [signal["probability"] for signal in dimension_signals]
            dimensions[dimension] = {
                "weight": weight,
                "risk": (risk := max(risks, default=None)),
                "score": round(100 * (1 - risk), 2) if risk is not None else None,
                "check_ids": sorted(str(signal["check_id"]) for signal in dimension_signals),
            }
        missing_dimensions = sorted(dimension for dimension, value in dimensions.items() if value["risk"] is None)
        coverage["missing_dimensions"] = missing_dimensions
        coverage["atomicity_pair_review"] = receipt.get("atomicity_pair_coverage", {"status": "not_reviewed"})
        coverage["semantic_term_contrast_review"] = receipt.get(
            "semantic_term_contrast_coverage", {"status": "not_reviewed", "policy_role": "advisory_unvalidated"}
        )
        coverage["unresolved_backticked_paths"] = receipt.get("state_path_coverage", {}).get(
            "unresolved_backticked_paths", []
        )
        complete = (
            not coverage["missing_check_ids"]
            and not coverage["unexpected_check_ids"]
            and not missing_dimensions
            and not coverage["unresolved_backticked_paths"]
        )
        weighted_risk = sum(value["weight"] * value["risk"] for value in dimensions.values()) if complete else None
        question_scores.append(
            {
                "question": receipt.get("candidate_question_id"),
                "status": "complete" if complete else "incomplete",
                "design_score": round(100 * (1 - weighted_risk), 2) if weighted_risk is not None else None,
                "weighted_risk": round(weighted_risk, 6) if weighted_risk is not None else None,
                "dimensions": dimensions,
                "coverage": coverage,
                "applicability": {
                    "applied_check_ids": sorted(expected_checks),
                    "skipped_checks": receipt.get("skipped_checks", {}),
                },
            }
        )
    complete_scores = [score["design_score"] for score in question_scores if score["design_score"] is not None]
    request_complete = len(complete_scores) == len(question_scores) and bool(question_scores)
    return {
        "policy": dict(policy),
        "questions": question_scores,
        "request": {
            "status": "complete" if request_complete else "incomplete",
            "aggregation": "minimum_complete_question_score",
            "design_score": min(complete_scores) if request_complete else None,
        },
        "workflow": workflow_grade,
    }


def route(signals: list[dict[str, Any]], policy: Mapping[str, Any]) -> str:
    signals = [signal for signal in signals if not signal.get("advisory_only")]
    if policy["kind"] == "no_threshold_policy":
        return "review_required"
    flagged = [signal for signal in signals if _policy_value(signal) >= policy["flag_at"]]
    if any(base_check_id(signal["check_id"]) == "requires_missing_case_fact" for signal in flagged):
        return "gather_evidence"
    if any(signal["scope"] == "question" for signal in flagged):
        return "revise_questions"
    if flagged:
        return "review_integration"
    if any(_policy_value(signal) > policy["clear_below"] for signal in signals):
        return "review_required"
    return "ready_for_small_trial"


def _policy_value(signal: Mapping[str, Any]) -> float:
    return signal["minimum_support_index"] if "minimum_support_index" in signal else signal["probability"]


def _coverage_repair_actions(question: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Name only repairs established by deterministic coverage metadata."""
    coverage = question["coverage"]
    actions: list[dict[str, Any]] = []
    unresolved = coverage["unresolved_backticked_paths"]
    if unresolved:
        actions.append(
            {
                "action": "resolve_state_references",
                "state_paths": list(unresolved),
                "message": (
                    "Resolve the named state references, or rewrite literal code/prose so it is not "
                    "presented as a state path."
                ),
            }
        )
    missing_checks = coverage["missing_check_ids"]
    if missing_checks:
        actions.append(
            {
                "action": "complete_review_checks",
                "check_ids": list(missing_checks),
                "message": "Recover or rerun the named review checks before using the composite score.",
            }
        )
    missing_dimensions = coverage["missing_dimensions"]
    if "atomicity" in missing_dimensions:
        reason = (
            question.get("applicability", {})
            .get("skipped_checks", {})
            .get("atomicity_pair_review", "atomicity has no complete source-backed proposition-pair review")
        )
        actions.append(
            {
                "action": "provide_atomicity_pair_or_keep_unreviewed",
                "dimension": "atomicity",
                "reason": reason,
                "message": (
                    "Provide a source-grounded proposition pair tied to two separately needed consumer "
                    "outputs and mixed-truth evidence, or keep atomicity explicitly unreviewed."
                ),
            }
        )
    remaining_dimensions = [dimension for dimension in missing_dimensions if dimension != "atomicity"]
    if remaining_dimensions:
        actions.append(
            {
                "action": "complete_dimension_evidence",
                "dimensions": remaining_dimensions,
                "message": "Complete the named review dimensions before using the composite score.",
            }
        )
    unexpected_checks = coverage["unexpected_check_ids"]
    if unexpected_checks:
        actions.append(
            {
                "action": "remove_unexpected_review_checks",
                "check_ids": list(unexpected_checks),
                "message": "Remove review observations that were not part of this exact prepared request.",
            }
        )
    return actions


def guard_report(
    *,
    document: Any,
    receipts: list[Mapping[str, Any]],
    signals: list[dict[str, Any]],
    route_policy: Mapping[str, Any],
    score_policy: Mapping[str, Any],
    candidate_request_sha256: str,
    skipped_reviews: Iterable[Mapping[str, Any]] = (),
    analysis_ownership: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    model_observations, principles = _principle_registry(signals)
    atomicity = compose_atomicity(receipts, model_observations)
    policy_signals = [
        signal
        for signal in model_observations
        if not is_pair_observation(signal["check_id"]) and not signal.get("advisory_only")
    ]
    policy_signals.extend(item for item in atomicity if item["minimum_support_index"] is not None)
    feedback = actionable_feedback(
        [*model_observations, *(item for item in atomicity if item["minimum_support_index"] is not None)], route_policy
    )
    selected_route = route(policy_signals, route_policy)
    expected_workflow_checks = {
        check_id
        for item in (analysis_ownership or {}).get("semantic", [])
        if item["scope"] == "workflow"
        for check_id in item["check_ids"]
    }
    scoring = score_reviews(receipts, model_observations, score_policy, skipped_reviews, expected_workflow_checks)
    if selected_route == "ready_for_small_trial" and scoring["workflow"]["status"] == "not_reviewed":
        selected_route = "ready_for_small_trial_questions_only"
    policy_observations = [signal for signal in model_observations if not signal.get("advisory_only")]
    policy_fingerprints = {signal["review_fingerprint"] for signal in policy_observations}
    all_served_models = sorted(
        {
            str(signal["response_model"])
            for signal in model_observations
            if isinstance(signal.get("response_model"), str)
        }
    )
    served_models = sorted(
        {
            str(signal["response_model"])
            for signal in policy_observations
            if isinstance(signal.get("response_model"), str)
        }
    )
    missing_response_models = sum(not isinstance(signal.get("response_model"), str) for signal in policy_observations)
    mixed_served_models = len(served_models) > 1
    model_identity_incomplete = mixed_served_models or missing_response_models > 0
    reused_alias_version_unverified = any(
        receipt.get("guard_source") == "reused"
        and receipt["review_fingerprint"] in policy_fingerprints
        and str(receipt.get("submitted", {}).get("model", "")).endswith("-latest")
        for receipt in receipts
    )
    if (
        model_identity_incomplete
        or reused_alias_version_unverified
        or scoring["request"]["status"] != "complete"
        or scoring["workflow"]["status"] == "incomplete"
    ) and selected_route in {
        "ready_for_small_trial",
        "ready_for_small_trial_questions_only",
    }:
        selected_route = "review_required"
    flag_at_value = route_policy.get("flag_at")
    critical_conditions = [
        {
            "question": signal.get("candidate_question_id"),
            "check": signal["check_id"],
            ("minimum_support_index" if "minimum_support_index" in signal else "probability"): _policy_value(signal),
            "recommended_action": CHECK_ACTIONS[base_check_id(signal["check_id"])],
        }
        for signal in policy_signals
        if isinstance(flag_at_value, (int, float)) and _policy_value(signal) >= flag_at_value
    ]
    dimensions: dict[str, list[str]] = {}
    for signal in model_observations:
        dimensions.setdefault(str(signal.get("dimension")), []).append(signal["check_id"])
    uncertain_conditions = []
    if route_policy["kind"] != "no_threshold_policy":
        uncertain_conditions = [
            {
                "question": signal.get("candidate_question_id"),
                "check": signal["check_id"],
                ("minimum_support_index" if "minimum_support_index" in signal else "probability"): _policy_value(
                    signal
                ),
            }
            for signal in policy_signals
            if route_policy["clear_below"] < _policy_value(signal) < route_policy["flag_at"]
        ]
    missing_information = []
    for question in scoring["questions"]:
        if question["status"] == "complete":
            continue
        repair_actions = _coverage_repair_actions(question)
        missing_information.append(
            {
                "question": question["question"],
                "missing_check_ids": question["coverage"]["missing_check_ids"],
                "missing_dimensions": question["coverage"]["missing_dimensions"],
                "unresolved_backticked_paths": question["coverage"]["unresolved_backticked_paths"],
                "repair_actions": repair_actions,
                "repair": " ".join(action["message"] for action in repair_actions),
            }
        )
    if scoring["workflow"]["status"] == "not_reviewed":
        missing_information.append({"workflow": scoring["workflow"]["coverage"]["reason"]})
    elif scoring["workflow"]["status"] == "incomplete":
        missing_information.append({"workflow": scoring["workflow"]["coverage"]})
    if mixed_served_models:
        missing_information.append(
            {"reason": "review responses came from different concrete model versions", "served_models": served_models}
        )
    if missing_response_models:
        missing_information.append(
            {
                "reason": "one or more review observations have no concrete response model",
                "observation_count": missing_response_models,
            }
        )
    if reused_alias_version_unverified:
        missing_information.append(
            {
                "reason": (
                    "Reused alias receipts describe the recorded model; the alias's current version is unverified."
                ),
                "served_models": served_models,
            }
        )
    return {
        "schema_version": 2,
        "kind": "guard",
        "status": "complete",
        "document_fingerprint": fingerprint(document),
        "route": selected_route,
        "policy": route_policy,
        "review_inputs": _review_input_registry(receipts),
        "principles": principles,
        "model_observations": model_observations,
        "scoring": scoring,
        "atomicity_assessments": atomicity,
        "criteria_condition_assessments": compose_conditions(receipts, model_observations, route_policy),
        **({"analysis_ownership": dict(analysis_ownership)} if analysis_ownership is not None else {}),
        "feedback": feedback,
        "dimensions": dimensions,
        "review_fingerprints": [receipt.get("review_fingerprint") for receipt in receipts],
        "candidate_request_sha256": candidate_request_sha256,
        "review_request_sha256": sorted(
            {str(receipt["request_sha256"]) for receipt in receipts if receipt.get("request_sha256")}
        ),
        "policy_conclusions": {
            "source": "deterministic_guard_policy",
            "route": selected_route,
            "recommended_next_action": selected_route,
            "question_design_score": scoring["request"]["design_score"],
            "workflow_score": scoring["workflow"]["score"],
            "critical_conditions": critical_conditions,
            "uncertain_conditions": uncertain_conditions,
            "served_models": served_models,
            "all_observation_served_models": all_served_models,
            "mixed_served_models": mixed_served_models,
            "reused_alias_version_unverified": reused_alias_version_unverified,
            "missing_response_model_observations": missing_response_models,
            "missing_information": missing_information,
        },
        "meaning": (
            "This route controls the next experiment step. It is not approval, quality "
            "certification, or measured correctness."
        ),
    }
