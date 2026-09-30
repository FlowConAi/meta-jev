# System One Meta Builder

The host LLM or human owns question proposals and revisions. Jev supplies typed judgments and
probabilities. Deterministic code owns request validation, receipts, and observations.

Jevc owns compiled Program validation, question lowering, and reducer execution. Meta Builder owns
the Python SDK boundary and the experiment evidence around that program; do not reimplement Jevc's
IR or reducer in Python.

Do not add a broad "is this suitable for Jev?" classifier or turn advisory signals into automatic
certification. Keep question-meaning review separate from observed behavior on real cases. Preserve
exact submitted requests and responses. Use the official TypeSafe SDK; do not add another HTTP
transport. Every runnable default uses `jev-latest`, and receipts retain the concrete response model.
The guard's composite score is an explicit deterministic experiment policy, never a claim of
accuracy. Preserve every raw signal and critical route when changing weights or presentation.

The design owner is `README.md`. Update it when the workflow changes.

For a question-only task, run `propose --question ...`, write the returned candidate JSON, then run
`prepare`, `guard`, a small `run`, and `inspect-results`. For a data-first task, run `propose --input ...`
with the real cases and optional labels, then revise the proposal using the observed results.
Host agents own the loop; this tool must not add a generative-provider client or an autonomous rewrite step.
