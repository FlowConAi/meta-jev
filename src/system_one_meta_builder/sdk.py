"""The single TypeSafe SDK boundary used by CLI commands."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping
from importlib.metadata import version
from time import perf_counter
from typing import Any

import httpx2
from pydantic import TypeAdapter, ValidationError
from typesafe_sdk import Choice, Noul, RetryPolicy, Score, TypeSafeClient

from .io import InputError

DEFAULT_MODEL = "jev-latest"
SDK_VERSION = version("typesafe-sdk")
_QUESTION_ADAPTER = TypeAdapter(Noul | Choice | Score)


def question_schema() -> dict[str, Any]:
    """Return a candidate-question schema derived from the installed official SDK."""
    return _QUESTION_ADAPTER.json_schema()


def validate_question(raw: Any) -> Noul | Choice | Score:
    if not isinstance(raw, Mapping):
        raise InputError("each question must be a JSON object")
    kind = raw.get("type")
    model = {"noul": Noul, "choice": Choice, "score": Score}.get(kind)
    if model is None:
        raise InputError(f"unsupported question type: {kind!r}")
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        raise InputError(str(error)) from error


def validated_questions(raw: Any) -> dict[str, Noul | Choice | Score]:
    if not isinstance(raw, Mapping) or not raw:
        raise InputError("request.questions must be a nonempty JSON object")
    return {str(name): validate_question(question) for name, question in raw.items()}


def normalize_request(document: Any, model_override: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(document, Mapping):
        raise InputError("input must be a JSON object")
    request = document.get("request", document)
    if not isinstance(request, Mapping):
        raise InputError("request must be a JSON object")
    if "state" not in request:
        raise InputError("request.state is required")
    questions = validated_questions(request.get("questions"))
    model = model_override or request.get("model") or DEFAULT_MODEL
    if not isinstance(model, str) or not model:
        raise InputError("request.model must be a nonempty string")
    submitted = {
        "state": request["state"],
        "questions": {
            name: question.model_dump(mode="json", exclude_none=True) for name, question in questions.items()
        },
        "model": model,
    }
    return submitted, questions


def validate_answer_bindings(submitted: Mapping[str, Any], response: Mapping[str, Any]) -> None:
    """The SDK parses answer types; code also requires the requested identities and types."""
    answers = response.get("answers")
    questions = submitted["questions"]
    if not isinstance(answers, Mapping) or set(answers) != set(questions):
        raise InputError("response answer keys do not match the submitted question keys")
    for name, question in questions.items():
        if answers[name].get("type") != question["type"]:
            raise InputError(f"response answer {name!r} does not match the requested primitive")


def call_once(
    submitted: Mapping[str, Any],
    questions: Mapping[str, Any],
    *,
    record_event: Callable[[dict[str, Any]], None],
) -> tuple[dict[str, Any], float]:
    """Use SDK transport hooks to retain wire evidence before response decoding."""

    def record_request(request: httpx2.Request) -> None:
        body = request.read()
        record_event(
            {
                "event": "http_request",
                "body_base64": base64.b64encode(body).decode("ascii"),
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }
        )

    def record_response(response: httpx2.Response) -> None:
        body = response.read()
        record_event(
            {
                "event": "http_response",
                "status_code": response.status_code,
                "request_id": response.headers.get("x-typesafe-request-id"),
                "body_base64": base64.b64encode(body).decode("ascii"),
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }
        )

    started = perf_counter()
    with (
        httpx2.Client(
            timeout=None,
            event_hooks={"request": [record_request], "response": [record_response]},
        ) as transport,
        TypeSafeClient(retry=RetryPolicy(max_retries=0), http_client=transport) as client,
    ):
        response = client.system_one(
            state=submitted["state"],
            questions=questions,
            model=submitted["model"],
        )
    elapsed = perf_counter() - started
    raw = json.loads(response.raw_http_response.content)
    return raw, elapsed
