"""Noninteractive CLI for host LLMs and humans."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from typing import Any

from typesafe_sdk import TypeSafeAPIResponseValidationError, TypeSafeError

from .guard import (
    guard_report,
    reusable_reviews,
    review_signals,
    routing_policy,
    scoring_policy,
    validate_review_response,
)
from .io import (
    InputError,
    append_jsonl,
    ensure_appendable,
    json_line,
    loads_json,
    read_json,
    read_text,
)
from .jevc import compile_program, reduce_program
from .observations import inspect
from .preflight import code_preflight
from .principles import PRINCIPLES
from .propose import proposal_brief
from .receipts import error_receipt, request_sha256, started_receipt, success_receipt
from .review import check_metadata, guidance_for, review_requests
from .sdk import DEFAULT_MODEL, call_once, normalize_request, validate_answer_bindings, validated_questions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="system-one-meta-builder",
        description="Prepare, review, run, and measure System One question experiments.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('system-one-meta-builder')}")
    sub = parser.add_subparsers(dest="command", required=True)

    propose = sub.add_parser("propose", help="prepare a host-LLM question-decomposition brief")
    start = propose.add_mutually_exclusive_group(required=True)
    start.add_argument("--question", help="initial broad question to decompose")
    start.add_argument("--goal", help="research or consuming-code goal")
    start.add_argument("--input", help="JSON research setup path, or - for stdin")
    propose.add_argument("--evidence", action="append", default=[], help="evidence file; repeatable")
    propose.add_argument("--format", choices=("json", "text"), default="json")

    prepare = sub.add_parser("prepare", help="print exact meta-review requests without API calls")
    prepare.add_argument("input", help="candidate JSON path, or - for stdin")
    prepare.add_argument("--model", default=DEFAULT_MODEL)

    review = sub.add_parser("review", help="run independent Jev meta-questions per candidate question")
    review.add_argument("input", help="candidate JSON path, or - for stdin")
    review.add_argument("--output", required=True, help="append-only JSONL receipt path")
    review.add_argument("--model", default=DEFAULT_MODEL)

    guard = sub.add_parser("guard", help="preflight an experiment before spending on a trial batch")
    guard.add_argument("input", help="candidate JSON path, or - for stdin")
    guard.add_argument("--output", required=True, help="append-only JSONL review and guard receipts")
    guard.add_argument("--reuse", help="prior JSONL review receipts to reuse by exact fingerprint")
    guard.add_argument("--model", default=DEFAULT_MODEL)
    guard.add_argument("--policy", help="optional JSON scoring policy path")
    guard.add_argument("--clear-below", type=float)
    guard.add_argument("--flag-at", type=float)
    guard.add_argument("--code-only", action="store_true", help="return structural checks without any Jev call")

    run = sub.add_parser("run", help="execute one candidate System One request once")
    run.add_argument("input", help="candidate JSON path, or - for stdin")
    run.add_argument("--output", required=True, help="append-only JSONL receipt path")
    run.add_argument("--model", help="override request.model; defaults to the candidate value, then jev-latest")

    compile_jev = sub.add_parser("compile-program", help="compile a Jevc Program into an SDK-validated request")
    compile_jev.add_argument("input", help="Jevc Program JSON path, or - for stdin")
    compile_jev.add_argument("--state", required=True, help="request state JSON path")
    compile_jev.add_argument("--model", help="override Jevc's jev-latest default")

    run_jev = sub.add_parser("run-program", help="compile and execute one Jevc Program with exact receipts")
    run_jev.add_argument("input", help="Jevc Program JSON path, or - for stdin")
    run_jev.add_argument("--state", required=True, help="request state JSON path")
    run_jev.add_argument("--output", required=True, help="append-only JSONL receipt path")
    run_jev.add_argument("--model", help="override Jevc's jev-latest default")

    inspect_parser = sub.add_parser("inspect-results", help="measure stored signal variation and correlation")
    inspect_parser.add_argument("input", help="JSONL observations or run receipts, or - for stdin")
    sub.add_parser("principles", help="print the source-backed reviewer principle registry")
    return parser


def _print(value: Any) -> None:
    print(json_line(value))


def _propose(args: argparse.Namespace) -> int:
    setup = read_json(args.input) if args.input else None
    evidence = [{"source": path, "content": read_text(path)} for path in args.evidence]
    result = proposal_brief(question=args.question, goal=args.goal, setup=setup, evidence=evidence)
    if args.format == "text":
        start = result["starting_point"]
        print("System One question-decomposition brief")
        print(json.dumps(start, ensure_ascii=False, indent=2))
        if evidence:
            print("\nEvidence")
            for item in evidence:
                print(f"\n--- {item['source']} ---\n{item['content']}")
        print("\nHost LLM task")
        print("\n".join(f"- {line}" for line in result["host_llm_task"]))
        print("\nCandidate JSON Schema")
        print(json.dumps(result["candidate_contract"], ensure_ascii=False, indent=2))
    else:
        _print(result)
    return 0


def _prepare(args: argparse.Namespace) -> int:
    document = read_json(args.input)
    _print({"kind": "prepared_review", "requests": review_requests(document, args.model)})
    return 0


def _execute_request(
    *,
    kind: str,
    submitted: Mapping[str, Any],
    output: str,
    context: Mapping[str, Any],
    validate: Callable[[Mapping[str, Any], Mapping[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], bool]:
    started = started_receipt(kind=kind, submitted=submitted, **context)
    append_jsonl(output, started)
    attempt_context = {**context, "attempt_id": started["attempt_id"]}

    def record_event(event: dict[str, Any]) -> None:
        append_jsonl(
            output,
            {
                "kind": "transport",
                "attempt_id": started["attempt_id"],
                "request_sha256": started["request_sha256"],
                **event,
            },
        )

    try:
        response, seconds = call_once(
            submitted,
            validated_questions(submitted["questions"]),
            record_event=record_event,
        )
    except TypeSafeError as error:
        receipt = error_receipt(kind=kind, submitted=submitted, error=error, **attempt_context)
        if isinstance(error, TypeSafeAPIResponseValidationError):
            receipt["status"] = "invalid_response"
        return receipt, False
    receipt = success_receipt(
        kind=kind,
        submitted=submitted,
        response=response,
        seconds=seconds,
        **attempt_context,
    )
    append_jsonl(output, {**receipt, "status": "received"})
    if validate is not None:
        try:
            validate(submitted, response)
        except InputError as error:
            return {
                **receipt,
                "status": "invalid_response",
                "error": {"type": type(error).__name__, "message": str(error)},
            }, False
    return receipt, True


def _execute_review_item(item: Mapping[str, Any], output: str) -> tuple[dict[str, Any], bool]:
    context = {key: value for key, value in item.items() if key != "submitted"}
    context["inspection_guidance"] = guidance_for(item["scope"])
    context["check_metadata"] = check_metadata(item["scope"])
    return _execute_request(
        kind="review",
        submitted=item["submitted"],
        output=output,
        context=context,
        validate=validate_review_response,
    )


def _review(args: argparse.Namespace) -> int:
    document = read_json(args.input)
    prepared = review_requests(document, args.model)
    ensure_appendable(args.output)
    failures = 0
    completed = 0
    runnable = []
    for item in prepared:
        if item.get("status") == "not_reviewed":
            append_jsonl(args.output, item)
            _print(item)
            continue
        runnable.append(item)
    for receipt, succeeded in _execute_review_batch(runnable, args.output):
        if succeeded:
            completed += 1
        else:
            failures += 1
        _print(receipt)
    print(f"reviewed {completed} request(s); {failures} failed", file=sys.stderr)
    return 1 if failures else 0


def _execute_review_batch(items: list[Mapping[str, Any]], output: str) -> list[tuple[dict[str, Any], bool]]:
    """Independent packets run concurrently; each worker retains its result before returning."""

    def execute(item: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        receipt, succeeded = _execute_review_item(item, output)
        receipt["guard_source"] = "fresh"
        append_jsonl(output, receipt)
        return receipt, succeeded

    with ThreadPoolExecutor() as pool:
        return list(pool.map(execute, items))


def _run(args: argparse.Namespace) -> int:
    document = read_json(args.input)
    submitted, _ = normalize_request(document, args.model)
    ensure_appendable(args.output)
    request = document.get("request", document) if isinstance(document, Mapping) else {}
    context: dict[str, Any] = {
        "model_source": "cli" if args.model is not None else "candidate" if request.get("model") else "default"
    }
    if isinstance(document, Mapping):
        for key in ("case_id", "group_id", "revision_id"):
            if key in document:
                context[key] = document[key]
    receipt, succeeded = _execute_request(
        kind="run",
        submitted=submitted,
        output=args.output,
        context=context,
        validate=validate_answer_bindings,
    )
    append_jsonl(args.output, receipt)
    _print(receipt)
    if not succeeded:
        print(f"run failed: {receipt['error']['message']}", file=sys.stderr)
        return 1
    print(f"run completed with model {receipt['response_model']}", file=sys.stderr)
    return 0


def _compile_program(args: argparse.Namespace) -> int:
    program = read_json(args.input)
    if not isinstance(program, Mapping):
        raise InputError("Jevc program must be a JSON object")
    submitted, compiler = compile_program(program, read_json(args.state), args.model)
    _print({"kind": "compiled_program", "compiler": compiler, "request": submitted})
    return 0


def _run_program(args: argparse.Namespace) -> int:
    program = read_json(args.input)
    if not isinstance(program, Mapping):
        raise InputError("Jevc program must be a JSON object")
    submitted, compiler = compile_program(program, read_json(args.state), args.model)
    ensure_appendable(args.output)
    context = {
        "compiler": compiler,
        "program": dict(program),
        "model_source": "cli" if args.model is not None else "compiler_default",
    }
    receipt, succeeded = _execute_request(
        kind="run",
        submitted=submitted,
        output=args.output,
        context=context,
        validate=validate_answer_bindings,
    )
    if succeeded:
        try:
            receipt["verdict"] = reduce_program(program, receipt["response"]["answers"])
        except InputError as error:
            receipt["status"] = "reduction_failed"
            receipt["error"] = {"type": type(error).__name__, "message": str(error)}
            succeeded = False
    append_jsonl(args.output, receipt)
    _print(receipt)
    if not succeeded:
        print(f"compiled run failed: {receipt['error']['message']}", file=sys.stderr)
        return 1
    print(f"compiled run completed with verdict {receipt['verdict']}", file=sys.stderr)
    return 0


def _jsonl_rows(source: str) -> list[Any]:
    rows = []
    for number, line in enumerate(read_text(source).splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(loads_json(line))
        except InputError as error:
            raise InputError(f"JSONL row {number}: {error}") from error
    return rows


def _guard(args: argparse.Namespace) -> int:
    document = read_json(args.input)
    score_policy = scoring_policy(read_json(args.policy) if args.policy else None)
    route_policy = routing_policy(args.clear_below, args.flag_at)
    candidate_submitted, _ = normalize_request(document, args.model)
    prepared = review_requests(document, args.model)
    ensure_appendable(args.output)
    structural = code_preflight(document, prepared, request_sha256(candidate_submitted))
    if args.code_only or structural["route"] == "gather_evidence":
        append_jsonl(args.output, structural)
        _print(structural)
        return 3
    reusable = reusable_reviews(_jsonl_rows(args.reuse)) if args.reuse else {}
    receipts: list[Mapping[str, Any]] = []
    skipped_reviews: list[Mapping[str, Any]] = []
    runnable = []
    failures = 0
    for item in prepared:
        if item.get("status") == "not_reviewed":
            append_jsonl(args.output, item)
            skipped_reviews.append(item)
            continue
        review_fingerprint = item["review_fingerprint"]
        if review_fingerprint in reusable:
            receipt = {
                **reusable[review_fingerprint],
                **item,
                "guard_source": "reused",
            }
            receipts.append(receipt)
            append_jsonl(args.output, receipt)
            continue
        runnable.append(item)
    for receipt, succeeded in _execute_review_batch(runnable, args.output):
        if succeeded:
            receipts.append(receipt)
        else:
            failures += 1
    if failures:
        _print({"kind": "guard", "status": "error", "failed_reviews": failures})
        return 1
    metadata = {scope: check_metadata(scope) for scope in ("question", "workflow", "criteria_condition")}
    signals = review_signals(receipts, metadata)
    report = guard_report(
        document=document,
        receipts=receipts,
        signals=signals,
        route_policy=route_policy,
        score_policy=score_policy,
        candidate_request_sha256=request_sha256(candidate_submitted),
        skipped_reviews=skipped_reviews,
        analysis_ownership=structural["analysis_ownership"],
    )
    append_jsonl(args.output, report)
    _print(report)
    return 0 if report["route"] == "ready_for_small_trial" else 3


def _inspect(args: argparse.Namespace) -> int:
    _print(inspect(_jsonl_rows(args.input)))
    return 0


def _principles(_args: argparse.Namespace) -> int:
    _print({"kind": "principles", "principles": PRINCIPLES})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return {
            "propose": _propose,
            "prepare": _prepare,
            "review": _review,
            "guard": _guard,
            "run": _run,
            "compile-program": _compile_program,
            "run-program": _run_program,
            "inspect-results": _inspect,
            "principles": _principles,
        }[args.command](args)
    except (InputError, OSError) as error:
        _print({"status": "error", "error": {"type": type(error).__name__, "message": str(error)}})
        return 2
    except Exception as error:  # unexpected programming defects retain a distinct exit contract
        traceback.print_exc(file=sys.stderr)
        _print({"status": "error", "error": {"type": type(error).__name__, "message": str(error)}})
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
