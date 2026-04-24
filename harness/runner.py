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

from harness import ui
from harness.config import HarnessConfigError, load_config, require_pyproject

# Re-exported for historical callers (e.g. tasks/stats.py).
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"
VERBOSE = "--verbose" in sys.argv

# Commands that must work without a project — diagnostics, scaffolding, meta.
PREFLIGHT_EXEMPT: frozenset[str] = frozenset({"doctor", "init", "presets", "version", "help"})

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
    """Emit a stage or sub-stage header."""
    ui.section(name)


def ok(message: str) -> None:
    """Emit a success line for a free-form message."""
    print(f"  {_glyph('✓', GREEN)} {message}")


def fail(message: str) -> None:
    """Emit a failure line without exiting (advisory gates)."""
    print(f"  {_glyph('✗', RED)} {message}")


def warn_skip(message: str) -> None:
    """Emit a 'skipped' status line for optional/absent gates."""
    print(f"  {_glyph('⚠', YELLOW)} {message}")


def fail_skip(message: str) -> NoReturn:
    """Emit a red ✗ and exit 1 for a required-but-missing gate."""
    print(f"  {_glyph('✗', RED)} {message}")
    sys.exit(1)


def arg_value(flag: str, default: str) -> str:
    """Return the value of ``--flag=value`` in sys.argv, else ``default``."""
    return next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith(flag)), default)


def preflight(command: str) -> None:
    """Fail fast with exit code 2 when running a non-exempt command without a pyproject.

    ``find_project_root`` silently falls back to CWD when no ancestor has a
    ``pyproject.toml``; every downstream task would then operate against a bogus
    root. Gate execution here so users see one clear message instead of confusing
    tool-by-tool failures. ``doctor`` and ``init`` are exempt — they exist to
    diagnose and bootstrap broken setups.
    """
    if command in PREFLIGHT_EXEMPT:
        return
    try:
        require_pyproject(load_config())
    except HarnessConfigError as exc:
        print(f"harness: {exc}", file=sys.stderr)
        sys.exit(2)


@dataclass(frozen=True)
class Task:
    description: str
    cmd: list[str]
    pre_cmds: tuple[list[str], ...] = ()
    test_summary: bool = False
    # Widened by tools whose benign states use non-zero exit codes (e.g. pytest
    # returns 5 when it collects nothing).
    allowed_rcs: tuple[int, ...] = (0,)
    # Short bracketed tag for row display, e.g. `[fix]`. Falls back to the first
    # word of ``description`` lowercased.
    label: str | None = None
    # Compact command string shown in the row's middle column. Falls back to a
    # basename-stripped rendering of ``cmd``.
    display: str | None = None


@dataclass
class RunResult:
    task: Task
    returncode: int
    stdout: str
    stderr: str
    elapsed: float


def run(task: Task, *, no_exit: bool = False) -> None:
    """Run ``task`` silently; print a status row. Exit on failure unless ``no_exit``."""
    result = _execute(task)
    _print_status(result, elapsed_suffix=False)
    if result.returncode in task.allowed_rcs:
        return
    _dump_failure(result, titled=False)
    if not no_exit:
        sys.exit(result.returncode)


def run_tasks(tasks: list[Task]) -> None:
    """Run ``tasks`` in parallel; stream status rows in completion order.

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
    label = task.label or _default_label(task.description)
    command = task.display or _default_display(task.cmd)
    status, detail, state = _status(result, elapsed_suffix=elapsed_suffix)
    with _PRINT_LOCK:
        ui.row(label, command, status, detail=detail, state=state)


def _status(result: RunResult, *, elapsed_suffix: bool) -> tuple[str, str | None, ui.State]:
    task = result.task
    if result.returncode not in task.allowed_rcs:
        return ("failed", None, "fail")
    if task.test_summary:
        summary = _parse_test_summary(result.stdout + result.stderr)
        if summary:
            return (summary, None, "ok")
    if elapsed_suffix:
        return ("ok", f"{result.elapsed:.1f}s", "ok")
    return ("ok", None, "ok")


def _default_label(description: str) -> str:
    """First word of ``description`` lowercased (e.g. `Fix lint errors` → `fix`)."""
    head = description.split(" ", 1)[0]
    return head.lower().rstrip(":")


def _default_display(cmd: list[str]) -> str:
    """Compact one-line rendering of ``cmd``: basename + key flags, no absolute paths."""
    if not cmd:
        return ""
    head = Path(cmd[0]).name or cmd[0]
    python_names = {"python", "python3", Path(sys.executable).name}
    if head in python_names and len(cmd) >= 3 and cmd[1] == "-m":
        head = f"python -m {cmd[2]}"
        rest = cmd[3:]
    else:
        rest = cmd[1:]
    # Drop config-path flags that carry absolute paths — noise in the demo row.
    cleaned = [a for a in rest if not a.startswith(("--config=", "--project=", "--rcfile="))]
    # Collapse whitespace so inline scripts and embedded newlines don't tear the row.
    joined = " ".join([head, *cleaned]).strip()
    return re.sub(r"\s+", " ", joined)


def _dump_failure(result: RunResult, *, titled: bool) -> None:
    if VERBOSE:
        return  # already streamed while running
    task = result.task
    with _PRINT_LOCK:
        if titled:
            print(f"\n--- {task.description} output ---")
        print(f"{_c(RED)}Command failed: {' '.join(task.cmd)}{_c(RESET)}")
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")


def _parse_test_summary(output: str) -> str:
    """Extract a short test summary from unittest or pytest output."""
    m = _UNITTEST_SUMMARY.search(output)
    if m:
        return f"{m.group(1)} tests in {m.group(2)}"
    m = _PYTEST_SUMMARY.search(output)
    if m:
        return f"{m.group(1)} passed in {m.group(2)}s"
    return ""


def _glyph(char: str, color: str) -> str:
    """Color-wrap a single status glyph, honoring NO_COLOR / non-TTY."""
    if not ui.use_color():
        return char
    return f"{color}{char}{RESET}"


def _c(code: str) -> str:
    """ANSI code or empty string depending on color availability."""
    return code if ui.use_color() else ""
