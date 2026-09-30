"""Jevc process boundary for compiled question programs and reducers."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .io import InputError, fingerprint
from .sdk import normalize_request

_EXPECTED_VERSION = "0.1.0"
_SOURCE_JEVC = Path(__file__).resolve().parents[2] / "node_modules" / ".bin" / "jevc"
_RUNTIME = Path(__file__).with_name("jevc_runtime.mjs")


def _compiler_paths() -> tuple[Path, Path]:
    """Resolve the installed Jevc executable and its public module entrypoint."""
    on_path = shutil.which("jevc")
    executable = Path(on_path) if on_path is not None else _SOURCE_JEVC
    if not executable.is_file():
        raise InputError(
            "Jevc is not installed; install `jev-compiler@0.1.0` so `jevc` is on PATH, "
            "or run `npm install` in the Meta Builder checkout"
        )
    entrypoint = executable.resolve().parent / "index.js"
    if not entrypoint.is_file():
        raise InputError(f"cannot locate the Jevc module beside executable: {executable}")
    return executable, entrypoint


def _run(command: list[str], payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        raise InputError(f"cannot run Jevc: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise InputError(f"Jevc rejected the program: {detail}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise InputError("Jevc returned invalid JSON") from error
    if not isinstance(result, dict):
        raise InputError("Jevc returned a non-object result")
    return result


def compiler_version() -> str:
    """Return the concrete locally pinned Jevc version."""
    executable, _ = _compiler_paths()
    try:
        completed = subprocess.run([str(executable), "--version"], capture_output=True, check=False, text=True)
    except OSError as error:
        raise InputError(f"cannot run Jevc: {error}") from error
    if completed.returncode != 0 or not completed.stdout.strip():
        raise InputError(f"cannot read Jevc version: {completed.stderr.strip() or completed.returncode}")
    installed = completed.stdout.strip()
    if installed != _EXPECTED_VERSION:
        raise InputError(f"Jevc {_EXPECTED_VERSION} is required, found {installed}")
    return installed


def compile_program(
    program: Mapping[str, Any], state: Any, model: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile with the real Jevc CLI, then validate its request with the Python SDK."""
    executable, _ = _compiler_paths()
    version = compiler_version()
    request = _run([str(executable), "compile", "-", "--emit", "json"], program)
    if request.get("state") != "<state>":
        raise InputError("Jevc JSON output did not contain its compile-time state placeholder")
    request["state"] = state
    submitted, _ = normalize_request({"request": request}, model)
    return submitted, {
        "package": "jev-compiler",
        "version": version,
        "source": f"npm:jev-compiler@{_EXPECTED_VERSION}",
        "program_sha256": fingerprint(program),
    }


def reduce_program(program: Mapping[str, Any], answers: Mapping[str, Any]) -> str:
    """Run the compiled reducer from Jevc rather than reimplementing it in Python."""
    _, entrypoint = _compiler_paths()
    result = _run(["node", str(_RUNTIME), str(entrypoint)], {"program": program, "answers": answers})
    verdict = result.get("verdict")
    if not isinstance(verdict, str) or not verdict:
        raise InputError("Jevc reducer returned no verdict")
    return verdict
