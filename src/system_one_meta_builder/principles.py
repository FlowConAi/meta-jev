"""Canonical, source-backed principles used by the request reviewer."""

from __future__ import annotations

from typing import Any

LESSONS_PATH = "src/system_one_meta_builder/principles.py"
HOW_TO_BUILD_PATH = "https://docs.typesafe.ai/concepts/how-to-build-with-system-one"
STATE_PATH = "https://docs.typesafe.ai/concepts/state"
PRIMITIVES_PATH = "https://docs.typesafe.ai/primitives"
CHOICE_PATH = "https://docs.typesafe.ai/primitives/choice"
NOUL_PATH = "https://docs.typesafe.ai/primitives/noul"
SCORE_PATH = "https://docs.typesafe.ai/primitives/score"
CONFIDENCE_PATH = "https://docs.typesafe.ai/confidence"
COMPOSITE_PATH = "https://docs.typesafe.ai/patterns/composite-scoring"
JAGGEDNESS_PATH = "https://docs.typesafe.ai/model-jaggedness/jev-1.13"


def _official(
    dimension: str,
    rule: str,
    source_url: str,
    section: str,
    *,
    source_path: str,
    source_excerpt: str,
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "rule": rule,
        "source_url": source_url,
        "source_path": source_path,
        "source_excerpt": source_excerpt,
        "section": section,
        "origin": "official_documentation",
        "passage_kind": "verbatim_official_documentation",
    }


def _local(
    dimension: str,
    rule: str,
    section: str,
    *,
    source_url: str = "https://docs.typesafe.ai/concepts/how-to-build-with-system-one",
    source_excerpt: str,
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "rule": rule,
        "source_url": source_url,
        "source_path": LESSONS_PATH,
        "section": section,
        "origin": "local_experiment_rule",
        "source_excerpt": source_excerpt,
        "passage_kind": "local_experiment_rule",
    }


PRINCIPLES: dict[str, dict[str, Any]] = {
    "decompose_independent_properties": _official(
        "atomicity",
        "Ask separately for independent outputs the consumer needs, then combine their answers in code.",
        "https://docs.typesafe.ai/concepts/how-to-build-with-system-one#decompose-the-questions",
        "Decompose the questions",
        source_path=HOW_TO_BUILD_PATH,
        source_excerpt=(
            "Ask the most explicit, narrow, specific, atomic questions you can. Break down complex or "
            "ill-defined questions into separate questions that each evaluate one property."
        ),
    ),
    "name_the_judged_property": _official(
        "question_clarity",
        "State which entity and property, relation, category, or ordered degree the typed answer represents.",
        "https://docs.typesafe.ai/primitives#define-a-question",
        "Define a question",
        source_path=PRIMITIVES_PATH,
        source_excerpt=("Write it as a clear, specific question, or as a statement for the model to judge."),
    ),
    "write_direct_comprehensible_questions": _official(
        "question_clarity",
        "Write instructions directly, without nested negation, unclear attachment, or avoidable indirection.",
        "https://docs.typesafe.ai/model-jaggedness/jev-1.13#indirection",
        "Jev 1.13 jaggedness / Indirection",
        source_path=JAGGEDNESS_PATH,
        source_excerpt=(
            "**Instead:** write your instructions as directly as possible. When possible, identify the relevant "
            "parts of state by name."
        ),
    ),
    "resolve_decision_terms": _official(
        "question_clarity",
        (
            "State the exact condition and select between supplied alternative definitions when they produce "
            "different typed answers."
        ),
        "https://docs.typesafe.ai/model-jaggedness/jev-1.13#literal-reading",
        "Jev 1.13 jaggedness / Literal reading",
        source_path=JAGGEDNESS_PATH,
        source_excerpt=(
            "**Instead:** state the exact condition in the `instructions`. Be specific. "
            "Put boundary cases in the criteria."
        ),
    ),
    "identify_question_references": _official(
        "question_clarity",
        (
            "Point instructions at the specific state values and entities they judge when more than "
            "one reference could fit."
        ),
        "https://docs.typesafe.ai/primitives#reference-specific-fields",
        "Reference specific fields",
        source_path=PRIMITIVES_PATH,
        source_excerpt=(
            "When a question is about one of those parts, name it in the `instructions` with a "
            "dot-and-index path to its key, including the backticks."
        ),
    ),
    "make_state_comprehensible": _local(
        "state_clarity",
        (
            "Review the supplied state's language separately from question wording; a needed "
            "component can have one meaning yet remain difficult to parse."
        ),
        "Authoring rules / Comprehension, ambiguity and atomicity are separate signals",
        source_url="https://docs.typesafe.ai/concepts/state#state-can-be-a-simple-string-or-a-structured-json-value",
        source_excerpt=("A question can have one meaning yet use nested negation or unclear clause attachment."),
    ),
    "name_state_component_role": _official(
        "state_clarity",
        "Name and structure a state component so its semantic role in the judgment is identifiable.",
        "https://docs.typesafe.ai/concepts/state#state-can-be-a-simple-string-or-a-structured-json-value",
        "State can be a simple string or a structured JSON value",
        source_path=STATE_PATH,
        source_excerpt=(
            "Use an object for most requests so each part of the state has a descriptive name and its "
            "relationships remain clear."
        ),
    ),
    "identify_state_component_entity": _local(
        "state_clarity",
        "A needed state value must identify which entity or subject it describes when several could fit.",
        "Authoring rules / Comprehension, ambiguity and atomicity are separate signals",
        source_url="https://docs.typesafe.ai/primitives#reference-specific-fields",
        source_excerpt=("Keep role, entity, unit and timeframe checks separate when their answers can differ."),
    ),
    "identify_state_component_unit": _local(
        "state_clarity",
        "A needed state value must identify its unit when different units would change the answer.",
        "Authoring rules / Comprehension, ambiguity and atomicity are separate signals",
        source_url="https://docs.typesafe.ai/concepts/state",
        source_excerpt=("Keep role, entity, unit and timeframe checks separate when their answers can differ."),
    ),
    "identify_state_component_timeframe": _local(
        "state_clarity",
        "A needed state value must identify its timeframe when different timeframes would change the answer.",
        "Authoring rules / Comprehension, ambiguity and atomicity are separate signals",
        source_url="https://docs.typesafe.ai/concepts/state",
        source_excerpt=("Keep role, entity, unit and timeframe checks separate when their answers can differ."),
    ),
    "identify_state_reference_target": _official(
        "state_clarity",
        "Select the exact supplied item, entity, baseline, or comparison target when several targets could fit.",
        "https://docs.typesafe.ai/primitives#reference-specific-fields",
        "Reference specific fields",
        source_path=PRIMITIVES_PATH,
        source_excerpt=("Explicit paths make it clear which parts of a structured state should inform each judgment."),
    ),
    "supply_case_evidence": _official(
        "evidence_sufficiency",
        (
            "Supply the case-specific facts needed by the judgment; ordinary semantic knowledge does "
            "not replace unavailable current facts or implementation evidence."
        ),
        "https://docs.typesafe.ai/concepts/how-to-build-with-system-one#decompose-the-input-state",
        "Decompose the input state",
        source_path=HOW_TO_BUILD_PATH,
        source_excerpt=(
            "Do not rely on knowledge stored in model weights when current information can come from your own "
            "knowledge base."
        ),
    ),
    "consistent_criteria": _local(
        "question_clarity",
        "Criteria must not assign the same concrete case to conflicting typed outcomes.",
        "State, instructions and answer boundaries / Make criteria define one consistent boundary",
        source_url="https://docs.typesafe.ai/primitives/advanced#structured-noul-criteria",
        source_excerpt=(
            "True and false must describe opposing outcomes of the same proposition. Check exclusions against "
            "the positive definition; an example must not satisfy both merely because one side uses a broader term."
        ),
    ),
    "instructions_align_with_criteria": _official(
        "question_clarity",
        "Treat criteria as an extension of the instruction; align their subject, direction, and answer meaning.",
        "https://docs.typesafe.ai/model-jaggedness/jev-1.13#contradictory-instructions-and-criteria",
        "Jev 1.13 jaggedness / Contradictory instructions and criteria",
        source_path=JAGGEDNESS_PATH,
        source_excerpt=(
            "**Instead:** treat the criteria as an extension of the instruction. Align the two using clear and "
            "precise language."
        ),
    ),
    "noul_criteria_are_optional": _official(
        "question_clarity",
        (
            "Noul criteria are optional; add true and false descriptions when the yes/no boundary "
            "is subtle, and otherwise let clear instructions stand alone."
        ),
        "https://docs.typesafe.ai/primitives/noul#design-guidance",
        "Noul / Design guidance",
        source_path=NOUL_PATH,
        source_excerpt=(
            'Make the boundary between yes and no unambiguous. "Does this candidate have any Python experience?" '
            'works well because "any" leaves no middle ground. When the boundary is subtle, add `criteria` with '
            "`true` and `false` descriptions, as the `is_repeat_contact` question above does. The instruction is "
            "enough for most Nouls, so try your questions with and without `criteria` and keep whichever gives "
            "better answers on your documents."
        ),
    ),
    "choice_is_one_selection": _official(
        "primitive_suitability",
        (
            "Use Choice for one selection among competing alternatives; use independent Nouls when "
            "several properties may hold at once."
        ),
        "https://docs.typesafe.ai/primitives/choice",
        "Choice",
        source_path=CHOICE_PATH,
        source_excerpt="Use a Choice when the answer is one of a fixed set of options.",
    ),
    "cover_choice_outcomes_for_case": _official(
        "primitive_suitability",
        (
            "Add a no-match option when the declared alternatives do not cover an input the question "
            "is intended to handle."
        ),
        "https://docs.typesafe.ai/primitives#choose-a-question-type",
        "Choose a question type",
        source_path=PRIMITIVES_PATH,
        source_excerpt=(
            "Give the full list of options, and add an `other` or `none of the above` option when the list "
            "might not cover every input."
        ),
    ),
    "score_is_ordered": _official(
        "primitive_suitability",
        "Use Score for ordered levels of one described dimension.",
        "https://docs.typesafe.ai/primitives/score#writing-good-levels",
        "Writing good levels",
        source_path=SCORE_PATH,
        source_excerpt="Keep each Score question to one dimension.",
    ),
    "score_levels_are_concrete": _official(
        "primitive_suitability",
        (
            "Describe standalone situations at each Score level rather than labels such as low, "
            "moderate, or high with no matching situation."
        ),
        "https://docs.typesafe.ai/primitives/score#writing-good-levels",
        "Writing good levels",
        source_path=SCORE_PATH,
        source_excerpt=(
            'Describe situations, not degrees. "Broken or degraded feature, but workaround exists" gives the '
            'model something to match the state against. "Moderately severe" doesn\'t.'
        ),
    ),
    "noul_is_one_proposition": _official(
        "primitive_suitability",
        (
            "Use Noul for the probability that one stated proposition is true; use Choice for one "
            "selection and Score for degree."
        ),
        "https://docs.typesafe.ai/primitives/noul#writing-a-noul-question",
        "Writing a Noul question",
        source_path=NOUL_PATH,
        source_excerpt=(
            'Ask one yes/no question per Noul. If a question has two conditions, such as "Is the customer angry '
            'and asking for a refund?", the model has to judge both at once and the value means less.'
        ),
    ),
    "model_judges_code_acts": _official(
        "task_suitability",
        "System One returns typed judgments; code owns generation, tools, control flow, and side effects.",
        "https://docs.typesafe.ai/concepts/how-to-build-with-system-one#design-a-system-one-workflow",
        "Design a System One workflow",
        source_path=HOW_TO_BUILD_PATH,
        source_excerpt=("Keep control flow, deterministic rules, and side effects in code."),
    ),
    "consumer_claims_follow_evidence": _official(
        "workflow_consumption",
        (
            "At each answer-consumption site, code may claim only what the relevant answers, "
            "deterministic facts, and explicit composition policy establish."
        ),
        "https://docs.typesafe.ai/concepts/how-to-build-with-system-one#combine-question-outputs-in-code-or-feed-into-a-classical-ml-model",
        "Combine question outputs in code",
        source_path=HOW_TO_BUILD_PATH,
        source_excerpt="Combine independent answers with deterministic rules or weighted sums.",
    ),
    "confidence_is_not_accuracy": _official(
        "workflow_weighting",
        (
            "Choice and Score confidence describes distribution concentration, not observed "
            "correctness; a Noul has no separate confidence field."
        ),
        "https://docs.typesafe.ai/confidence#confidence-is-derived-from-the-probabilities",
        "Confidence is derived from the probabilities",
        source_path=CONFIDENCE_PATH,
        source_excerpt=(
            "`confidence` is a statistic computed from the probability distribution the answer already gives you."
        ),
    ),
    "option_probability_is_not_provider_confidence": _official(
        "workflow_weighting",
        (
            "Keep a selected option's probability distinct from the provider confidence statistic "
            "derived from the full Choice or Score distribution."
        ),
        "https://docs.typesafe.ai/primitives#what-comes-back",
        "What comes back",
        source_path=PRIMITIVES_PATH,
        source_excerpt=(
            "`choice` is the selected option. `probabilities` is the distribution across every option. `confidence` "
            "summarizes how peaked that distribution is."
        ),
    ),
    "noul_probability_is_not_degree": _official(
        "workflow_weighting",
        "A Noul is the probability that its proposition is true, not the intensity or degree of the subject.",
        "https://docs.typesafe.ai/primitives/noul#reading-a-noul",
        "Reading a Noul",
        source_path=NOUL_PATH,
        source_excerpt=(
            "A Noul value runs from 0 to 1, but it's not a scale of the thing you asked about. It is the "
            "probability that the answer is yes."
        ),
    ),
    "preserve_missing_evidence": _local(
        "workflow_consumption",
        "Keep missing evidence distinct from a substantive negative answer.",
        "Question decomposition and the meta builder",
        source_excerpt=("Unresolved wiring is incomplete evidence, not a clean bill of health."),
    ),
    "weighting_is_explicit_policy": _official(
        "workflow_weighting",
        "When code combines independent answers, state the decision role and weights explicitly.",
        "https://docs.typesafe.ai/patterns/composite-scoring#step-2-combine-with-weights",
        "Composite scoring / Combine with weights",
        source_path=COMPOSITE_PATH,
        source_excerpt=(
            "break the judgment into independent dimensions, score each one separately, and combine them "
            "with weights you control in code."
        ),
    ),
    "prerequisites_do_not_compensate": _local(
        "workflow_weighting",
        (
            "Keep a required prerequisite as an individual condition instead of allowing unrelated "
            "strengths to average it away."
        ),
        "Question decomposition and the meta builder / Return the evidence and the computed judgment",
        source_url="https://docs.typesafe.ai/patterns/composite-scoring",
        source_excerpt=(
            "Critical defects remain individually actionable and cannot be cancelled by unrelated strengths."
        ),
    ),
    "normalize_scores_before_combining": _official(
        "workflow_weighting",
        "Normalize Score positions to a comparable range before combining dimensions with different level counts.",
        "https://docs.typesafe.ai/patterns/composite-scoring#step-2-combine-with-weights",
        "Composite scoring / Combine with weights",
        source_path=COMPOSITE_PATH,
        source_excerpt="Each dimension is normalized to 0–1 and weighted.",
    ),
    "do_not_invent_joint_probability": _local(
        "workflow_weighting",
        (
            "Do not label arithmetic over correlated Noul probabilities as a joint probability "
            "without an independently justified model."
        ),
        "Design for a reusable real-world decision / Code owns composition and escalation",
        source_url="https://docs.typesafe.ai/concepts/how-to-build-with-system-one#combine-question-outputs-in-code-or-feed-into-a-classical-ml-model",
        source_excerpt=(
            "Do not multiply correlated signals into invented confidence or let strengths on unrelated dimensions "
            "cancel a critical design defect."
        ),
    ),
    "deterministic_rules_stay_in_code": _official(
        "workflow_consumption",
        "Use code for a decision fully determined by supplied explicit rules; use System One for semantic judgment.",
        "https://docs.typesafe.ai/concepts/how-to-build-with-system-one#use-code-when-you-can",
        "Use code when you can",
        source_path=HOW_TO_BUILD_PATH,
        source_excerpt="Keep deterministic work in code. It is reliable and cheap.",
    ),
}


def selected_principles(ids: set[str]) -> dict[str, dict[str, Any]]:
    """Return only the relevant rule and source passage; full provenance stays outside model state."""
    return {
        principle_id: {
            "rule": PRINCIPLES[principle_id]["rule"],
            "source_excerpt": PRINCIPLES[principle_id]["source_excerpt"],
        }
        for principle_id in sorted(ids)
    }


def principle_provenance(ids: set[str]) -> dict[str, dict[str, Any]]:
    """Return full source metadata for prepared output and durable receipts."""
    return {principle_id: PRINCIPLES[principle_id] for principle_id in sorted(ids)}
