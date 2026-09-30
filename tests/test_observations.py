from __future__ import annotations

import pytest

from system_one_meta_builder.io import InputError
from system_one_meta_builder.observations import inspect


def _receipt(case_id: str, instruction: str, value: float) -> dict:
    return {
        "kind": "run",
        "status": "ok",
        "case_id": case_id,
        "revision_id": "v1",
        "submitted": {"questions": {"q": {"type": "noul", "instructions": instruction}}},
        "response": {
            "model": "jev-1.13.0",
            "answers": {"q": {"type": "noul", "noul": value}},
        },
    }


def test_repeats_count_separately_and_revisions_do_not_pool() -> None:
    report = inspect(
        [
            _receipt("same-case", "Does A hold?", 0.1),
            _receipt("same-case", "Does A hold?", 0.3),
            _receipt("same-case", "Does a narrower A hold?", 0.9),
        ]
    )
    assert report["observation_count"] == 3
    assert report["distinct_case_count"] == 1
    counts = sorted(signal["count"] for signal in report["signals"].values())
    assert counts == [1, 2]


def test_correlations_align_observations_instead_of_deduplicating_case_ids() -> None:
    report = inspect(
        [
            {"cohort_id": "trial-v1", "case_id": "same", "signals": {"a": 0.1, "b": 0.2}},
            {"cohort_id": "trial-v1", "case_id": "same", "signals": {"a": 0.2, "b": 0.4}},
            {"cohort_id": "trial-v1", "case_id": "other", "signals": {"a": 0.3, "b": 0.6}},
        ]
    )
    correlation = report["pearson_correlations"][0]
    assert correlation["aligned_count"] == 3
    assert correlation["value"] == pytest.approx(1.0)


def test_manual_signals_require_a_cohort_identity() -> None:
    with pytest.raises(InputError, match="cohort_id"):
        inspect([{"case_id": "one", "signals": {"q": 0.5}}])


def test_choice_and_score_preserve_confidence_and_score_spread() -> None:
    report = inspect(
        [
            {
                "kind": "run",
                "status": "ok",
                "case_id": "case",
                "revision_id": "v1",
                "submitted": {
                    "questions": {
                        "route": {"type": "choice", "instructions": "Choose.", "criteria": {"a": {}, "b": {}}},
                        "severity": {
                            "type": "score",
                            "instructions": "Rate.",
                            "criteria": ["none", "some", "blocking"],
                        },
                    }
                },
                "response": {
                    "model": "jev-1.13.0",
                    "answers": {
                        "route": {
                            "type": "choice",
                            "choice": "a",
                            "confidence": 0.6,
                            "probabilities": {"a": 0.75, "b": 0.25},
                        },
                        "severity": {
                            "type": "score",
                            "score": 1.0,
                            "confidence": 0.4,
                            "legend": {"0": "none", "1": "some", "2": "blocking"},
                            "probabilities": {"0": 0.5, "1": 0.0, "2": 0.5},
                        },
                    },
                },
            }
        ]
    )

    by_metric = {signal["identity"]["metric"]: signal for signal in report["signals"].values()}
    assert by_metric["provider_confidence"]["count"] == 1
    assert sorted(
        signal["min"] for signal in report["signals"].values() if signal["identity"]["metric"] == "provider_confidence"
    ) == [0.4, 0.6]
    assert by_metric["derived_score_standard_deviation"]["min"] == pytest.approx(1.0)


def test_inspect_reports_every_skipped_row_by_reason() -> None:
    report = inspect(
        [
            _receipt("case", "Does A hold?", 0.2),
            {"kind": "run", "status": "error", "error": {"message": "provider unavailable"}},
            {"kind": "transport", "event": "request"},
            {"kind": "review", "status": "ok"},
            {"unrelated": True},
        ]
    )

    assert report["input_row_count"] == 5
    assert report["row_applicability"] == {
        "applied_rows": [1],
        "skipped_count": 4,
        "skipped_by_reason": {
            "review_row_not_applicable": [4],
            "row_not_applicable": [5],
            "run_error": [2],
            "transport_row_not_applicable": [3],
        },
    }
