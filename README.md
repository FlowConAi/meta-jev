# Meta Jev

Meta Jev helps a coding agent or researcher **design, check, and test typed System One questions**. A host LLM or person proposes the questions; Meta Jev validates the request, asks narrow Jev review questions, runs a small trial, and records exactly what happened. It does not generate or silently rewrite the proposal.

Use it when a broad goal such as “did this change preserve the required behavior?” needs to become atomic `noul`, `choice`, or `score` questions with explicit evidence and a consumer policy. The design score is an **experimental review index**, not measured accuracy or approval.

## Install

```bash
git clone https://github.com/FlowConAi/meta-jev.git
cd meta-jev
uv tool install .
npm install --global jev-compiler@0.1.0
```

The pinned [Jevc compiler](https://github.com/doronp/jevc) validates typed programs and supplies their deterministic reducer. Set `TYPESAFE_API_KEY` in your environment for the commands that call Jev: `review`, normal `guard`, `run`, and `run-program`. Do not put a key in a candidate file.

## A small working loop

```bash
# Generate a brief and candidate schema for your host agent.
system-one-meta-builder propose \
  --question 'Does this change preserve each required validation behavior?' > brief.json

# Have the host agent or a person write candidate.json from that brief.
system-one-meta-builder prepare candidate.json > prepared.json
system-one-meta-builder guard candidate.json --code-only > structural.json
system-one-meta-builder guard candidate.json --output guard.receipts.jsonl > guard.json

# Inspect the raw judgments and repair the question, state, or consumer as needed.
# Guard defaults to review_required until you supply an explicit experimental policy.
system-one-meta-builder run candidate.json --output run.receipts.jsonl > run.json
system-one-meta-builder inspect-results run.receipts.jsonl > observations.json
```

`prepare` and `guard --code-only` make no model calls. `guard` reviews each question; `run` sends the candidate's independent questions together in one System One request. For program IR, use `compile-program` offline and `run-program` for the live call. All commands are noninteractive; JSON goes to stdout, status to stderr, and `-` reads stdin.

## Commands

| Command | Job |
| --- | --- |
| `propose` | Package a goal, cases, and source evidence into a host-agent brief and SDK-derived candidate schema. |
| `prepare` | Validate a candidate with the official SDK and show the exact planned review requests; no provider call. |
| `review` | Run narrow, independent design checks and retain typed answers. |
| `guard` | Combine structural checks and review observations into an explicit trial route; `--code-only` is free. |
| `run` | Execute one candidate request and retain the wire response and usage. |
| `inspect-results` | Summarize stored observations without new calls or invented labels. |
| `compile-program` / `run-program` | Validate Jevc program IR offline, then execute it against runtime state. |

A candidate can be a System One request or a wrapper that adds case identity, intended uses, consumer code, and source-backed review context. See the [candidate format and full CLI reference](docs/reference.md#candidate-input) and the [constructed labelled examples](examples/labelled-question-design/).

## Reading the result

- Jev makes **atomic typed judgments**. Code owns validation, arithmetic, weights, routing, and side effects. A Noul probability is not an explanation or a separate confidence score.
- Every live attempt has append-only receipts with the submitted request, raw transport response, served model, usage, and terminal outcome. `jev-latest` is the default alias; compare or calibrate against the **served version**, not just the requested alias.
- Workflow checks share a packet only with sites in the same collected source context. Every packet remains separate in receipts; the workflow score uses the strongest applicable risk across all packets, and missing packets remain incomplete.
- Missing question evidence, unresolved state references, and unsupported consumer code remain visible as incomplete. Python consumer analysis supports direct SDK reads and [explicit host-declared bindings](docs/reference.md#candidate-input) for adapter or scalar-map reads. A declared join is not proof of runtime data flow or consumer semantics.
- A `ready_for_small_trial` route means try a small labelled batch. It does **not** certify correctness or whole-experiment readiness. Keep blind labels and held-out cases before making quality claims.

The [technical reference](docs/reference.md) documents the review matrix, scores, cache identity, receipt format, exit codes, and current limits. This is a source release, not a PyPI publication. The private experiment corpus and the excluded cookbook-derived research module are not included.

Sources: [TypeSafe System One concepts](https://docs.typesafe.ai/concepts/how-to-build-with-system-one) · [Python SDK](https://docs.typesafe.ai/sdk/python) · [Jevc](https://github.com/doronp/jevc)
