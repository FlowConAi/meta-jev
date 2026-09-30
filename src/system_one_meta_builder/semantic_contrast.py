"""Host-bound semantic term contrasts for advisory review."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .io import InputError, question_review_context, resolve_path


def _required_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{path} must be a nonempty string")
    return value


def _resolve_selected_text(request_state: Any, candidate_question: Mapping[str, Any], path: str) -> str:
    if path == "request_state":
        current = request_state
        remainder = ""
    elif path.startswith("request_state."):
        current = request_state
        remainder = path[len("request_state.") :]
    elif path == "candidate_question":
        current = candidate_question
        remainder = ""
    elif path.startswith("candidate_question."):
        current = candidate_question
        remainder = path[len("candidate_question.") :]
    else:
        raise InputError("semantic term contrast selected_path must start with request_state or candidate_question")

    try:
        current = resolve_path(current, remainder)
    except (IndexError, KeyError) as error:
        raise InputError(f"semantic term contrast selected_path does not resolve: {path!r}") from error
    if not isinstance(current, str):
        raise InputError(f"semantic term contrast selected_path must resolve to text: {path!r}")
    return current


def _definition(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InputError(f"{path} must be an object")
    provenance = value.get("provenance")
    if not isinstance(provenance, Mapping):
        raise InputError(f"{path}.provenance must be an object")
    kind = provenance.get("kind")
    if kind not in {"request_grounded", "constructed_diagnostic"}:
        raise InputError(f"{path}.provenance.kind must be request_grounded or constructed_diagnostic")
    return {
        "id": _required_string(value.get("id"), f"{path}.id"),
        "text": _required_string(value.get("text"), f"{path}.text"),
        "provenance": {
            "kind": kind,
            "source_anchor": _required_string(provenance.get("source_anchor"), f"{path}.provenance.source_anchor"),
        },
    }


def _validate_reference_answer(value: Any, question: Mapping[str, Any], path: str) -> None:
    primitive = question["type"]
    if primitive == "noul":
        valid = isinstance(value, bool)
        expected = "a boolean for Noul"
    elif primitive == "choice":
        valid = isinstance(value, str) and value in question["criteria"]
        expected = "a key from the Choice criteria"
    else:
        valid = type(value) is int and 0 <= value < len(question["criteria"])
        expected = "a zero-based Score anchor index"
    if not valid:
        raise InputError(f"{path} must be {expected}")


def semantic_term_contrasts(
    document: Mapping[str, Any],
    question_id: str,
    request_state: Any,
    candidate_question: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Validate exact host evidence and keep labels outside the model-visible form."""
    question_context = question_review_context(document, question_id)
    raw_contrasts = question_context.get("semantic_term_contrasts")
    if raw_contrasts is None:
        return []
    if not isinstance(raw_contrasts, list) or not raw_contrasts:
        raise InputError(f"review_context.questions.{question_id}.semantic_term_contrasts must be a nonempty array")

    contrasts: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw in enumerate(raw_contrasts):
        path = f"review_context.questions.{question_id}.semantic_term_contrasts[{index}]"
        if not isinstance(raw, Mapping):
            raise InputError(f"{path} must be an object")
        contrast_id = _required_string(raw.get("contrast_id"), f"{path}.contrast_id")
        if contrast_id in ids:
            raise InputError(f"{path}.contrast_id duplicates {contrast_id!r}")
        ids.add(contrast_id)
        selected_path = _required_string(raw.get("selected_path"), f"{path}.selected_path")
        selected_text = _resolve_selected_text(request_state, candidate_question, selected_path)
        quoted_term = _required_string(raw.get("quoted_term"), f"{path}.quoted_term")
        occurrence_index = raw.get("occurrence_index")
        if isinstance(occurrence_index, bool) or not isinstance(occurrence_index, int) or occurrence_index < 0:
            raise InputError(f"{path}.occurrence_index must be a nonnegative integer")
        if occurrence_index >= selected_text.count(quoted_term):
            raise InputError(f"{path} selected occurrence is absent from selected_path")

        definition_a = _definition(raw.get("definition_a"), f"{path}.definition_a")
        definition_b = _definition(raw.get("definition_b"), f"{path}.definition_b")
        if definition_a["id"] == definition_b["id"] or definition_a["text"] == definition_b["text"]:
            raise InputError(f"{path} must supply two distinct definitions")
        differing_case = raw.get("differing_answer_case")
        if not isinstance(differing_case, Mapping):
            raise InputError(f"{path}.differing_answer_case must be an object")
        answer_a = differing_case.get("answer_under_a")
        answer_b = differing_case.get("answer_under_b")
        for side, answer in (("a", answer_a), ("b", answer_b)):
            _validate_reference_answer(answer, candidate_question, f"{path}.differing_answer_case.answer_under_{side}")
        if answer_a == answer_b:
            raise InputError(f"{path}.differing_answer_case must have different typed answers")
        contrasts.append(
            {
                "contrast_id": contrast_id,
                "selected_path": selected_path,
                "selected_text": selected_text,
                "quoted_term": quoted_term,
                "occurrence_index": occurrence_index,
                "definition_a": definition_a,
                "definition_b": definition_b,
                "differing_answer_case": {
                    "source_anchor": _required_string(
                        differing_case.get("source_anchor"), f"{path}.differing_answer_case.source_anchor"
                    ),
                    "answer_under_a": answer_a,
                    "answer_under_b": answer_b,
                },
            }
        )
    return contrasts


def model_semantic_term_contrasts(contrasts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose only the contrast needed for judgment; host labels and provenance stay in receipts."""
    return [
        {
            "contrast_id": contrast["contrast_id"],
            "selected_path": contrast["selected_path"],
            "quoted_term": contrast["quoted_term"],
            "occurrence_index": contrast["occurrence_index"],
            "definition_a": {key: contrast["definition_a"][key] for key in ("id", "text")},
            "definition_b": {key: contrast["definition_b"][key] for key in ("id", "text")},
        }
        for contrast in contrasts
    ]
