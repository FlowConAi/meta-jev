"""Stable receipt shapes for submitted requests, responses, and failures."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .io import fingerprint
from .sdk import SDK_VERSION


def request_sha256(submitted: Mapping[str, Any]) -> str:
    """Canonical request identity, excluding model and receipt metadata."""
    payload = {"state": submitted["state"], "questions": submitted["questions"]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def review_binding_id(receipt: Mapping[str, Any]) -> str:
    """Identify a retained answer's use without changing the provider request identity."""
    condition = receipt.get("condition_comparison", {})
    return fingerprint(
        {
            "review_fingerprint": receipt["review_fingerprint"],
            "attempt_id": receipt.get("attempt_id"),
            "scope": receipt.get("scope"),
            "candidate_question_id": receipt.get("candidate_question_id"),
            "condition_id": condition.get("condition_id"),
            "side": condition.get("side"),
        }
    )


def started_receipt(*, kind: str, submitted: Mapping[str, Any], **context: Any) -> dict[str, Any]:
    """Write this receipt durably before dispatching the attempt."""
    return {
        **context,
        "schema_version": 1,
        "kind": kind,
        "status": "started",
        "created_at": datetime.now(UTC).isoformat(),
        "attempt_id": str(uuid4()),
        "sdk": {"package": "typesafe-sdk", "version": SDK_VERSION},
        "submitted": dict(submitted),
        "request_sha256": request_sha256(submitted),
    }


def success_receipt(
    *,
    kind: str,
    submitted: Mapping[str, Any],
    response: Mapping[str, Any],
    seconds: float,
    **context: Any,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": kind,
        "status": "ok",
        "created_at": datetime.now(UTC).isoformat(),
        "sdk": {"package": "typesafe-sdk", "version": SDK_VERSION},
        "submitted": dict(submitted),
        "request_sha256": request_sha256(submitted),
        "response": dict(response),
        "response_model": response.get("model"),
        "usage": response.get("usage"),
        "duration_seconds": round(seconds, 6),
        **context,
    }


def error_receipt(*, kind: str, submitted: Mapping[str, Any], error: BaseException, **context: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": kind,
        "status": "error",
        "created_at": datetime.now(UTC).isoformat(),
        "sdk": {"package": "typesafe-sdk", "version": SDK_VERSION},
        "submitted": dict(submitted),
        "request_sha256": request_sha256(submitted),
        "error": {"type": type(error).__name__, "message": str(error)},
        **context,
    }
