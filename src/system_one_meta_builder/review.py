"""Source-grounded, independent meta-questions for proposed System One requests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

from typesafe_sdk import Noul

from .consumer import inspect_python_consumer
from .criteria_conditions import CHECK_ID as CONDITION_CHECK_ID
from .criteria_conditions import CHECK_SPEC as CONDITION_CHECK_SPEC
from .criteria_conditions import condition_review_requests
from .io import InputError, fingerprint, question_review_context, resolve_path
from .principles import PRINCIPLES, principle_provenance, selected_principles
from .sdk import DEFAULT_MODEL, validate_question
from .semantic_contrast import model_semantic_term_contrasts, semantic_term_contrasts


def _criteria(
    defect: str,
    acceptable: str,
    *,
    defect_not_for: str,
    acceptable_not_for: str,
    defect_example: str,
    acceptable_example: str,
) -> dict[str, dict[str, Any]]:
    return {
        "true": {
            "what": defect,
            "not_for": defect_not_for,
            "examples": [defect_example],
        },
        "false": {
            "what": acceptable,
            "not_for": acceptable_not_for,
            "examples": [acceptable_example],
        },
    }


def _check(
    principle_id: str,
    question: str,
    *,
    inspect: str | list[str],
    focus: str,
    guidance: str,
    criteria: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "principle_ids": [principle_id],
        "instructions": {
            "question": question,
            "inspect": inspect,
            "apply_principle": f"principles.{principle_id}.rule",
            "focus": focus,
        },
        "criteria": criteria,
        "guidance": guidance,
    }


ATOMICITY_PAIR_CHECKS: dict[str, dict[str, Any]] = {
    "atomicity_requires_proposition_a": _check(
        "decompose_independent_properties",
        "Does `candidate_question` ask the model to check proposition A?",
        inspect=["candidate_question"],
        focus=(
            "Judge proposition A only. Do not decide whether A is true in the supplied case, proposition B, "
            "whether A and B are independent, or whether the candidate question is well designed. A fact used "
            "only as evidence does not count as a condition the question asks the model to check."
        ),
        guidance="Inspect whether the candidate asks the model to check proposition A as a condition.",
        criteria=_criteria(
            "The candidate question asks the model to check the exact proposition A as one of its conditions.",
            "The candidate question does not ask the model to check the exact proposition A as a condition.",
            defect_not_for="A fact that merely informs a category, relation, or dimension without being an output.",
            acceptable_not_for="A differently worded condition that still settles the exact proposition A.",
            defect_example="A yes/no answer explicitly requires deciding whether logging is preserved.",
            acceptable_example=(
                "A route category uses logging as evidence but does not answer whether logging is preserved."
            ),
        ),
    ),
    "atomicity_requires_proposition_b": _check(
        "decompose_independent_properties",
        "Does `candidate_question` ask the model to check proposition B?",
        inspect=["candidate_question"],
        focus=(
            "Judge proposition B only. Do not decide whether B is true in the supplied case, proposition A, "
            "whether A and B are independent, or whether the candidate question is well designed. A fact used "
            "only as evidence does not count as a condition the question asks the model to check."
        ),
        guidance="Inspect whether the candidate asks the model to check proposition B as a condition.",
        criteria=_criteria(
            "The candidate question asks the model to check the exact proposition B as one of its conditions.",
            "The candidate question does not ask the model to check the exact proposition B as a condition.",
            defect_not_for="A fact that merely informs a category, relation, or dimension without being an output.",
            acceptable_not_for="A differently worded condition that still settles the exact proposition B.",
            defect_example="A yes/no answer explicitly requires deciding whether invalid input is rejected.",
            acceptable_example=(
                "A route category uses input validity as evidence but does not answer whether it is rejected."
            ),
        ),
    ),
}


SEMANTIC_CONTRAST_CHECKS: dict[str, dict[str, Any]] = {
    "decision_term_rules_out_definition_a": _check(
        "resolve_decision_terms",
        "Does the selected candidate wording rule out definition A for the selected term occurrence?",
        inspect=["request_state", "candidate_question", "semantic_term_contrasts"],
        focus="Use only a distinguishing condition stated in the actual candidate wording.",
        guidance="Inspect which supplied definition the exact candidate wording excludes.",
        criteria=_criteria(
            "The candidate wording states a distinguishing condition incompatible with definition A.",
            "No supplied distinguishing condition rules out definition A for this occurrence.",
            defect_not_for="A preference or provenance statement outside the candidate wording.",
            acceptable_not_for="Proof that definition A is the intended or correct definition.",
            defect_example="The wording explicitly restricts the term to a condition excluded by definition A.",
            acceptable_example="The wording leaves definition A compatible or does not distinguish it.",
        ),
    ),
    "decision_term_rules_out_definition_b": _check(
        "resolve_decision_terms",
        "Does the selected candidate wording rule out definition B for the selected term occurrence?",
        inspect=["request_state", "candidate_question", "semantic_term_contrasts"],
        focus="Use only a distinguishing condition stated in the actual candidate wording.",
        guidance="Inspect which supplied definition the exact candidate wording excludes.",
        criteria=_criteria(
            "The candidate wording states a distinguishing condition incompatible with definition B.",
            "No supplied distinguishing condition rules out definition B for this occurrence.",
            defect_not_for="A preference or provenance statement outside the candidate wording.",
            acceptable_not_for="Proof that definition B is the intended or correct definition.",
            defect_example="The wording explicitly restricts the term to a condition excluded by definition B.",
            acceptable_example="The wording leaves definition B compatible or does not distinguish it.",
        ),
    ),
}
for _semantic_contrast_check in SEMANTIC_CONTRAST_CHECKS.values():
    _semantic_contrast_check["advisory_only"] = True
del _semantic_contrast_check


PER_QUESTION_CHECKS: dict[str, dict[str, Any]] = {
    "does_not_name_judged_property": _check(
        "name_the_judged_property",
        (
            "Is the entity and property, relation, category, or ordered degree represented by "
            "`candidate_question` missing?"
        ),
        inspect=["candidate_question.instructions", "candidate_question.criteria"],
        focus="The question id is unavailable to the candidate model and cannot supply missing meaning.",
        guidance="Name the exact entity and property, relation, category, or degree represented by the answer.",
        criteria=_criteria(
            "The typed answer's subject or judged property cannot be stated without inventing intent.",
            "The instructions and criteria identify both the subject and what the answer represents.",
            defect_not_for="A short question whose subject and property are still explicit.",
            acceptable_not_for="Meaning supplied only by the question id or consuming variable name.",
            defect_example="Instructions ask whether the supplied item is good without naming the judged property.",
            acceptable_example="Instructions ask whether `message` requests a refund.",
        ),
    ),
    "question_wording_is_hard_to_understand": _check(
        "write_direct_comprehensible_questions",
        (
            "Is the wording of `candidate_question` difficult for an average reader to parse even if "
            "one meaning can be recovered?"
        ),
        inspect=["candidate_question.instructions", "candidate_question.criteria"],
        focus=(
            "Look for nested negation, unclear clause attachment, or multi-hop indirection that requires rereading. "
            "Do not flag length, technical vocabulary, structured fields, or one ordinary negation by themselves."
        ),
        guidance="Rewrite the difficult clause directly while preserving the same judgment boundary.",
        criteria=_criteria(
            "A reader can recover one meaning only after resolving avoidable syntactic or referential indirection.",
            "The wording communicates its meaning directly enough for an average reader.",
            defect_not_for="Technical terms that are defined or ordinary direct conditional wording.",
            acceptable_not_for=(
                "Wording that becomes clear only after unpacking nested negation or unclear clause attachment."
            ),
            defect_example="A nested negative condition requires reversing the proposition twice.",
            acceptable_example="Does `message` ask the recipient to provide a password?",
        ),
    ),
    "question_meaning_is_unrecoverable": _check(
        "write_direct_comprehensible_questions",
        (
            "Is an essential part of `candidate_question` impossible to interpret from its wording, "
            "criteria, state, and ordinary knowledge?"
        ),
        inspect=["request_state", "candidate_question.instructions", "candidate_question.criteria"],
        focus=(
            "This is stronger than hard wording: no stable meaning can be recovered without guessing "
            "a private abbreviation, "
            "omitted definition, or missing relation."
        ),
        guidance=(
            "Define the unrecoverable abbreviation, relation, or instruction before reviewing its decision boundary."
        ),
        criteria=_criteria(
            "An essential phrase has no recoverable meaning without guessing information not supplied.",
            "The question has a recoverable meaning using the supplied contract and ordinary knowledge.",
            defect_not_for="A difficult sentence that still has one recoverable meaning.",
            acceptable_not_for="A private abbreviation or relation whose meaning must be invented.",
            defect_example="The instruction relies on an undefined project-only acronym that controls the answer.",
            acceptable_example="The instruction uses a common domain term or defines a local term in criteria.",
        ),
    ),
    "question_reference_is_ambiguous": _check(
        "identify_question_references",
        (
            "Can a reference in `candidate_question` plausibly name more than one supplied entity or "
            "value and change the answer?"
        ),
        inspect=["request_state", "candidate_question.instructions", "candidate_question.criteria"],
        focus=(
            "Inspect question wording, including pronouns and unnamed baselines; an absent fact is a "
            "separate evidence check."
        ),
        guidance="Replace the ambiguous reference with the exact state path, entity, or baseline.",
        criteria=_criteria(
            "A question reference can select multiple supplied targets whose answers can differ.",
            "Each decision-relevant reference selects one supplied target.",
            defect_not_for="A relation that intentionally names and compares several entities.",
            acceptable_not_for="A pronoun or generic noun that could select different supplied entities.",
            defect_example="It could refer to either of two named implementations.",
            acceptable_example="`candidate.text` selects the implementation being judged.",
        ),
    ),
    "state_reference_target_is_ambiguous": _check(
        "identify_state_reference_target",
        (
            "Does `candidate_question` require one target while multiple supplied state targets fit "
            "and no identifier selects one?"
        ),
        inspect=["request_state", "candidate_question"],
        focus="Report multiple supplied targets only; absent evidence is a separate check.",
        guidance="Point to the exact state path, entity id, baseline, or comparison target.",
        criteria=_criteria(
            "Multiple supplied targets fit a required reference and none is selected.",
            "The required target is unique or selected by an exact identifier or path.",
            defect_not_for="A question intentionally judging one relationship among named entities.",
            acceptable_not_for="A generic target word that fits multiple supplied records.",
            defect_example="The state has two baselines and the question asks about the baseline.",
            acceptable_example="The question names `baselines.current`.",
        ),
    ),
    "requires_missing_case_fact": _check(
        "supply_case_evidence",
        "Does the substantive judgment require a case-specific fact absent from `request_state`?",
        inspect=["request_state", "candidate_question"],
        focus=(
            "Ordinary semantic knowledge is available. Report the gap even if a missing-evidence "
            "outcome represents it; "
            "that outcome prevents guessing but does not supply the substantive fact."
        ),
        guidance="Supply the exact case fact or retain the result as an explicit evidence gap.",
        criteria=_criteria(
            (
                "A current policy, implementation fact, source fact, or observation unique to this case "
                "is needed but absent."
            ),
            "The state and ordinary semantic knowledge contain the facts needed for the substantive answer.",
            defect_not_for="Ordinary language or background semantic interpretation.",
            acceptable_not_for="A conclusion that depends on an omitted callee, policy, or observation.",
            defect_example="A question about callee behavior receives only the call site.",
            acceptable_example="The relevant call site and callee implementation are both supplied.",
        ),
    ),
    "has_conflicting_criteria": _check(
        "consistent_criteria",
        "Do `candidate_question.criteria` assign different typed answers to the same reasonable interpretation?",
        inspect="candidate_question.criteria",
        focus="Adjacent Score levels may have uncertainty; require affirmative assignment to conflicting outcomes.",
        guidance="Repair the specific overlapping positive rules without demanding artificial boundary precision.",
        criteria=_criteria(
            "The same interpretation is affirmatively assigned to different typed outcomes.",
            "The criteria are mutually consistent, including ordinary uncertainty at boundaries.",
            defect_not_for="Probability spread between neighboring Score levels at a natural boundary.",
            acceptable_not_for="Two criteria that both claim the same concrete case.",
            defect_example="One example satisfies both the stated true and false definitions.",
            acceptable_example="True and false describe opposite outcomes of the same proposition.",
        ),
    ),
    "instructions_conflict_with_criteria": _check(
        "instructions_align_with_criteria",
        (
            "Do `candidate_question.instructions` and `candidate_question.criteria` assign opposite "
            "or different meanings to the same typed answer?"
        ),
        inspect=["candidate_question.instructions", "candidate_question.criteria"],
        focus=(
            "Compare subject, property, and answer direction; do not require optional criteria when "
            "instructions are sufficient."
        ),
        guidance="Align the instruction and criteria on the same subject, property, and answer direction.",
        criteria=_criteria(
            "The instruction and criteria disagree about what at least one typed outcome means.",
            "The criteria extend the same judgment and answer direction as the instruction.",
            defect_not_for="Criteria that add examples or clarify an already aligned boundary.",
            acceptable_not_for="A true criterion describing no while the instruction asks whether the condition holds.",
            defect_example="The instruction asks whether a fact is present while true means the fact is absent.",
            acceptable_example="The instruction asks whether a fact is present and true defines presence.",
        ),
    ),
    "requires_generated_content": _check(
        "model_judges_code_acts",
        "Does `candidate_question` require open-ended generated content in addition to its declared typed answer?",
        inspect=["candidate_question.type", "candidate_question.instructions"],
        focus="Judge required output, not whether supplied state contains prose.",
        guidance="Move generation to the host LLM or code and retain a bounded typed judgment.",
        criteria=_criteria(
            "The requested result includes newly generated open-ended content.",
            "The requested result is only the declared Noul, Choice, or Score answer.",
            defect_not_for="Selecting one supplied text option.",
            acceptable_not_for="Writing a new explanation, rewrite, or code fragment.",
            defect_example="The question asks for a classification and a written explanation.",
            acceptable_example="The question selects one declared route.",
        ),
    ),
    "requires_external_action": _check(
        "model_judges_code_acts",
        "Does `candidate_question` require System One itself to execute a tool, side effect, or external action?",
        inspect=["candidate_question.type", "candidate_question.instructions"],
        focus="Retrieving an absent fact is covered by the evidence-gap check; this check concerns execution.",
        guidance="Make code or the host agent own the action after reading the typed answer.",
        criteria=_criteria(
            "The model must execute a tool, mutation, or external action for the requested result.",
            "The model only judges supplied state and code owns any resulting action.",
            defect_not_for="Judging whether a supplied action is appropriate.",
            acceptable_not_for="Instructions that tell System One to send, fetch, edit, or execute something.",
            defect_example="The question asks the model to fetch a current policy and approve a request.",
            acceptable_example="The question asks whether a supplied policy supports a supplied request.",
        ),
    ),
    "noul_lacks_single_proposition": _check(
        "noul_is_one_proposition",
        "Does this Noul ask for something other than the truth probability of one stated proposition?",
        inspect=["candidate_question.instructions", "candidate_question.criteria"],
        focus="Atomicity is reviewed separately; here inspect the answer shape and meaning.",
        guidance="State one proposition for the Noul or use the primitive matching the answer shape.",
        criteria=_criteria(
            "The expected answer is a selection, a degree, generated content, or no identifiable proposition.",
            "The answer is the probability that one identifiable proposition is true.",
            defect_not_for="One relational proposition involving several named entities.",
            acceptable_not_for="Using a Noul probability as a degree scale or multi-option selection.",
            defect_example="A Noul asks how severe an issue is.",
            acceptable_example="A Noul asks whether the issue blocks login.",
        ),
    ),
    "choice_has_nonexclusive_properties": _check(
        "choice_is_one_selection",
        "Can multiple Choice options validly hold at once as independently useful properties?",
        inspect=["request_state", "candidate_question.criteria"],
        focus="A Choice may compare overlapping evidence while still making one explicit selection.",
        guidance="Replace independently applicable Choice labels with one Noul per property.",
        criteria=_criteria(
            "Several options can simultaneously hold and their separate truth values matter to the consumer.",
            "The options compete for one selection on the stated decision dimension.",
            defect_not_for="One primary-route selection when several topics are mentioned.",
            acceptable_not_for="Independent labels where every applicable label must be retained.",
            defect_example="Choice options are contains credentials and creates urgency.",
            acceptable_example="Choice options select the primary support department.",
        ),
    ),
    "choice_has_no_valid_option_for_case": _check(
        "cover_choice_outcomes_for_case",
        "Can the supplied `request_state` validly match none of this Choice's options?",
        inspect=["request_state", "candidate_question.criteria"],
        focus="This is a case-specific coverage observation, not proof that every Choice needs a no-match option.",
        guidance="For this intended input, add a concrete no-match option or repair candidate coverage.",
        criteria=_criteria(
            "No declared option validly covers this supplied case.",
            "At least one declared option validly covers this supplied case.",
            defect_not_for="An exhaustive option set whose names or descriptions cover the case.",
            acceptable_not_for="Forcing an uncovered case into the closest option.",
            defect_example="A billing-or-shipping Choice receives an unrelated account-access case.",
            acceptable_example="An exhaustive yes-or-no Choice covers the supplied proposition.",
        ),
    ),
    "score_lacks_ordered_degree": _check(
        "score_is_ordered",
        "Do the Score criteria fail to form ordered levels of one described dimension?",
        inspect=["candidate_question.instructions", "candidate_question.criteria"],
        focus="The levels may use different evidence while still increasing on one dimension.",
        guidance="Use one ordered dimension or choose a different primitive.",
        criteria=_criteria(
            "Levels mix categories or independent dimensions, or their order has no consistent meaning.",
            "Levels increase along one stated dimension.",
            defect_not_for="Different situations that are ordered on the same dimension.",
            acceptable_not_for="A list of unordered categories presented as levels.",
            defect_example="Levels mix urgency, customer value, and technical severity.",
            acceptable_example="Levels increase from no functional impact to blocking with no workaround.",
        ),
    ),
    "score_levels_are_abstract_degrees": _check(
        "score_levels_are_concrete",
        "Do the Score criteria use degree labels without standalone situations that distinguish the levels?",
        inspect="candidate_question.criteria",
        focus="Short concrete descriptions are sufficient; examples and objects are optional.",
        guidance="Describe a concrete situation for each level so it can be judged independently.",
        criteria=_criteria(
            "One or more levels are only relative or abstract degrees with no independently understandable situation.",
            "Each level describes a situation the supplied state can be matched against.",
            defect_not_for="A concise level description that names observable conditions.",
            acceptable_not_for="Labels such as low, moderate, or worse than previous with no defined situation.",
            defect_example="Criteria are low, medium, and high severity.",
            acceptable_example="The middle level is broken feature with a workaround.",
        ),
    ),
}


STATE_COMPONENT_CHECKS: dict[str, dict[str, Any]] = {
    "state_component_wording_is_hard_to_understand": _check(
        "make_state_comprehensible",
        (
            "Is the language of `selected_component.value` difficult to understand for the candidate "
            "judgment even if one meaning can be recovered?"
        ),
        inspect=["selected_component", "candidate_question"],
        focus="Inspect this selected path only. Technical content is not defective merely because it is specialized.",
        guidance="Rewrite or structure the named state component without changing its factual meaning.",
        criteria=_criteria(
            "The needed component has one recoverable meaning but requires avoidable reconstruction or rereading.",
            "The needed component communicates its meaning directly enough for the judgment.",
            defect_not_for="Specialized source text or data that is directly stated.",
            acceptable_not_for=(
                "Nested negation, unclear attachment, or unexplained indirection inside the state value."
            ),
            defect_example="A nested negative exception obscures which case the value describes.",
            acceptable_example="A named field states the observed message directly.",
        ),
    ),
    "state_component_role_is_unclear": _check(
        "name_state_component_role",
        "Is the semantic role of `selected_component` in the candidate judgment unresolved?",
        inspect=["selected_component", "candidate_question"],
        focus="Entity, unit, and timeframe are reviewed separately.",
        guidance="Rename or structure the named state component so its role in the judgment is explicit.",
        criteria=_criteria(
            "The value's role in the candidate judgment cannot be identified.",
            "The value's role in the candidate judgment is identifiable.",
            defect_not_for="An identifiable role expressed in unstructured prose.",
            acceptable_not_for="A generic value whose relationship to the question must be guessed.",
            defect_example="A value named data could be the observation or the policy.",
            acceptable_example="A value named observed_diagnostic contains the emitted message.",
        ),
    ),
    "state_component_entity_is_unclear": _check(
        "identify_state_component_entity",
        (
            "Does the candidate judgment need to know which entity `selected_component` describes, "
            "while that entity is unresolved?"
        ),
        inspect=["selected_component", "candidate_question", "request_state"],
        focus="If the judgment does not depend on an entity distinction, this defect is false.",
        guidance="Attach the named state component to the exact entity or subject it describes.",
        criteria=_criteria(
            "The judgment depends on the entity and multiple entities fit the component.",
            "The entity is identifiable or irrelevant to the judgment.",
            defect_not_for="A value whose entity is unique in context or does not affect the answer.",
            acceptable_not_for="A needed value that could belong to different supplied entities.",
            defect_example="status could describe either the source or destination record.",
            acceptable_example="source.status names the entity directly.",
        ),
    ),
    "state_component_unit_is_unclear": _check(
        "identify_state_component_unit",
        "Does the candidate judgment depend on the unit of `selected_component`, while that unit is unresolved?",
        inspect=["selected_component", "candidate_question"],
        focus="If no unit distinction affects the answer, this defect is false.",
        guidance="Name the unit for the selected state component when it changes the answer.",
        criteria=_criteria(
            "Different plausible units change the answer and the component does not select one.",
            "The unit is explicit, uniquely implied, or irrelevant to the answer.",
            defect_not_for="A non-quantitative value or an ordinary unit uniquely fixed by context.",
            acceptable_not_for="A threshold comparison whose value could be seconds or milliseconds.",
            defect_example="latency is 500 without identifying milliseconds or seconds.",
            acceptable_example="latency_ms is 500.",
        ),
    ),
    "state_component_timeframe_is_unclear": _check(
        "identify_state_component_timeframe",
        (
            "Does the candidate judgment depend on the timeframe of `selected_component`, while that "
            "timeframe is unresolved?"
        ),
        inspect=["selected_component", "candidate_question"],
        focus="If no timeframe distinction affects the answer, this defect is false.",
        guidance="Name the relevant observation time or interval for the selected state component.",
        criteria=_criteria(
            "Different plausible timeframes change the answer and the component does not select one.",
            "The timeframe is explicit, uniquely implied, or irrelevant to the answer.",
            defect_not_for="A timeless fact or a timeframe uniquely fixed by context.",
            acceptable_not_for="A current-versus-historical value that changes the judgment.",
            defect_example="error_rate is supplied without saying which deployment window it covers.",
            acceptable_example="error_rate_after_deploy identifies the observation window.",
        ),
    ),
}


WORKFLOW_CHECKS: dict[str, dict[str, Any]] = {
    "consumer_site_overclaims_evidence": _check(
        "consumer_claims_follow_evidence",
        (
            "Can `selected_site` assert or trigger a conclusion that its "
            "`selected_site.relevant_questions`, "
            "deterministic facts, and explicit policy do not establish together?"
        ),
        inspect=["selected_site", "purpose", "request_state"],
        focus=(
            "Judge this exact read or composition site and its enclosing statement, not the whole "
            "consumer in one answer."
        ),
        guidance=(
            "Restrict the named consumption site to conclusions established by its exact answers and "
            "deterministic facts."
        ),
        criteria=_criteria(
            "A reachable conclusion at this site exceeds the supplied answers and deterministic facts.",
            "The site's conclusion follows from the exact relevant answers, facts, and policy.",
            defect_not_for="An explicit policy that composes several relevant answers.",
            acceptable_not_for="A conclusion that adds an unmeasured property.",
            defect_example="A code-quality conclusion is made from one unrelated classification.",
            acceptable_example="A route follows the exact supported Choice and its explicit threshold policy.",
        ),
    ),
    "concentration_used_as_empirical_accuracy": _check(
        "confidence_is_not_accuracy",
        "Does `selected_site` interpret provider confidence or a Noul probability as measured empirical correctness?",
        inspect=["selected_site", "purpose"],
        focus="A separately supplied calibration measurement is evidence; a response number alone is not.",
        guidance="Keep observed accuracy from labelled cases separate from response probability or confidence.",
        criteria=_criteria(
            "The site equates a response probability or distribution concentration with measured correctness.",
            "The site uses response uncertainty without calling it observed accuracy.",
            defect_not_for="Routing on an explicitly chosen confidence threshold.",
            acceptable_not_for="Naming a provider confidence value accuracy or measured reliability.",
            defect_example="The code reports confidence as the detector's accuracy.",
            acceptable_example="The code routes a low-confidence Choice to review.",
        ),
    ),
    "option_probability_mislabeled_as_confidence": _check(
        "option_probability_is_not_provider_confidence",
        "Does `selected_site` treat one Choice or Score option probability as the provider's confidence field?",
        inspect=["selected_site", "selected_site.relevant_questions"],
        focus="A caller may deliberately use an option probability; the defect is claiming it is provider confidence.",
        guidance="Name the value as an option probability or consume the returned confidence field.",
        criteria=_criteria(
            "One option's probability is read or named as the provider confidence statistic.",
            "Option probabilities and provider confidence retain their distinct meanings.",
            defect_not_for="A documented custom policy using a named option probability.",
            acceptable_not_for="Calling max(probabilities) the returned confidence field.",
            defect_example="max answer probability is stored as provider_confidence.",
            acceptable_example="The code reads answer.confidence or names the value winning_probability.",
        ),
    ),
    "noul_probability_used_as_degree": _check(
        "noul_probability_is_not_degree",
        "Does `selected_site` use a Noul probability as the intensity or degree of the proposition's subject?",
        inspect=["selected_site", "selected_site.relevant_questions"],
        focus=(
            "Ranking by truth probability can be valid; the defect is interpreting it as degree on "
            "the subject dimension."
        ),
        guidance="Use Noul as probability of truth or replace it with a Score whose levels define the degree.",
        criteria=_criteria(
            "The site interprets a Noul value as how much of a property the subject has.",
            "The site treats the Noul value as probability that its proposition is true.",
            defect_not_for="Thresholding or ranking by probability that a fixed proposition holds.",
            acceptable_not_for="Calling a 0.5 Noul medium severity or medium skill.",
            defect_example="A Python-experience Noul is displayed as the amount of experience.",
            acceptable_example="A refund-request Noul is thresholded as probability the request exists.",
        ),
    ),
    "missing_evidence_mapped_to_negative": _check(
        "preserve_missing_evidence",
        (
            "Can an explicit missing or unavailable evidence path at `selected_site` become a "
            "substantive negative or clean result?"
        ),
        inspect=["selected_site", "selected_site.relevant_questions"],
        focus="Require an actual evidence-gap path; absence of such a path makes this defect false.",
        guidance="Preserve the evidence gap as unavailable or not reviewed at this site.",
        criteria=_criteria(
            "A reachable missing-evidence path is converted into a substantive negative or clean conclusion.",
            "Missing evidence remains unavailable, incomplete, or separately routed.",
            defect_not_for="A substantive false answer produced from sufficient evidence.",
            acceptable_not_for="Defaulting an absent answer or source to clean.",
            defect_example="No source is available and the consumer emits no defect found.",
            acceptable_example="No source is available and the consumer emits not reviewed.",
        ),
    ),
    "answer_weights_lack_explicit_policy": _check(
        "weighting_is_explicit_policy",
        (
            "Does the numeric composition at `selected_site` affect the outcome without an explicit "
            "decision role for its weights?"
        ),
        inspect=["selected_site", "purpose"],
        focus="If this site does not combine independent answers numerically, this defect is false.",
        guidance="State the decision role and reason for each weight at the named composition site.",
        criteria=_criteria(
            "Weights affect a decision but their policy meaning is unstated.",
            "There is no weighted composition, or the role of each weight is explicit.",
            defect_not_for="A visible experimental weighting policy tied to the stated purpose.",
            acceptable_not_for="Unexplained constants that silently determine the result.",
            defect_example="Several answers are averaged with unexplained constants before routing.",
            acceptable_example="Documented product priorities define and expose each weight.",
        ),
    ),
    "required_condition_hidden_by_compensation": _check(
        "prerequisites_do_not_compensate",
        "Can a required condition named by `purpose` be averaged away by unrelated strengths at `selected_site`?",
        inspect=["selected_site", "purpose", "selected_site.relevant_questions"],
        focus="Compensating preferences are valid; require an actual prerequisite that the policy says must hold.",
        guidance="Keep the named prerequisite as an individual route condition outside the compensating score.",
        criteria=_criteria(
            "A stated prerequisite can fail while the composite still passes because other terms compensate.",
            "The composition contains only compensating preferences or preserves each required condition separately.",
            defect_not_for="A weighted ranking where every dimension is intentionally compensating.",
            acceptable_not_for="A must-have evidence condition blended into an average.",
            defect_example="Missing required evidence is offset by high clarity in one aggregate score.",
            acceptable_example="Missing required evidence routes separately before preference scoring.",
        ),
    ),
    "score_combined_without_normalization": _check(
        "normalize_scores_before_combining",
        (
            "Does `selected_site` combine a raw Score position with another dimension without "
            "accounting for their level ranges?"
        ),
        inspect=["selected_site", "selected_site.relevant_questions"],
        focus="A raw Score can be used alone; this defect requires cross-dimension numeric composition.",
        guidance="Normalize each Score by its top level before combining differently ranged dimensions.",
        criteria=_criteria(
            "Scores with different possible ranges are combined as if their raw positions were comparable.",
            "The Score is not combined across dimensions or the ranges are normalized or explicitly accounted for.",
            defect_not_for="Thresholding one raw Score against a threshold defined on that same scale.",
            acceptable_not_for="Adding a 0-to-2 Score to a 0-to-5 Score without adjustment.",
            defect_example="Raw severity and quality Scores with different level counts are averaged.",
            acceptable_example="Each Score is divided by its top level before weighting.",
        ),
    ),
    "noul_product_claimed_joint_probability": _check(
        "do_not_invent_joint_probability",
        (
            "Does `selected_site` present a product of Noul probabilities as a justified joint "
            "probability without an independence model?"
        ),
        inspect=["selected_site", "selected_site.relevant_questions", "purpose"],
        focus=(
            "Multiplication itself is not forbidden; require the product to be claimed or consumed as"
            " joint probability."
        ),
        guidance="Name the product as an application score or justify and validate the probabilistic model.",
        criteria=_criteria(
            "The product is treated as joint probability without evidence that the judgments are independent.",
            "The product is not used, is named as a policy score, or has a justified probabilistic model.",
            defect_not_for="An explicitly named heuristic score using multiplication.",
            acceptable_not_for="Calling correlated Noul multiplication calibrated joint confidence.",
            defect_example="Two related Noul values are multiplied and reported as probability both facts hold.",
            acceptable_example="The product is documented as an uncalibrated ranking score.",
        ),
    ),
}


def _nouls(checks: Mapping[str, Mapping[str, Any]]) -> dict[str, Noul]:
    return {name: Noul(instructions=spec["instructions"], criteria=spec["criteria"]) for name, spec in checks.items()}


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _strings(nested)


def _backticked_paths(question: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for text in _strings(question.get("instructions")):
        pieces = text.split("`")
        for index in range(1, len(pieces), 2):
            path = pieces[index].strip()
            if path and path not in paths:
                paths.append(path)
    return paths


def _replace_instruction_path(value: Any, source: str, target: str) -> Any:
    if isinstance(value, str):
        return value.replace(source, target)
    if isinstance(value, Mapping):
        return {key: _replace_instruction_path(nested, source, target) for key, nested in value.items()}
    if isinstance(value, list):
        return [_replace_instruction_path(nested, source, target) for nested in value]
    return value


def _resolve_path(state: Any, path: str) -> Any:
    if path.startswith("request_state."):
        path = path[len("request_state.") :]
    return resolve_path(state, path)


def _state_components(state: Any, question: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    components: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for path in _backticked_paths(question):
        try:
            value = _resolve_path(state, path)
        except (IndexError, KeyError):
            unresolved.append(path)
            continue
        components.append({"path": path, "value": value})
    if not components:
        components.append({"path": "$", "value": state})
    return components, unresolved


def _unresolved_question_paths(state: Mapping[str, Any], questions: Mapping[str, Mapping[str, Any]]) -> list[str]:
    unresolved: list[str] = []
    for question in questions.values():
        for path in _backticked_paths(question):
            try:
                _resolve_path(state, path)
            except (IndexError, KeyError):
                if path not in unresolved:
                    unresolved.append(path)
    return unresolved


def _state_component_checks(components: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for index, _component in enumerate(components):
        for check_id, template in STATE_COMPONENT_CHECKS.items():
            check = deepcopy(template)
            check["instructions"] = _replace_instruction_path(
                check["instructions"], "selected_component", f"state_components[{index}]"
            )
            checks[f"{check_id}__{index}"] = check
    return checks


def _workflow_checks(sites: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for index, site in enumerate(sites):
        check_ids = {
            "consumer_site_overclaims_evidence",
            "missing_evidence_mapped_to_negative",
        }
        fields = set(site["answer_fields"])
        if "confidence" in fields:
            check_ids.add("concentration_used_as_empirical_accuracy")
        if "probabilities" in fields:
            check_ids.add("option_probability_mislabeled_as_confidence")
        if "noul" in fields:
            check_ids.add("noul_probability_used_as_degree")
        if site["kind"] == "composition":
            check_ids.update({"answer_weights_lack_explicit_policy", "required_condition_hidden_by_compensation"})
            if "score" in fields:
                check_ids.add("score_combined_without_normalization")
            if site.get("operation") == "Mult" and fields == {"noul"}:
                check_ids.add("noul_product_claimed_joint_probability")
        for check_id in sorted(check_ids):
            check = deepcopy(WORKFLOW_CHECKS[check_id])
            check["instructions"] = _replace_instruction_path(
                check["instructions"], "selected_site", f"consumer_sites[{index}]"
            )
            checks[f"{check_id}__{index}"] = check
    return checks


def _required_nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{path} must be a nonempty string")
    return value


def _atomicity_pairs(document: Mapping[str, Any], question_id: str) -> list[dict[str, Any]]:
    question_context = question_review_context(document, question_id)
    raw_pairs = question_context.get("atomicity_pairs")
    if raw_pairs is None:
        return []
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise InputError(f"review_context.questions.{question_id}.atomicity_pairs must be a nonempty array")

    pairs: list[dict[str, Any]] = []
    pair_ids: set[str] = set()
    for index, raw_pair in enumerate(raw_pairs):
        path = f"review_context.questions.{question_id}.atomicity_pairs[{index}]"
        if not isinstance(raw_pair, Mapping):
            raise InputError(f"{path} must be an object")
        pair_id = _required_nonempty_string(raw_pair.get("pair_id"), f"{path}.pair_id")
        if pair_id in pair_ids:
            raise InputError(f"{path}.pair_id duplicates {pair_id!r}")
        pair_ids.add(pair_id)

        propositions: dict[str, dict[str, str]] = {}
        for side in ("a", "b"):
            raw_proposition = raw_pair.get(f"proposition_{side}")
            proposition_path = f"{path}.proposition_{side}"
            if not isinstance(raw_proposition, Mapping):
                raise InputError(f"{proposition_path} must be an object")
            propositions[side] = {
                "id": _required_nonempty_string(raw_proposition.get("id"), f"{proposition_path}.id"),
                "text": _required_nonempty_string(raw_proposition.get("text"), f"{proposition_path}.text"),
                "source_anchor": _required_nonempty_string(
                    raw_proposition.get("source_anchor"), f"{proposition_path}.source_anchor"
                ),
            }
        if propositions["a"]["id"] == propositions["b"]["id"] or propositions["a"]["text"] == propositions["b"]["text"]:
            raise InputError(f"{path} must name two distinct propositions")

        raw_outputs = raw_pair.get("consumer_outputs")
        if not isinstance(raw_outputs, Mapping):
            raise InputError(f"{path}.consumer_outputs must be an object")
        consumer_outputs = {
            side: _required_nonempty_string(raw_outputs.get(side), f"{path}.consumer_outputs.{side}")
            for side in ("a", "b")
        }
        if consumer_outputs["a"] == consumer_outputs["b"]:
            raise InputError(f"{path}.consumer_outputs must name two distinct outputs or actions")

        raw_evidence = raw_pair.get("independence_evidence")
        if not isinstance(raw_evidence, Mapping):
            raise InputError(f"{path}.independence_evidence must be an object")
        a_truth = raw_evidence.get("a_truth")
        b_truth = raw_evidence.get("b_truth")
        if not isinstance(a_truth, bool) or not isinstance(b_truth, bool):
            raise InputError(f"{path}.independence_evidence a_truth and b_truth must be booleans")
        if a_truth == b_truth:
            raise InputError(f"{path}.independence_evidence must be a mixed-truth case")
        independence_evidence = {
            "case_ref": _required_nonempty_string(
                raw_evidence.get("case_ref"), f"{path}.independence_evidence.case_ref"
            ),
            "source_anchor": _required_nonempty_string(
                raw_evidence.get("source_anchor"), f"{path}.independence_evidence.source_anchor"
            ),
            "a_truth": a_truth,
            "b_truth": b_truth,
        }
        pairs.append(
            {
                "pair_id": pair_id,
                "proposition_a": propositions["a"],
                "proposition_b": propositions["b"],
                "consumer_outputs": consumer_outputs,
                "independence_evidence": independence_evidence,
            }
        )
    return pairs


def _atomicity_pair_checks(pairs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for index, _pair in enumerate(pairs):
        for check_id, template in ATOMICITY_PAIR_CHECKS.items():
            check = deepcopy(template)
            side = "a" if check_id.endswith("_a") else "b"
            proposition_path = f"atomicity_pairs[{index}].proposition_{side}.text"
            check["instructions"]["question"] = (
                f"Does `candidate_question` ask the model to check whether `{proposition_path}` is true?"
            )
            check["instructions"]["inspect"] = ["candidate_question", proposition_path]
            checks[f"{check_id}__{index}"] = check
    return checks


def _model_atomicity_pairs(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "proposition_a": {key: pair["proposition_a"][key] for key in ("id", "text")},
            "proposition_b": {key: pair["proposition_b"][key] for key in ("id", "text")},
        }
        for pair in pairs
    ]


def _semantic_contrast_checks(contrasts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for index, _contrast in enumerate(contrasts):
        contrast_path = f"semantic_term_contrasts[{index}]"
        for check_id, template in SEMANTIC_CONTRAST_CHECKS.items():
            check = deepcopy(template)
            side = "a" if check_id.endswith("_a") else "b"
            check["instructions"]["question"] = (
                f"Does the actual wording at the path named by `{contrast_path}.selected_path` state a "
                f"distinguishing condition that rules out `{contrast_path}.definition_{side}.text` for the "
                f"chosen occurrence of `{contrast_path}.quoted_term`?"
            )
            check["instructions"]["inspect"] = [
                "request_state",
                "candidate_question",
                contrast_path,
            ]
            checks[f"{check_id}__{index}"] = check
    return checks


def _applicable_question_checks(
    question: Mapping[str, Any],
    intended_use: Any,
    atomicity_pairs: list[dict[str, Any]],
    semantic_contrasts: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str]]:
    checks = deepcopy(PER_QUESTION_CHECKS)
    skipped: dict[str, str] = {}
    if semantic_contrasts:
        checks.update(_semantic_contrast_checks(semantic_contrasts))
    else:
        skipped["decision_term_semantic_contrast"] = (
            "no host-supplied quoted term with two grounded definitions and a differing-answer case"
        )
    if atomicity_pairs:
        checks.update(_atomicity_pair_checks(atomicity_pairs))
    else:
        skipped["atomicity_pair_review"] = (
            "no source-backed atomicity pair with independently needed consumer outputs and mixed-truth evidence"
        )
    if "criteria" not in question:
        for check_id in ("has_conflicting_criteria", "instructions_conflict_with_criteria"):
            checks.pop(check_id)
            skipped[check_id] = "candidate question has no criteria"
    if question["type"] != "choice":
        for check_id in ("choice_has_nonexclusive_properties", "choice_has_no_valid_option_for_case"):
            checks.pop(check_id)
            skipped[check_id] = "candidate question is not a Choice"
    elif intended_use is not None:
        checks["choice_has_nonexclusive_properties"]["instructions"]["candidate_intended_use"] = intended_use
    if question["type"] != "noul":
        checks.pop("noul_lacks_single_proposition")
        skipped["noul_lacks_single_proposition"] = "candidate question is not a Noul"
    if question["type"] != "score":
        for check_id in ("score_lacks_ordered_degree", "score_levels_are_abstract_degrees"):
            checks.pop(check_id)
            skipped[check_id] = "candidate question is not a Score"
    return checks, skipped


def review_requests(document: Any, model: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(document, Mapping):
        raise InputError("review input must be a JSON object")
    request = document.get("request", document)
    if not isinstance(request, Mapping) or "state" not in request:
        raise InputError("review input requires request.state")
    raw_questions = request.get("questions")
    if not isinstance(raw_questions, Mapping) or not raw_questions:
        raise InputError("review input requires nonempty request.questions")
    intended_uses = document.get("intended_uses", {})
    if not isinstance(intended_uses, Mapping):
        raise InputError("intended_uses must be an object keyed by question id")

    normalized = {
        str(question_id): validate_question(raw_question).model_dump(mode="json", exclude_none=True)
        for question_id, raw_question in raw_questions.items()
    }
    prepared: list[dict[str, Any]] = []
    for question_id, question in normalized.items():
        atomicity_pairs = _atomicity_pairs(document, question_id)
        semantic_contrasts = semantic_term_contrasts(document, question_id, request["state"], question)
        components, unresolved_paths = _state_components(request["state"], question)
        state: dict[str, Any] = {
            "request_state": request["state"],
            "candidate_question": question,
            "state_components": components,
        }
        if atomicity_pairs:
            state["atomicity_pairs"] = _model_atomicity_pairs(atomicity_pairs)
        if semantic_contrasts:
            state["semantic_term_contrasts"] = model_semantic_term_contrasts(semantic_contrasts)
        checks, skipped_checks = _applicable_question_checks(
            question,
            intended_uses.get(question_id),
            atomicity_pairs,
            semantic_contrasts,
        )
        checks.update(_state_component_checks(components))
        principle_ids = {principle_id for spec in checks.values() for principle_id in spec["principle_ids"]}
        state["principles"] = selected_principles(principle_ids)
        submitted = {
            "state": state,
            "questions": {
                name: value.model_dump(mode="json", exclude_none=True) for name, value in _nouls(checks).items()
            },
            "model": model or DEFAULT_MODEL,
        }
        generated_unresolved_paths = _unresolved_question_paths(state, submitted["questions"])
        prepared.append(
            {
                "scope": "question",
                "candidate_question_id": question_id,
                "skipped_checks": skipped_checks,
                "atomicity_pair_coverage": {
                    "status": "reviewed" if atomicity_pairs else "not_reviewed",
                    "pairs": atomicity_pairs,
                },
                "semantic_term_contrast_coverage": {
                    "status": "reviewed" if semantic_contrasts else "not_reviewed",
                    "contrasts": semantic_contrasts,
                    "policy_role": "advisory_unvalidated",
                },
                "state_path_coverage": {
                    "selected_paths": [component["path"] for component in components],
                    "unresolved_backticked_paths": list(
                        dict.fromkeys([*unresolved_paths, *generated_unresolved_paths])
                    ),
                    "review_question_unresolved_paths": generated_unresolved_paths,
                },
                "principle_provenance": principle_provenance(principle_ids),
                "review_fingerprint": fingerprint(submitted),
                "submitted": submitted,
            }
        )

    for question_id, question in normalized.items():
        prepared.extend(condition_review_requests(document, question_id, question, request["state"], model))

    workflow = document.get("workflow")
    if not (
        isinstance(workflow, Mapping)
        and isinstance(workflow.get("consumer_code"), str)
        and workflow["consumer_code"].strip()
    ):
        prepared.append(_not_reviewed("workflow.consumer_code was not supplied"))
        return prepared
    language = workflow.get("language", "python")
    if language != "python":
        prepared.append(_not_reviewed(f"workflow language {language!r} is not supported; only Python is reviewed"))
        return prepared
    analysis = inspect_python_consumer(workflow["consumer_code"], normalized)
    if analysis["status"] != "reviewed":
        prepared.append(_not_reviewed(str(analysis["reason"])))
        return prepared

    sites = analysis["sites"]
    checks = _workflow_checks(sites)
    principle_ids = {principle_id for spec in checks.values() for principle_id in spec["principle_ids"]}
    coverage = {key: value for key, value in analysis.items() if key != "sites"}
    state = {
        "purpose": workflow.get("purpose"),
        "consumer_sites": sites,
        "workflow_coverage": coverage,
        "request_state": request["state"],
        "principles": selected_principles(principle_ids),
    }
    submitted = {
        "state": state,
        "questions": {name: value.model_dump(mode="json", exclude_none=True) for name, value in _nouls(checks).items()},
        "model": model or DEFAULT_MODEL,
    }
    generated_unresolved_paths = _unresolved_question_paths(state, submitted["questions"])
    prepared.append(
        {
            "scope": "workflow",
            "workflow_coverage": coverage,
            "state_path_coverage": {
                "selected_paths": [],
                "unresolved_backticked_paths": generated_unresolved_paths,
                "review_question_unresolved_paths": generated_unresolved_paths,
            },
            "principle_provenance": principle_provenance(principle_ids),
            "review_fingerprint": fingerprint(submitted),
            "submitted": submitted,
        }
    )
    return prepared


def _not_reviewed(reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "review",
        "scope": "workflow",
        "status": "not_reviewed",
        "reason": reason,
    }


def base_check_id(check_id: str) -> str:
    return check_id.split("__", 1)[0]


def guidance_for(scope: str) -> dict[str, str]:
    checks: dict[str, dict[str, Any]] = {}
    if scope == "criteria_condition":
        checks[CONDITION_CHECK_ID] = CONDITION_CHECK_SPEC
    elif scope == "question":
        checks.update(ATOMICITY_PAIR_CHECKS)
        checks.update(SEMANTIC_CONTRAST_CHECKS)
        checks.update(PER_QUESTION_CHECKS)
        checks.update(STATE_COMPONENT_CHECKS)
    else:
        checks.update(WORKFLOW_CHECKS)
    return {name: str(spec["guidance"]) for name, spec in checks.items()}


def check_metadata(scope: str) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    if scope == "criteria_condition":
        checks[CONDITION_CHECK_ID] = CONDITION_CHECK_SPEC
    elif scope == "question":
        checks.update(ATOMICITY_PAIR_CHECKS)
        checks.update(SEMANTIC_CONTRAST_CHECKS)
        checks.update(PER_QUESTION_CHECKS)
        checks.update(STATE_COMPONENT_CHECKS)
    else:
        checks.update(WORKFLOW_CHECKS)
    return {
        name: {
            "dimension": PRINCIPLES[spec["principle_ids"][0]]["dimension"],
            "principle_ids": list(spec["principle_ids"]),
            "principle_provenance": {principle_id: PRINCIPLES[principle_id] for principle_id in spec["principle_ids"]},
            "inspection_guidance": spec["guidance"],
            **({"advisory_only": True} if spec.get("advisory_only") else {}),
        }
        for name, spec in checks.items()
    }
