# Meta Jev reference

This page contains the candidate format, review checks, receipts, and interpretation details. Start with the [README](../README.md) for the working loop.

## Candidate input

`prepare`, `review`, and `run` accept an official request directly or wrapped with research context:

```json
{
  "case_id": "case-001",
  "group_id": "change-family-a",
  "revision_id": "questions-v1",
  "request": {
    "state": {
      "change": "The submitted change text",
      "requirements": ["A required behavior", "Another required behavior"]
    },
    "questions": {
      "preserves_first_requirement": {
        "type": "noul",
        "instructions": {
          "question": "Does `change` preserve the first item in `requirements`?",
          "inspect": ["change", "requirements[0]"]
        },
        "criteria": {
          "true": {"what": "The behavior remains available with the same required effect."},
          "false": {"what": "The behavior is removed or its required effect changes."}
        }
      }
    },
    "model": "jev-latest"
  },
  "intended_uses": {
    "preserves_first_requirement": "Show whether this individual obligation is preserved."
  },
  "workflow": {
    "purpose": "Route each failed obligation to an engineer.",
    "consumer_code": "if answers[\"preserves_first_requirement\"].noul < preservation_threshold: queue_review()"
  }
}
```

Instructions and criteria may be strings, objects, arrays, or null where the SDK permits them.
Choice descriptions may be null. The CLI rejects duplicate JSON keys so a repeated question id is
not silently discarded.

Optional review-context containers (`review_context`, its `questions`, and each question entry)
may be omitted or null; both mean absent. Other non-object values are input errors before any call.
Semantic term contrasts require two different reference answers valid for the candidate primitive:
booleans for Noul, existing option keys for Choice, and zero-based integer anchor indexes for Score.
These host labels name answers, not probabilities or an expected Score value.

Atomicity review is available only when the host supplies a source-backed proposition pair under
`review_context.questions.<question_id>.atomicity_pairs`. Each pair names propositions A and B,
the separate consumer outputs that need them, their source anchors, and one cited case where A and B
have opposite truth values. Use the same pair for matched broad and narrow candidate questions; the
pair count must not encode the expected label. Jev answers two bounded questions: whether the
candidate asks the model to check A and whether it asks the model to check B. Code combines those raw
answers with the host evidence as `requires_both_independent_propositions`. The consumer-output and
mixed-truth evidence remain outside model state. The model-visible `atomicity_pairs` state contains
only each proposition's id and text, and every generated check names it through a concrete
`atomicity_pairs[index].proposition_a.text` or `.proposition_b.text` path. Without a prepared pair,
atomicity is explicitly `not_reviewed` and the complete design index remains unavailable; the reviewer does not substitute a
generic bundled-question classifier. See [`examples/labelled-question-design/`](../examples/labelled-question-design/) for constructed
controls derived from the official spam and tool-trace decompositions.

## Commands

### Compare a particular condition in instructions and criteria

For a Noul, optional `review_context.questions.<id>.criteria_conditions` entries name a single
requirement whose presence needs inspection. Each entry has `condition_id`, `condition`,
`source_path` (under `candidate_question`) and an exact `source_quote`. Code rejects a missing
path or quote before spending. For example:

```json
{
  "condition_id": "completion",
  "condition": "The run has finished.",
  "source_path": "candidate_question.criteria.true.what",
  "source_quote": "completed an execution"
}
```

The normal `prepare` / `guard` workflow adds two independent requests. One receives only the
candidate instruction; the other receives only its true criterion. Both receive the same named
condition and original request state for reference resolution. Neither receives the sibling
component, the host's expected answer, or the condition's source quote as a hint.

`criteria_condition_assessments` retains both raw values, observation IDs, source texts and the
selected quote. Explicit caller bands yield `same_requirement`, `asymmetric_requirement`, or
`uncertain`; absent answers remain `incomplete`, and absent bands remain `unthresholded`.
An asymmetric result prompts inspection of that named requirement. It is not automatically a
defect: criteria can legitimately define what concise instructions mean. These comparisons are
`advisory_unvalidated`; they do not contribute to the main design score or route. Policy tests
prove isolation and composition, not the model's ability to identify requirements.

Reports distinguish request identity from answer use. `review_fingerprint` remains the cache key;
`review_binding_id` also identifies the retained provider attempt and current question/component.
Observation references, component comparisons, and per-question scores use that binding. Two
identical requests may receive different answers; neither may overwrite the other in a report.
Reusing one retained answer for two components keeps both current source bindings.

### CLI reference

- `propose` emits the host-LLM task and SDK-derived candidate contract. Use `--question`, `--goal`,
  or `--input`; add any number of `--evidence` files. `--format text` is available for human reading.
- `prepare INPUT` validates each proposed question with the official SDK models and prints the exact
  meta-review requests without making a model call.
- `review INPUT --output FILE` makes one request per candidate question, plus any optional isolated
  condition comparisons described above. The independent Nouls cover
  the exact dimensions in the matrix below. State-component questions are generated per explicit
  backticked path, so feedback names the path. Consumer review parses Python, selects each typed
  answer read and composition site, and supplies only the relevant candidate questions and downstream
  branch statements. Missing code, non-Python code, unparseable code, and code with no resolvable
  typed-answer read are recorded as `not_reviewed`. The bounded collector uses the declared
  `answers` or `response.answers` input root and straight-line local aliases. It does not prove
  interprocedural data flow; supply the direct consumption site when a helper boundary hides it.
- `guard INPUT --output FILE` is the coding-agent preflight. `--code-only` performs free structural
  checks and returns exact missing state paths without making a provider call. Normal `guard` also
  stops before inference when those paths cannot be resolved. Criteria remain optional; their absence
  is an informational check, not a malformed-request verdict. It performs the same exact reviews and
  returns contextual model observations plus an action route. With no caller policy it returns
  `review_required` and exit `3`. `--reuse FILE` reuses only successful reviews whose exact state, question, intended use,
  workflow, reviewer rubric, and model alias fingerprint matches. With both `--clear-below` and
  `--flag-at`, it can route to `ready_for_small_trial`, `ready_for_small_trial_questions_only`,
  `revise_questions`, `gather_evidence`, or `review_integration`. Question-only readiness keeps a
  missing consumer explicitly unreviewed and returns the advisory exit code. Mixed concrete response
  model versions cannot route to a ready state. Reused `-latest` receipts retain their recorded model
  and scores but require review because reuse cannot establish the alias's current served version.
  Unresolved backticked state references make question coverage incomplete and suppress the composite;
  they require resolving the reference or clarifying that the backticked text is literal code/prose.
  The thresholds are explicitly experimental routing
  policy, never a quality or accuracy claim.
- Every complete question review also reports a composite design score. Each ordinary dimension uses
  the strongest applicable defect probability. Atomicity instead uses the strongest
  `minimum_support_index` across host-evidenced pairs, with each index equal to the smaller of its
  two proposition-required probabilities. This is code composition, not a joint probability. The default experimental weights are atomicity `0.20`,
  question clarity `0.15`, state clarity `0.15`, primitive suitability `0.15`, evidence sufficiency
  `0.20`, and task suitability `0.15`. The request score is the minimum complete question score.
  Workflow consumption and answer weighting are graded separately with weights `0.60` and `0.40`.
  `--policy FILE` can replace either complete weight dictionary with `question_dimension_weights`
  and `workflow_dimension_weights`; each dictionary must sum to `1`. Scores never override an
  individual flagged condition or the guard route.
- `run INPUT --output FILE` executes the candidate request once. Independent candidate questions
  ride the same System One call. It uses `request.model` when supplied, otherwise `jev-latest`;
  `--model` is an explicit override. Receipts record whether the model came from the CLI, candidate,
  or default.
- `inspect-results INPUT` reads stored run receipts or documented observation rows and reports count,
  minimum, maximum, range, constants, and aligned Pearson correlations. It makes no calls and removes
  no features. Manual rows require a `cohort_id`; run receipts are partitioned by exact question
  definition, concrete model, and revision. Choice and Score retain actual provider confidence;
  Score also reports a labelled distribution standard deviation derived from returned probabilities.
  Every input row is listed as applied or skipped with its exact skip reason.
## Review coverage

The registry in `principles.py` is the single source for rule text, dimension, origin, official URL,
source, section, and a short exact source passage. Each check sends only its concise rule
and relevant passage to Jev. Full provenance remains in prepared output and receipts, including
whether the passage is verbatim official documentation or a local experiment rule. The wording
checks use the Jev 1.13 literal-reading and indirection notes as version-specific evidence, not a
permanent model limitation.

| Requested surface | Independent checks | Exact review input | Static repair | Behavioral proof and limit |
| --- | --- | --- | --- | --- |
| Atomicity | Candidate asks the model to check both host-named propositions that the consumer needs separately | Actual candidate question and the same source-backed A/B pair for matched broad and narrow candidates; mixed-truth witness and expected label stay outside model state | `split_question` only after code combines both pair observations | No generic fallback. Missing pairs are `not_reviewed`; semantic calibration requires a separately labelled blind run. |
| Question comprehension | Hard-to-parse but recoverable wording; unrecoverable meaning | Actual instructions, criteria, and state, without question id or intended-use hints | `rewrite_for_directness`, `define_missing_meaning` | Tests prove the reviewer cannot borrow hidden metadata. No length or vocabulary blacklist is used. |
| Question ambiguity | Reference that can select multiple supplied targets | Actual instructions, criteria, and state | `identify_question_reference` | Reference ambiguity remains independently reviewed. Semantic term contrast is `not_reviewed` until the host supplies an exact selected occurrence, two distinct definitions with honest provenance, and a case whose answer differs under them. When supplied, Meta prepares two independent “rules out A/B” Nouls. Their answers remain `advisory_unvalidated`: routing and design scores ignore them until labelled controls validate the detector. The rejected generic “plausible meanings” classifier is not used. |
| Judged subject | Missing entity or missing property, relation, category, or degree | Actual candidate question | `name_judged_property` | The question id is absent from reviewer state and cannot supply the meaning. |
| State comprehension | Hard-to-understand state wording | One code-selected state component path and value plus the exact candidate question | `rewrite_state_component` | Explicit backticked paths are named in feedback; when none resolve, root state is inspected and coverage says so. |
| State meaning | Component role, entity, unit, and timeframe are four separate checks; target ambiguity is separate | One selected component per check and the complete original state | `clarify_state_role`, `identify_state_entity`, `identify_state_unit`, `identify_state_timeframe`, `identify_state_target` | Tests prove distinct questions per path and aspect. A false answer means the aspect is clear or not applicable. |
| Evidence | Required case-specific fact absent | Actual state and question | `supply_evidence` | Missing evidence stays distinct from a legitimate missing-evidence outcome and from semantic background knowledge. |
| Criteria | Criteria conflict with each other; instructions conflict with criteria | Instructions and criteria | `repair_criteria`, `align_instruction_and_criteria` | Both sides have `what`, `not_for`, and control examples; model efficacy remains uncalibrated. |
| Primitive fit | Noul truth proposition; Choice single selection; no valid Choice option for this case; Score ordered dimension; concrete standalone Score levels | Actual primitive, criteria, state, and intended use only where output meaning needs it | Primitive-specific repair actions | Choice coverage is case-specific and does not require a no-match option for an exhaustive Choice. |
| Task fit | Open-ended generation; external action | Actual typed question | `move_generation_to_host`, `move_action_to_code` | These remain independent so retrieval gaps are not misreported as action defects. |
| Consumer evidence | Conclusion exceeds relevant answers and facts; missing evidence becomes negative | Python AST-selected answer read, enclosing statement, branch, downstream uses, and only its relevant questions | Site-specific integration actions | Code records answer provenance, field, expression, line, operation, branch, and downstream statements as structural facts. Jev does not decide whether an arbitrary program is deterministic. Unsupported or unresolved consumer paths are `not_reviewed`, never green. |
| Probability and confidence | Confidence called empirical accuracy; option probability called provider confidence; Noul used as degree | Exact access site and relevant primitive definitions | `measure_accuracy_separately`, `use_correct_uncertainty_field`, `use_score_for_degree` | Checks preserve raw fields and do not ban legitimate caller-defined probability policies. |
| Weights and composition | Unexplained weights; prerequisite hidden by compensation; differently ranged Scores unnormalised; Noul product claimed as joint probability | Exact arithmetic expression, branch, downstream uses, purpose, and relevant questions | Composition-specific actions | Multiplication and weighting are not blanket defects; each check requires the claimed misuse. |
| Response-model consistency | Concrete provider models differ or model identity is missing across review receipts | Receipt metadata, outside model state | `review_required` | Unit tests prove incomplete or mixed versions cannot route ready; every concrete model remains visible. |
| Observation integrity | Choice/Score confidence, Score distribution spread, and non-applicable receipt rows | Stored run receipts only | Preserve each measured field or state why a row was skipped | Tests prove provider confidence is retained and every input row is accounted for. |

Independent candidate-question and workflow review requests are dispatched concurrently through
the official SDK. Questions within each request also run in parallel. Every worker appends its own
received result and terminal outcome durably before returning; a sibling failure does not erase it. A complete score dictionary
retains every typed answer, probability, applicable and skipped check, selected path or code site,
per-dimension risk, composite index, uncertainty disposition, critical condition, concrete model,
and static repair. The composite remains unavailable when required coverage is missing and never
overrides an individual route condition.

Guard JSON has one canonical `model_observations` list and deterministic `policy_conclusions`; the
old duplicate `signals` list is removed. Each observation preserves the exact typed Noul answer and
raw probability, reviewer question and criteria, concrete model and hashes, plus references to its
shared input and principles. `review_inputs` stores the candidate question and receipt context per
`review_binding_id`, preserving the provider attempt and current question/component separately
from the request fingerprint. Full request state is referenced by hash and selected paths.
`principles` stores each exact rule, excerpt, and URL once by content hash. When code selected one
state component or consumer site, that exact inspected content remains in the canonical
observation. Feedback references the observation and principles and repeats only the action,
location, proposition, and typed answer needed to act. The review question's `focus` is the scope
limit in the observation. The output states plainly that a Noul probability is
not Jev rationale, measured accuracy, or proof of the defect. Combined atomicity feedback uses an
`assessment_id` and `pair_id` to reference `atomicity_assessments`; each assessment links its two
actual model inputs through `input_observation_ids`. It never presents a computed assessment as
a model observation. The report also preserves
per-dimension risks and scores, applicability and missing coverage, static repair actions, routing
policy, model version, and exact request identities. Each feedback item has a policy-derived
`flagged`, `uncertain`, `not_flagged`,
or `unthresholded` disposition; only a flagged item carries a `recommended_action`. Raw proposition
requirements use `observation` and are composed separately. Each feedback item includes its exact
question or consumer location, applicable state paths, source documentation passage and URL, review
fingerprint, and whether its basis is a model suspicion, an unvalidated advisory observation, or
code composition. The tool names a
missing state path when code can prove it; a missing-evidence probability alone cannot name the
unknown fact, and the feedback says so. Noul
observations never gain a fabricated confidence field.

Both free preflight and the final guard report include one `analysis_ownership` block. Its
`code_known` entries are exact structural observations already established by request validation or
the bounded Python AST collector; they do not certify what the program means. Its `semantic`
entries list the exact checks prepared for Jev. Its `incomplete` entries name unresolved references,
missing required atomicity evidence, or consumer coverage the collector cannot establish. An
incomplete required dimension has no composite score and cannot be averaged away by strong model
answers. The code-first rule and its official documentation passage stay in report provenance; the
tool does not ask Jev to decide whether an arbitrary program could have been implemented in code.

Receipts are append-only, fsynced JSONL. Before dispatch, a `started` record durably retains the exact
submitted request and a unique `attempt_id`. Official SDK transport hooks record the exact request
bytes before sending and response bytes before SDK decoding, as base64 with byte hashes. Response
events also retain HTTP status and provider request id. This preserves malformed, non-JSON and
HTTP-error responses. Authentication headers are not request data and are not recorded.

After decoding, a `received` record preserves the response, served model and usage before application
validation. Terminal `ok`, `invalid_response` or `error` records share the attempt identity. An
interrupted attempt remains visible through its preceding records; no terminal outcome is invented.
Every attempt's `request_sha256` uses the shared canonical state-and-questions hash excluding model;
the separate byte hashes identify actual wire bytes. History is not rewritten. The CLI disables SDK
retries and client-side request deadlines: an authorized experiment runs until it receives a response,
the caller interrupts it, or the transport reports a real connection failure. The CLI does not classify
programming errors as provider failures. Invalid or incomplete guard
thresholds fail before any provider call. Exit code `0`
means the command completed, `1` means a Jev call failed, `2` means the local input or output was
invalid, `3` means the guard returned an action other than `ready_for_small_trial`, and `4` exposes
an unexpected programming defect with a traceback on stderr. Routing-eligible review signals
change guard routing only when the caller supplies its experimental thresholds. Checks marked
`advisory_only` never change that route, even when thresholds are present.

## Interpreting results

A Noul value is the probability that its proposition is true; it has no separate confidence.
Choice and Score confidence describes concentration of the returned distribution, not observed
accuracy. A constant question may describe a rare property rather than a bad feature. Repeated runs
remain separate observations. Reworded questions and different concrete models remain separate
series. Evaluate reviewed cases, keep related revisions in one data split, and preserve an untouched
held-out group before making claims about improvement.

## Next controlled evaluation

Current state-clarity reviews inspect each explicit state path named in question instructions; when
none resolves, the receipt says that root state was the fallback. State relevance remains separate
and is intentionally not a whole-request score. A useful next experiment would ask, for one
code-selected `path` and `value`, whether that component contributes a fact, definition, or reference
needed for this answer. Code would continue to own component selection, so feedback can name the
inspected path. A low relevance probability would remain an observation; it would not prove
redundancy or trigger automatic deletion.

Evaluate that check with a question about a specific behavior inside a real callee, then remove
the callee in an explicit controlled variant. The call site must not already establish the answer:
“does this call delegate selection?” was a weak missing-evidence control, whereas whether the callee
skips rows with an error requires its implementation. Keep independently reviewed expectations and
original-source provenance outside the Jev request.

The current guard still reviews one request packet at a time. It does not yet prove that an entire
experiment contains real historical cases, lookalike and crossed controls, blind labels bound to the
exact packet, an untouched holdout, or a strong-model ceiling check. `ready_for_small_trial` means
the reviewed question and supplied consumer are ready for a small evidence-gathering run; it is not
whole-experiment readiness. Experiment-pack validation, blind label binding, and same-case variant
comparison remain required before any calibrated quality claim.

## Sources

- [TypeSafe documentation index](https://docs.typesafe.ai/llms.txt)
- [How to build with System One](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- [Python SDK](https://docs.typesafe.ai/sdk/python)
- [Noul](https://docs.typesafe.ai/primitives/noul), [Choice](https://docs.typesafe.ai/primitives/choice),
  [Score](https://docs.typesafe.ai/primitives/score), and [confidence](https://docs.typesafe.ai/confidence)
