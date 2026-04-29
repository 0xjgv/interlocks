"""Mutation testing via mutmut."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING

from interlocks import ui
from interlocks.config import InterlockConfig, find_project_root, load_config
from interlocks.git import changed_py_files_vs
from interlocks.metrics import MutationSummary, coverage_line_rate, read_mutation_summary
from interlocks.runner import (
    _PRINT_LOCK,
    VERBOSE,
    arg_value,
    fail,
    ok,
    python_m,
    warn_skip,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass
class _PulseState:
    """Shared state between the reader and pulse threads.

    `active` and `max_width` are both read by the reader's `on_line` (to clear
    the in-place pulse line before printing a keep-line). Mutations to
    `max_width` happen under `_PRINT_LOCK` so the reader can't observe a stale
    width mid-update.
    """

    active: bool = False
    max_width: int = 0


_BRAILLE_SPINNER = frozenset("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠟⠯⠷⠾⠽⠻")

# Watchdog tick when refreshing in-place progress lines.
_PULSE_SECONDS = 2.0


def _mutant_in_changed(mutant_key: str, changed: set[str]) -> bool:
    """Mutant keys look like `interlocks.foo.x_bar__mutmut_1`; match vs `interlocks/foo.py`.

    The trailing dot-component is the mutmut-mangled function name (``x_<name>``),
    which isn't part of the module file path — strip it before resolving.
    """
    head = mutant_key.split("__mutmut_", 1)[0]
    module = head.rsplit(".", 1)[0]
    rel = module.replace(".", "/") + ".py"
    return any(c == rel or c.endswith("/" + rel) for c in changed)


def _dir_prefix(d: str) -> str:
    """Project-relative dir → ``"d/"`` slash-prefix; root layout (``""``/``"."``) → ``""``."""
    return "" if d in ("", ".") else f"{d}/"


def _changed_to_globs(changed: set[str], src_dir: str, test_dir: str) -> list[str]:
    """`{"interlocks/tasks/foo.py"}` + `src_dir="interlocks"` -> `["interlocks.tasks.foo.*"]`.

    Filters out paths under ``test_dir`` and (when set) outside ``src_dir`` so test
    files don't leak into mutmut. Root layouts (``src_dir`` ``""``/``"."``) admit
    any ``*.py`` outside the test tree. Each glob matches mutmut keys like
    ``<module>.x_<func>__mutmut_<n>`` via fnmatch.
    """
    src_prefix = _dir_prefix(src_dir)
    test_prefix = _dir_prefix(test_dir)
    out: list[str] = []
    for path in sorted(changed):
        if not path.endswith(".py"):
            continue
        if test_prefix and path.startswith(test_prefix):
            continue
        if src_prefix and not path.startswith(src_prefix):
            continue
        module = path[:-3].replace("/", ".")
        out.append(f"{module}.*")
    return out


def _is_spinner_line(line: str) -> bool:
    s = line.lstrip()
    return bool(s) and s[0] in _BRAILLE_SPINNER


def _is_progress_line(line: str) -> bool:
    """`113/4895  🎉 0 🫥 113` style — running totals from mutmut."""
    s = line.strip()
    return "/" in s and ("🎉" in s or "🫥" in s)


def _is_keep_line(line: str) -> bool:
    """Lines worth surfacing in default (non-verbose) mode."""
    s = line.strip().lower()
    return "mutations/second" in s or s.startswith("done")


def _drain(stream: IO[str], on_line: Callable[[str], None]) -> None:
    for line in stream:
        on_line(line)


def _ensure_log_path() -> Path:
    log_dir = find_project_root() / ".interlocks"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "mutation.log"


def _make_pulse_thread(
    get_progress: Callable[[], str | None],
    stop_event: threading.Event,
    state: _PulseState,
) -> threading.Thread | None:
    """Daemon thread that refreshes the in-place progress line every `_PULSE_SECONDS`.

    Returns ``None`` when pulses are disabled (verbose/quiet/non-tty already
    decided by the caller via `state.active`). The thread mutates
    ``state.max_width`` and the on-screen line under ``_PRINT_LOCK`` so the
    reader thread can clear the line atomically before printing keep-lines.
    """
    if not state.active:
        return None

    last_emitted: str | None = None

    def _pulse() -> None:
        nonlocal last_emitted
        while not stop_event.wait(_PULSE_SECONDS):
            current = get_progress()
            if current is None or current == last_emitted:
                continue
            text = f"  {current}"
            with _PRINT_LOCK:
                state.max_width = max(state.max_width, len(text))
                sys.stdout.write(f"\r{text}")
                sys.stdout.flush()
            last_emitted = current

    return threading.Thread(target=_pulse, daemon=True)


def _finalize_progress(last_progress: str | None, max_width: int) -> None:
    """Clear any in-place pulse line and emit the final progress newline."""
    if max_width:
        with _PRINT_LOCK:
            sys.stdout.write("\r" + " " * max_width + "\r")
            sys.stdout.flush()
    if last_progress is not None:
        sys.stdout.write(f"  {last_progress}\n")


def _wait_for_proc(proc: subprocess.Popen[str], timeout: int) -> bool:
    """Wait for `proc`; SIGTERM (then SIGKILL) on timeout. Returns completion flag."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return False
    return True


def _run_mutmut(mutmut: list[str], timeout: int) -> tuple[bool, Path]:
    """Run mutmut, SIGTERM after `timeout`. Capture+filter output.

    ``mutmut`` is the full argv (callers supply ``run`` and any module globs in
    the correct order — mutmut requires ``run`` BEFORE positional globs).
    Full mutmut stream is mirrored to ``.interlocks/mutation.log`` so noisy lines
    (spinner ticks, fork ``DeprecationWarning``) can be hidden by default while
    remaining recoverable on failure. ``--verbose`` passes through unfiltered;
    ``--quiet`` prints nothing here (the ok/fail row carries the verdict).
    """
    log_path = _ensure_log_path()
    quiet = ui.is_quiet()
    env = {**os.environ, "PYTHONWARNINGS": "ignore::DeprecationWarning"}

    last_progress: str | None = None
    pulse = _PulseState(active=not VERBOSE and not quiet and sys.stdout.isatty())

    def on_line(line: str) -> None:
        nonlocal last_progress
        log.write(line)
        if quiet:
            return
        if VERBOSE:
            sys.stdout.write(line)
            return
        stripped = line.rstrip("\r\n")
        if _is_spinner_line(stripped):
            return
        if _is_progress_line(stripped):
            last_progress = stripped
            return
        if _is_keep_line(stripped):
            with _PRINT_LOCK:
                if pulse.max_width:
                    sys.stdout.write("\r" + " " * pulse.max_width + "\r")
                sys.stdout.write(line)
                sys.stdout.flush()

    pulse_stop = threading.Event()
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            mutmut,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        if proc.stdout is None:
            raise RuntimeError("subprocess stdout pipe missing")
        reader = threading.Thread(target=_drain, args=(proc.stdout, on_line), daemon=True)
        reader.start()
        pulse_thread = _make_pulse_thread(lambda: last_progress, pulse_stop, pulse)
        if pulse_thread is not None:
            pulse_thread.start()
        try:
            completed = _wait_for_proc(proc, timeout)
            # Close stdout to unblock the reader, then drain it before the log file
            # exits scope — otherwise late writes hit a closed file.
            proc.stdout.close()
            reader.join(timeout=5)
        finally:
            pulse_stop.set()
            if pulse_thread is not None:
                pulse_thread.join(timeout=1)
        if not quiet and not VERBOSE:
            _finalize_progress(last_progress, pulse.max_width)
    return completed, log_path


def _print_survivors(survived: list[str], changed: set[str] | None) -> None:
    if ui.is_quiet():
        return
    shown = [s for s in survived if changed is None or _mutant_in_changed(s, changed)][:20]
    if not shown:
        return
    print(f"    surviving mutants ({len(shown)} shown):")
    for key in shown:
        print(f"      {key}")


def _resolve_min_score(cfg: InterlockConfig, *, default: float | None = None) -> float | None:
    """CLI ``--min-score=`` wins; else ``default`` (caller-supplied);
    else ``cfg.mutation_min_score`` when enforcing; else None."""
    min_score_arg = arg_value("--min-score=", "")
    if min_score_arg:
        return float(min_score_arg)
    if default is not None:
        return default
    if cfg.enforce_mutation:
        return cfg.mutation_min_score
    return None


def _report_mutation(
    summary: MutationSummary,
    min_score: float | None,
    *,
    completed: bool,
    changed: set[str] | None,
    log_path: Path,
) -> bool:
    """Print ok/fail row + survivors. Return True when the gate failed."""
    total = summary.killed + summary.survived + summary.timeout
    failed = min_score is not None and summary.score < min_score
    partial = "" if completed else " (partial — timeout)"
    if failed:
        fail(f"Mutation: score {summary.score:.1f}% below threshold {min_score:.1f}%{partial}")
        if ui.is_quiet():
            print(f"  log: {log_path}")
    else:
        ok(f"Mutation: score {summary.score:.1f}% (killed {summary.killed}/{total}){partial}")
    _print_survivors(summary.survivors, changed)
    return failed


def _resolve_changed_globs(
    cfg: InterlockConfig, *, changed_only: bool
) -> tuple[list[str] | None, set[str] | None]:
    """Translate ``--changed-only`` into module globs + the underlying changed set.

    Returns ``(globs, changed)``:
      - ``(None, None)`` when full-run mode (no incremental scoping).
      - ``([], changed)`` when incremental mode but no src files changed (caller
        warn-skips).
      - ``([glob, ...], changed)`` for the normal incremental path.
    """
    if not changed_only:
        return None, None
    changed = changed_py_files_vs(cfg.mutation_since_ref)
    globs = _changed_to_globs(changed, cfg.src_dir_arg, cfg.test_dir_arg)
    return globs, changed


def cmd_mutation(
    *, changed_only: bool | None = None, min_score_default: float | None = None
) -> None:
    """Mutation score via mutmut (reads ``[tool.mutmut]``).

    CLI flags ``--min-coverage=`` / ``--max-runtime=`` / ``--min-score=`` win;
    otherwise thresholds come from ``cfg.mutation_min_coverage`` /
    ``cfg.mutation_max_runtime`` / ``cfg.mutation_min_score`` (defaults
    70.0 / 600 / 80.0, overridable via ``[tool.interlocks]``). Advisory by default;
    set ``enforce_mutation = true`` to exit 1 when score < ``mutation_min_score``.

    Stages call programmatically: ``changed_only`` overrides ``--changed-only`` argv
    sniffing; ``min_score_default`` supplies a fallback threshold when no
    ``--min-score=`` flag is present (CLI flag still wins).
    """
    cfg = load_config()
    min_cov = float(arg_value("--min-coverage=", str(cfg.mutation_min_coverage)))
    rate = coverage_line_rate()
    if rate is None:
        warn_skip("mutation: no coverage data — run `interlocks coverage` first")
        return
    pct = rate * 100
    if pct < min_cov:
        warn_skip(f"mutation: suite coverage {pct:.1f}% < {min_cov}%")
        return

    timeout = int(arg_value("--max-runtime=", str(cfg.mutation_max_runtime)))
    min_score = _resolve_min_score(cfg, default=min_score_default)
    changed_flag = changed_only if changed_only is not None else "--changed-only" in sys.argv
    globs, changed = _resolve_changed_globs(cfg, changed_only=changed_flag)
    if globs == []:
        warn_skip(f"mutation: no changed src files vs {cfg.mutation_since_ref}")
        return
    if globs and not ui.is_quiet():
        print(f"  mutating {len(globs)} module(s) changed vs {cfg.mutation_since_ref}")

    completed, log_path = _run_mutmut([*python_m("mutmut"), "run", *(globs or [])], timeout)

    summary = read_mutation_summary()
    if summary is None:
        warn_skip("mutation: .mutmut-cache/ missing after run")
        return

    if _report_mutation(
        summary, min_score, completed=completed, changed=changed, log_path=log_path
    ):
        sys.exit(1)
