"""JSON input and append-only receipt helpers."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any

_APPEND_LOCK = Lock()


class InputError(ValueError):
    """Raised when a CLI input cannot be interpreted without guessing."""


def question_review_context(document: Mapping[str, Any], question_id: str) -> Mapping[str, Any]:
    """Read optional review metadata; a missing or null container means absent."""
    current: Any = document
    path: list[str] = []
    for key in ("review_context", "questions", question_id):
        path.append(key)
        current = current.get(key)
        if current is None:
            return {}
        if not isinstance(current, Mapping):
            raise InputError(f"{'.'.join(path)} must be an object")
    return current


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def loads_json(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as error:
        raise InputError(f"invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}") from error


def read_text(source: str) -> str:
    return sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")


def read_json(source: str) -> Any:
    return loads_json(read_text(source))


def json_line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json_line(value).encode()).hexdigest()


def resolve_path(value: Any, path: str) -> Any:
    """Resolve one dotted/indexed path without guessing missing keys or indexes."""
    current = value
    cursor = 0
    while cursor < len(path):
        if path[cursor] == ".":
            cursor += 1
            continue
        if path[cursor] == "[":
            closing = path.find("]", cursor)
            if closing < 0 or not path[cursor + 1 : closing].isdigit() or not isinstance(current, list):
                raise KeyError(path)
            current = current[int(path[cursor + 1 : closing])]
            cursor = closing + 1
            continue
        end = cursor
        while end < len(path) and path[end] not in ".[":
            end += 1
        key = path[cursor:end]
        if not key or not isinstance(current, Mapping) or key not in current:
            raise KeyError(path)
        current = current[key]
        cursor = end
    return current


def append_jsonl(path: str, value: Any) -> None:
    """Append one durable record; never truncate an existing research log."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _APPEND_LOCK, destination.open("a", encoding="utf-8") as stream:
        stream.write(json_line(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def ensure_appendable(path: str) -> None:
    """Fail before a paid call if its receipt cannot be appended."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8"):
        pass
