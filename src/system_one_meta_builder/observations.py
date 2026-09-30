"""Observed signal diagnostics with no new model calls or automatic pruning."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .io import InputError, json_line


def _series_id(question_id: str, definition: Any, response_model: Any, revision_id: Any) -> tuple[str, dict[str, Any]]:
    identity = {
        "question": definition,
        "response_model": response_model,
        "revision_id": revision_id,
    }
    digest = hashlib.sha256(json_line(identity).encode()).hexdigest()[:12]
    return f"{question_id}@{digest}", identity


def _receipt_signals(row: Mapping[str, Any], index: int) -> tuple[dict[str, float], dict[str, Any]]:
    response = row.get("response")
    submitted = row.get("submitted")
    if not isinstance(response, Mapping) or not isinstance(submitted, Mapping):
        raise InputError(f"run receipt row {index} lacks response or submitted request")
    answers = response.get("answers")
    definitions = submitted.get("questions")
    if not isinstance(answers, Mapping) or not isinstance(definitions, Mapping):
        raise InputError(f"run receipt row {index} lacks answer or question objects")
    if not answers:
        raise InputError(f"run receipt row {index} has no answers")
    signals: dict[str, float] = {}
    metadata: dict[str, Any] = {}
    for question_id, answer in answers.items():
        if not isinstance(answer, Mapping) or question_id not in definitions:
            raise InputError(f"run receipt row {index} has an unbound answer {question_id!r}")
        base, identity = _series_id(
            str(question_id),
            definitions[question_id],
            response.get("model"),
            row.get("revision_id"),
        )
        kind = answer.get("type")
        if kind == "noul" and isinstance(answer.get("noul"), (int, float)):
            signals[base] = float(answer["noul"])
            metadata[base] = {"question_id": question_id, "metric": "true_probability", **identity}
        elif kind == "score" and isinstance(answer.get("score"), (int, float)):
            signals[base] = float(answer["score"])
            metadata[base] = {"question_id": question_id, "metric": "expected_score", **identity}
            _add_confidence(signals, metadata, base, question_id, identity, answer, index)
            probabilities = answer.get("probabilities")
            if not isinstance(probabilities, Mapping) or not probabilities:
                raise InputError(f"run receipt row {index} has no Score probabilities for {question_id!r}")
            score = float(answer["score"])
            variance = 0.0
            for level, probability in probabilities.items():
                if not isinstance(probability, (int, float)):
                    raise InputError(f"run receipt row {index} has a nonnumeric probability for {question_id!r}")
                try:
                    numeric_level = float(level)
                except (TypeError, ValueError) as error:
                    raise InputError(
                        f"run receipt row {index} has a nonnumeric Score level for {question_id!r}"
                    ) from error
                variance += float(probability) * (numeric_level - score) ** 2
            spread_id = f"{base}#spread"
            signals[spread_id] = math.sqrt(max(variance, 0.0))
            metadata[spread_id] = {
                "question_id": question_id,
                "metric": "derived_score_standard_deviation",
                **identity,
            }
        elif kind == "choice" and isinstance(answer.get("probabilities"), Mapping):
            for option, probability in answer["probabilities"].items():
                if not isinstance(probability, (int, float)):
                    raise InputError(f"run receipt row {index} has a nonnumeric probability for {question_id!r}")
                signal_id = f"{base}={option}"
                signals[signal_id] = float(probability)
                metadata[signal_id] = {
                    "question_id": question_id,
                    "choice_option": option,
                    "metric": "option_probability",
                    **identity,
                }
            _add_confidence(signals, metadata, base, question_id, identity, answer, index)
        else:
            raise InputError(f"run receipt row {index} has an invalid answer {question_id!r}")
    return signals, metadata


def _add_confidence(
    signals: dict[str, float],
    metadata: dict[str, Any],
    base: str,
    question_id: Any,
    identity: Mapping[str, Any],
    answer: Mapping[str, Any],
    row_index: int,
) -> None:
    confidence = answer.get("confidence")
    if not isinstance(confidence, (int, float)):
        raise InputError(f"run receipt row {row_index} has no numeric confidence for {question_id!r}")
    signal_id = f"{base}#confidence"
    signals[signal_id] = float(confidence)
    metadata[signal_id] = {"question_id": question_id, "metric": "provider_confidence", **identity}


def observation(row: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        raise InputError(f"JSONL row {index} must be an object")
    metadata: dict[str, Any]
    if isinstance(row.get("signals"), Mapping):
        cohort_id = row.get("cohort_id")
        if not isinstance(cohort_id, str) or not cohort_id:
            raise InputError(f"manual signal row {index} requires a nonempty cohort_id")
        raw_signals = row["signals"]
        signals = {f"{cohort_id}/{name}": value for name, value in raw_signals.items()}
        metadata = {f"{cohort_id}/{name}": {"cohort_id": cohort_id, "question_id": str(name)} for name in raw_signals}
    elif row.get("kind") == "run" and row.get("status") == "ok":
        signals, metadata = _receipt_signals(row, index)
    elif row.get("kind") == "run":
        return None
    else:
        return None
    numeric: dict[str, float] = {}
    for name, value in signals.items():
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise InputError(f"signal {name!r} on row {index} must be a finite number")
        numeric[str(name)] = float(value)
    return {
        "observation_id": f"row-{index}",
        "case_id": str(row.get("case_id", f"row-{index}")),
        "group_id": None if row.get("group_id") is None else str(row["group_id"]),
        "signals": numeric,
        "signal_metadata": metadata,
    }


def _pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs, strict=True)
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    dx, dy = [x - mean_x for x in xs], [y - mean_y for y in ys]
    denominator = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    if denominator == 0:
        return None
    return sum(x * y for x, y in zip(dx, dy, strict=True)) / denominator


def inspect(rows: Iterable[Any]) -> dict[str, Any]:
    rows = list(rows)
    observations: list[dict[str, Any]] = []
    applied_rows: list[int] = []
    skipped_by_reason: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows, 1):
        item = observation(row, index)
        if item is not None:
            observations.append(item)
            applied_rows.append(index)
            continue
        if isinstance(row, Mapping) and row.get("kind") == "run":
            reason = f"run_{row.get('status', 'status_missing')}"
        elif isinstance(row, Mapping) and row.get("kind") in {"transport", "guard", "review"}:
            reason = f"{row.get('kind')}_row_not_applicable"
        else:
            reason = "row_not_applicable"
        skipped_by_reason[reason].append(index)
    by_signal: dict[str, list[tuple[str, float]]] = defaultdict(list)
    signal_metadata: dict[str, Any] = {}
    for row in observations:
        signal_metadata.update(row["signal_metadata"])
        for signal, value in row["signals"].items():
            by_signal[signal].append((row["observation_id"], value))

    signals: dict[str, Any] = {}
    for name, entries in sorted(by_signal.items()):
        values = [value for _, value in entries]
        low, high = min(values), max(values)
        signals[name] = {
            "identity": signal_metadata[name],
            "count": len(values),
            "min": low,
            "max": high,
            "range": high - low,
            "constant": low == high,
        }

    correlations: list[dict[str, Any]] = []
    names = sorted(by_signal)
    mappings = {name: dict(by_signal[name]) for name in names}
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            shared = sorted(mappings[left].keys() & mappings[right].keys())
            pairs = [(mappings[left][item], mappings[right][item]) for item in shared]
            value = _pearson(pairs)
            record: dict[str, Any] = {"left": left, "right": right, "aligned_count": len(pairs)}
            if value is None:
                record.update(value=None, reason="fewer_than_3_aligned_cases_or_constant_signal")
            else:
                record["value"] = value
            correlations.append(record)
    groups = {row["group_id"] for row in observations if row["group_id"] is not None}
    return {
        "kind": "observed_signal_report",
        "input_row_count": len(rows),
        "observation_count": len(observations),
        "distinct_case_count": len({row["case_id"] for row in observations}),
        "group_count": len(groups),
        "signals": signals,
        "pearson_correlations": correlations,
        "row_applicability": {
            "applied_rows": applied_rows,
            "skipped_count": sum(len(indexes) for indexes in skipped_by_reason.values()),
            "skipped_by_reason": dict(sorted(skipped_by_reason.items())),
        },
        "interpretation": (
            "These are observed distributions, not correctness labels. Repeats remain separate "
            "observations, and revised question meanings or returned models form separate series. "
            "A constant signal may be appropriate for a rare condition; nothing is removed automatically."
        ),
    }
