"""Subprocess funnel + parallel executor. Stdlib-only."""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import IO, NoReturn

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"
VERBOSE = "--verbose" in sys.argv

_BIN = Path(sys.executable).parent

_UNITTEST_SUMMARY = re.compile(r"Ran (\d+) tests? in ([\d.]+s)")
_PYTEST_SUMMARY = re.compile(r"(\d+) passed[^\n]*?\s+in\s+([\d.]+)s")

_PRINT_LOCK = threading.Lock()


def tool(name: str, *args: str) -> list[str]:
    """Resolve a co-installed console script; fall back to PATH, then bare name."""
    local = _BIN / name
    if local.exists():
        return [str(local), *args]
    return [shutil.which(name) or name, *args]


def python_m(module: str, *args: str) -> list[str]:
    """Invoke a Python module using the CLI's own interpreter."""
    return [sys.executable, "-m", module, *args]


def capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` silently; return the CompletedProcess (never raises on non-zero rc).

    Subprocess kwargs here are pragma'd: ``check=False``/``None`` are equivalent,
    and ``capture_output``/``text`` flips are invisible to our tests. Mutation
    survivors on those kwargs would be fake-confidence noise, not real gaps.
    """
    # pragma: no mutate start
    return subprocess.run(cmd, capture_output=True, text=True, check=False)
    # pragma: no mutate end


def generate_coverage_xml() -> Path:
    """Regenerate coverage.xml from .coverage. Returns the path whether or not it exists."""
    capture(python_m("coverage", "xml", "-o", "coverage.xml", "-q"))
    return Path("coverage.xml")


def section(name: str) -> None:
    """Emit a blank-padded ``=== name ===`` stage header."""
    print(f"\n=== {name} ===\n")


def ok(message: str) -> None:
    """Emit a success line for a completed action."""
    print(f"  {GREEN}✓{RESET} {message}")


def fail(message: str) -> None:
    """Emit a failure line without exiting (advisory gates)."""
    print(f"  {RED}✗{RESET} {message}")


def warn_skip(message: str) -> None:
    """Emit a 'skipped' status line for optional/absent gates."""
    print(f"  {GREEN}⚠{RESET} {message}")


def fail_skip(message: str) -> NoReturn:
    """Emit a red ✗ and exit 1 for a required-but-missing gate."""
    print(f"  {RED}✗{RESET} {message}")
    sys.exit(1)


def arg_value(flag: str, default: str) -> str:
    """Return the value of ``--flag=value`` in sys.argv, else ``default``."""
    return next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith(flag)), default)


@dataclass(frozen=True)
class Task:
    description: str
    cmd: list[str]
    pre_cmds: tuple[list[str], ...] = ()
    test_summary: bool = False
    # Widened by tools whose benign states use non-zero exit codes (e.g. pytest
    # returns 5 when it collects nothing).
    allowed_rcs: tuple[int, ...] = (0,)


@dataclass
class RunResult:
    task: Task
    returncode: int
    stdout: str
    stderr: str
    elapsed: float


def run(task: Task, *, no_exit: bool = False) -> None:
    """Run ``task`` silently; print ✓/✗. Exit on failure unless ``no_exit``."""
    result = _execute(task)
    _print_status(result, elapsed_suffix=False)
    if result.returncode in task.allowed_rcs:
        return
    _dump_failure(result, titled=False)
    if not no_exit:
        sys.exit(result.returncode)


def run_tasks(tasks: list[Task]) -> None:
    """Run ``tasks`` in parallel; stream ✓/✗ in completion order.

    All tasks run to completion. On any failure, captured output is dumped
    after the status block, and we ``sys.exit`` with the *first-in-task-list*
    failure's returncode (deterministic; matches sequential semantics).
    """
    if not tasks:
        return
    results: list[RunResult | None] = [None] * len(tasks)
    max_workers = min(len(tasks), (os.cpu_count() or 4) * 2)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_execute, t): idx for idx, t in enumerate(tasks)}
        for fut in as_completed(futures):
            result = fut.result()
            results[futures[fut]] = result
            _print_status(result, elapsed_suffix=True)
    failures = [r for r in results if r is not None and r.returncode not in r.task.allowed_rcs]
    for failed in failures:
        _dump_failure(failed, titled=True)
    if failures:
        sys.exit(failures[0].returncode)


def _execute(task: Task) -> RunResult:
    """Run each command in ``task``, stopping at the first non-zero."""
    start = time.monotonic()
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    rc = 0
    for cmd in (*task.pre_cmds, task.cmd):
        rc, out, err = _run_one(cmd, task.description)
        stdout_parts.append(out)
        stderr_parts.append(err)
        if rc != 0:
            break
    return RunResult(
        task, rc, "".join(stdout_parts), "".join(stderr_parts), time.monotonic() - start
    )


def _run_one(cmd: list[str], tag: str) -> tuple[int, str, str]:
    if VERBOSE:
        return _run_one_streamed(cmd, tag)
    result = capture(cmd)
    return result.returncode, result.stdout, result.stderr


def _run_one_streamed(cmd: list[str], tag: str) -> tuple[int, str, str]:
    with _PRINT_LOCK:
        print(f"  -> [{tag}] {' '.join(cmd)}")
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    ) as proc:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        threads = [
            threading.Thread(target=_pump, args=(proc.stdout, tag, out_buf), daemon=True),
            threading.Thread(target=_pump, args=(proc.stderr, tag, err_buf), daemon=True),
        ]
        for t in threads:
            t.start()
        rc = proc.wait()
        for t in threads:
            t.join()
        return rc, out_buf.getvalue(), err_buf.getvalue()


def _pump(stream: IO[str] | None, tag: str, sink: io.StringIO) -> None:
    if stream is None:
        return
    for line in iter(stream.readline, ""):
        with _PRINT_LOCK:
            sys.stdout.write(f"[{tag}] {line}")
            sys.stdout.flush()
        sink.write(line)


def _print_status(result: RunResult, *, elapsed_suffix: bool) -> None:
    task = result.task
    succeeded = result.returncode in task.allowed_rcs
    suffix = ""
    if succeeded and task.test_summary:
        suffix = _parse_test_summary(result.stdout + result.stderr)
    if not suffix and elapsed_suffix:
        suffix = f" ({result.elapsed:.1f}s)"
    message = f"{task.description}{suffix}"
    with _PRINT_LOCK:
        (ok if succeeded else fail)(message)


def _dump_failure(result: RunResult, *, titled: bool) -> None:
    if VERBOSE:
        return  # already streamed while running
    task = result.task
    with _PRINT_LOCK:
        if titled:
            print(f"\n--- {task.description} output ---")
        print(f"{RED}Command failed: {' '.join(task.cmd)}{RESET}")
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")


def _parse_test_summary(output: str) -> str:
    """Extract '(N tests, X.Xs)' from unittest or pytest output."""
    m = _UNITTEST_SUMMARY.search(output)
    if m:
        return f" ({m.group(1)} tests, {m.group(2)})"
    m = _PYTEST_SUMMARY.search(output)
    if m:
        return f" ({m.group(1)} tests, {m.group(2)}s)"
    return ""
