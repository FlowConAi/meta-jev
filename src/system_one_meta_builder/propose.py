"""Host-LLM authoring briefs; this module never calls a generative model."""

from __future__ import annotations

from typing import Any

from .sdk import question_schema


def proposal_brief(
    *, question: str | None, goal: str | None, setup: Any, evidence: list[dict[str, str]]
) -> dict[str, Any]:
    official_question_schema = question_schema()
    definitions = official_question_schema.pop("$defs", {})
    starting_point: dict[str, Any] = {}
    if question:
        starting_point["initial_question"] = question
    if goal:
        starting_point["research_goal"] = goal
    if setup is not None:
        starting_point["research_setup"] = setup
    return {
        "kind": "system_one_meta_builder_proposal",
        "starting_point": starting_point,
        "evidence": evidence,
        "host_llm_task": [
            "Work backward from the decision the consuming code needs.",
            "Keep deterministic lookup, calculation, execution, and policy in code.",
            "Propose independent Noul, Choice, or Score questions over the supplied state.",
            (
                "Do not replace a genuine single relation, ordered degree, or specified "
                "aggregate with word-level fragments."
            ),
            "For each question, name its intended downstream use and the case-specific evidence it requires.",
            (
                "Return candidate JSON only; the host LLM may add, revise, or drop questions "
                "after review and observations."
            ),
        ],
        "candidate_contract": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": definitions,
            "type": "object",
            "required": ["request"],
            "properties": {
                "request": {
                    "type": "object",
                    "required": ["state", "questions"],
                    "properties": {
                        "state": {},
                        "questions": {
                            "type": "object",
                            "minProperties": 1,
                            "additionalProperties": official_question_schema,
                        },
                        "model": {"type": "string", "default": "jev-latest"},
                    },
                },
                "intended_uses": {"type": "object", "additionalProperties": {}},
                "workflow": {
                    "type": "object",
                    "properties": {
                        "purpose": {"type": "string"},
                        "consumer_code": {"type": "string"},
                    },
                },
            },
        },
        "next_step": (
            "Write the candidate JSON, then run `system-one-meta-builder prepare -` and `guard - --output FILE`."
        ),
    }
