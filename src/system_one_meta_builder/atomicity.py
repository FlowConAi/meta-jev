"""Code-owned composition of separately observed proposition requirements."""

from collections.abc import Iterable, Mapping
from typing import Any

from .io import fingerprint
from .receipts import review_binding_id

PAIR_CHECKS = ("atomicity_requires_proposition_a", "atomicity_requires_proposition_b")


def is_pair_observation(check_id: str) -> bool:
    return check_id.split("__", 1)[0] in PAIR_CHECKS


def compose_atomicity(receipts: Iterable[Mapping[str, Any]], signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    indexed = {(signal["review_binding_id"], signal["check_id"]): signal for signal in signals}
    for receipt in receipts:
        pairs = receipt.get("atomicity_pair_coverage", {}).get("pairs", [])
        for index, pair in enumerate(pairs):
            keys = [f"{check}__{index}" for check in PAIR_CHECKS]
            binding_id = review_binding_id(receipt)
            observations = [indexed.get((binding_id, key)) for key in keys]
            available = all(observation is not None for observation in observations)
            results.append(
                {
                    "assessment_id": fingerprint({"review_binding_id": binding_id, "pair_id": pair["pair_id"]}),
                    "scope": "question",
                    "candidate_question_id": receipt["candidate_question_id"],
                    "check_id": "requires_both_independent_propositions",
                    "dimension": "atomicity",
                    "pair_id": pair["pair_id"],
                    "review_fingerprint": receipt["review_fingerprint"],
                    "review_binding_id": binding_id,
                    "status": "observed" if available else "incomplete",
                    "minimum_support_index": min(item["probability"] for item in observations) if available else None,
                    "formula": "minimum of the two proposition-required probabilities",
                    "meaning": "Support for both required outputs; not a joint probability or model-reported defect.",
                    "inputs": {
                        key: observation["probability"] if observation else None
                        for key, observation in zip(keys, observations, strict=True)
                    },
                    "input_observation_ids": [
                        observation["observation_id"] for observation in observations if observation is not None
                    ],
                    "contract": dict(pair),
                    "principle_references": observations[0].get("principle_references", []) if available else [],
                    "inspection_guidance": (
                        f"Expose separate answers for {pair['proposition_a']['text']!r} and "
                        f"{pair['proposition_b']['text']!r}. Their consumers need "
                        f"{pair['consumer_outputs']['a']!r} and {pair['consumer_outputs']['b']!r} separately."
                    ),
                    "source": "deterministic_pair_composition",
                }
            )
    return results
