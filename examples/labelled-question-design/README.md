# Labelled question-design set

This set tests one narrow contract: whether a candidate's typed answer must settle both of two
propositions that its consumer needs as separate outputs. `labels.json` holds the expected result;
candidate files never contain it.

Each matched group uses the same A/B pair, consumer outputs, source anchors, and cited mixed-truth
case for its broad and narrow question. This prevents the host from leaking the label by supplying
two propositions only for a known bad candidate. The spam and weather pairs are constructed
contrasts derived from the official TypeSafe decomposition examples.

Run `system-one-meta-builder prepare` on a candidate to inspect the exact request without making a
provider call. Record the candidate and prepared-request hashes before a live experiment.
