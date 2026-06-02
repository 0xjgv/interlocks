"""Mutation testing via mutmut."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, NoReturn

from interlocks import run_summary, ui
from interlocks.config import InterlockConfig, find_project_root, load_config
from interlocks.git import changed_py_files_vs
from interlocks.metrics import (
    MUTATION_EVIDENCE,
    MutationSummary,
    coverage_line_rate,
    read_mutation_summary,
)
from interlocks.runner import (
    _PRINT_LOCK,
    VERBOSE,
    arg_value,
    fail,
    ok,
    uv_run_with,
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


@dataclass(frozen=True)
class _MutationRun:
    min_coverage: float
    coverage_pct: float
    timeout: int
    min_score: float | None
    changed_only: bool
    globs: list[str] | None
    changed: set[str] | None


@dataclass(frozen=True)
class _MutationPayloadContext:
    min_score: float | None
    completed: bool
    changed_only: bool
    globs: list[str] | None
    changed: set[str] | None
    log_path: Path
    elapsed: float
    max_runtime: int
    min_coverage: float
    coverage_pct: float
    total_mutants: int | None


@dataclass(frozen=True)
class _MutationExecution:
    completed: bool
    log_path: Path
    start: float
    total_mutants: int | None


@dataclass(frozen=True)
class _NoResultsContext:
    start: float
    json_mode: bool
    run_config: _MutationRun
    completed: bool
    progress: _MutationProgress | None


@dataclass(frozen=True)
class _MutationProgress:
    checked: int
    total: int


@dataclass
class _JsonProgress:
    last_emit: float = 0.0


_BRAILLE_SPINNER = frozenset("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠟⠯⠷⠾⠽⠻")
_MUTATION_FRACTION = re.compile(r"\b(?P<checked>\d+)/(?P<total>\d+)\b")

# Watchdog tick when refreshing in-place progress lines.
_PULSE_SECONDS = 2.0
_JSON_PROGRESS_SECONDS = 30.0
_READER_JOIN_SECONDS = 5.0
_MUTATION_SURVIVOR_LIMIT = 20
_MUTATION_TARGET_LIMIT = 20


def _mutant_in_changed(mutant_key: str, changed: set[str]) -> bool:
    """Mutant keys look like `interlocks.foo.x_bar__mutmut_1`; match vs `interlocks/foo.py`.

    The trailing dot-component is the mutmut-mangled function name (``x_<name>``),
    which isn't part of the module file path — strip it before resolving.
    """
    head = mutant_key.split("__mutmut_", 1)[0]
    rel = head.rsplit(".", 1)[0].replace(".", "/") + ".py"
    suffix = f"/{rel}"
    return rel in changed or any(c.endswith(suffix) for c in changed)


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


def _mutation_progress_label(line: str) -> str | None:
    """Compact mutmut progress label safe for JSON-mode stderr."""
    stripped = line.strip()
    progress = _mutation_progress_from_line(stripped)
    if progress is not None:
        return f"mutmut {progress.checked}/{progress.total}"
    if _is_spinner_line(stripped):
        label = stripped[1:].strip()
        if label.lower().startswith("running "):
            label = label[8:].strip()
        return label.lower() or "mutmut"
    return None


def _print_json_progress(label: str, progress: _JsonProgress, *, now: float | None = None) -> None:
    if not ui.is_json():
        return
    current = time.monotonic() if now is None else now
    if progress.last_emit and current - progress.last_emit < _JSON_PROGRESS_SECONDS:
        return
    with _PRINT_LOCK:
        print(f"interlocks: [mutation] {label} running", file=sys.stderr)
        sys.stderr.flush()
    progress.last_emit = current


def _mutation_progress_from_line(line: str) -> _MutationProgress | None:
    match = _MUTATION_FRACTION.search(line)
    if match is None:
        return None
    return _MutationProgress(checked=int(match["checked"]), total=int(match["total"]))


def _mutation_progress_from_log(log_path: Path) -> _MutationProgress | None:
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    progress: _MutationProgress | None = None
    for line in lines:
        parsed = _mutation_progress_from_line(line)
        if parsed is not None:
            progress = parsed
    return progress


def _completion_pct(checked: int, total: int | None) -> float | None:
    if total is None or total <= 0:
        return None
    return min(checked / total * 100, 100.0)


def _estimated_full_runtime(elapsed: float, checked: int, total: int | None) -> float | None:
    if total is None or total <= checked or checked <= 0:
        return None
    return elapsed * total / checked


def _drain(stream: IO[str], on_line: Callable[[str], None]) -> None:
    try:
        for line in stream:
            on_line(line)
    except ValueError:
        return


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


def _erase_pulse_line(max_width: int) -> None:
    """CR-pad-CR to wipe the pulse line; no-op if ``max_width == 0``.

    Caller holds ``_PRINT_LOCK``.
    """
    if max_width:
        sys.stdout.write("\r" + " " * max_width + "\r")


def _finalize_progress(last_progress: str | None, max_width: int) -> None:
    """Clear any in-place pulse line and emit the final progress newline."""
    if max_width:
        with _PRINT_LOCK:
            _erase_pulse_line(max_width)
            sys.stdout.flush()
    if last_progress is not None:
        sys.stdout.write(f"  {last_progress}\n")


def _wait_for_proc(proc: subprocess.Popen[str], timeout: int) -> bool:
    """Wait for `proc`; SIGINT, SIGTERM, then SIGKILL on timeout. Returns completion flag."""
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        return False
    return True


def _close_reader(
    reader: threading.Thread,
    stream: IO[str],
    drain_stop: threading.Event,
) -> None:
    reader.join(timeout=_READER_JOIN_SECONDS)
    alive = reader.is_alive()
    if alive:
        drain_stop.set()
    stream.close()
    if alive:
        reader.join(timeout=_READER_JOIN_SECONDS)


def _run_mutmut(mutmut: list[str], timeout: int) -> tuple[bool, Path]:
    """Run mutmut, SIGINT after `timeout`. Capture+filter output.

    ``mutmut`` is the full argv (callers supply ``run`` and any module globs in
    the correct order — mutmut requires ``run`` BEFORE positional globs).
    Full mutmut stream is mirrored to ``.interlocks/mutation.log`` so noisy lines
    (spinner ticks, fork ``DeprecationWarning``) can be hidden by default while
    remaining recoverable on failure. ``--verbose`` passes through unfiltered;
    minimal-default mode prints nothing here (the ok/fail row carries the verdict).
    """
    log_path = _ensure_log_path()
    quiet = not ui.is_verbose()
    env = {**os.environ, "PYTHONWARNINGS": "ignore::DeprecationWarning"}

    last_progress: str | None = None
    pulse = _PulseState(active=not VERBOSE and not quiet and sys.stdout.isatty())
    json_progress = _JsonProgress()
    drain_stop = threading.Event()

    def on_line(line: str) -> None:
        nonlocal last_progress
        if drain_stop.is_set():
            return
        log.write(line)
        stripped = line.rstrip("\r\n")
        label = _mutation_progress_label(stripped)
        if label is not None:
            _print_json_progress(label, json_progress)
        if quiet:
            return
        if VERBOSE:
            sys.stdout.write(line)
            return
        if _is_spinner_line(stripped):
            return
        if _is_progress_line(stripped):
            last_progress = stripped
            return
        if _is_keep_line(stripped):
            with _PRINT_LOCK:
                _erase_pulse_line(pulse.max_width)
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
            # Wait for the reader to observe EOF from the exited process before
            # closing the pipe. Closing while another thread iterates the stream
            # can raise ValueError even after a successful mutmut run.
            _close_reader(reader, proc.stdout, drain_stop)
        finally:
            pulse_stop.set()
            if pulse_thread is not None:
                pulse_thread.join(timeout=1)
        if not quiet and not VERBOSE:
            _finalize_progress(last_progress, pulse.max_width)
    return completed, log_path


def _print_survivors(survived: list[str], changed: set[str] | None) -> None:
    if not ui.is_verbose():
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
    failed = _mutation_failed(summary, min_score, completed=completed)
    partial = "" if completed else " (partial — timeout)"
    if failed:
        if not completed:
            fail(
                "Mutation: timed out before all mutants were checked; "
                f"checked score {summary.score:.1f}% is partial"
            )
        else:
            fail(f"Mutation: score {summary.score:.1f}% below threshold {min_score:.1f}%")
        if not ui.is_verbose():
            print(f"  log: {log_path}")
    else:
        message = (
            f"Mutation: score {summary.score:.1f}% (killed {summary.killed}/{total}){partial}"
        )
        if ui.is_verbose():
            ok(message)
        elif not ui.is_json():
            print(f"  {message}")
    run_summary.record_mutation(summary.score)
    _print_survivors(summary.survivors, changed)
    return failed


def _mutation_score_failed(summary: MutationSummary, min_score: float | None) -> bool:
    return min_score is not None and summary.score < min_score


def _mutation_failed(
    summary: MutationSummary, min_score: float | None, *, completed: bool = True
) -> bool:
    return min_score is not None and (not completed or _mutation_score_failed(summary, min_score))


def _mutation_status(summary: MutationSummary, min_score: float | None, *, completed: bool) -> str:
    if not completed:
        return "partial"
    if _mutation_score_failed(summary, min_score):
        return "failed"
    return "ok"


def _mutation_survivors(summary: MutationSummary, changed: set[str] | None) -> list[str]:
    return [
        key for key in summary.survivors if changed is None or _mutant_in_changed(key, changed)
    ]


def _checked_mutants(summary: MutationSummary) -> int:
    return summary.killed + summary.survived + summary.timeout


def _mutation_progress_fields(
    checked: int,
    total_mutants: int | None,
    *,
    elapsed: float | None = None,
    completed: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    completion = _completion_pct(checked, total_mutants)
    estimate = (
        _estimated_full_runtime(elapsed, checked, total_mutants) if elapsed is not None else None
    )
    if total_mutants is not None:
        payload["total_mutants"] = total_mutants
    if completion is not None:
        payload["completion_pct"] = round(completion, 3)
    if not completed and estimate is not None:
        payload["estimated_full_runtime_seconds"] = round(estimate, 3)
    return payload


def _mutation_total_from_progress(
    run_config: _MutationRun,
    progress: _MutationProgress | None,
) -> int | None:
    if run_config.globs:
        return None
    return progress.total if progress is not None else None


def _survivor_truncation_field(survivor_count: int, visible_count: int) -> dict[str, object]:
    truncated = survivor_count - visible_count
    return {"truncated_survivors": truncated} if truncated > 0 else {}


def _mutation_target_fields(globs: list[str] | None) -> dict[str, object]:
    targets = list(globs or [])
    visible = targets[:_MUTATION_TARGET_LIMIT]
    payload: dict[str, object] = {
        "targets": visible,
        "target_count": len(targets),
    }
    truncated = len(targets) - len(visible)
    if truncated > 0:
        payload["truncated_targets"] = truncated
    return payload


def _mutation_result_message_fields(
    summary: MutationSummary,
    context: _MutationPayloadContext,
    *,
    failed: bool,
    score_failed: bool,
) -> dict[str, object]:
    if failed and not context.completed:
        return {
            "error": (
                "Mutation run timed out before all mutants were checked; "
                f"checked score {summary.score:.1f}% is partial"
            )
        }
    if score_failed:
        message = f"Mutation score {summary.score:.1f}% below threshold {context.min_score:.1f}%"
        return {"error": message}
    if not context.completed:
        return {"warning": "mutation run timed out before all mutants were checked"}
    return {}


def _mutation_payload(
    summary: MutationSummary,
    context: _MutationPayloadContext,
) -> dict[str, object]:
    survivors = _mutation_survivors(summary, context.changed)
    visible_survivors = survivors[:_MUTATION_SURVIVOR_LIMIT]
    failed = _mutation_failed(summary, context.min_score, completed=context.completed)
    score_failed = _mutation_score_failed(summary, context.min_score)
    total = _checked_mutants(summary)
    payload: dict[str, object] = {
        "command": "mutation",
        "passed": not failed,
        "status": _mutation_status(summary, context.min_score, completed=context.completed),
        "elapsed_seconds": round(context.elapsed, 3),
        "mode": "changed-only" if context.changed_only else "full",
        "completed": context.completed,
        "checked_mutants": total,
        "score": round(summary.score, 3),
        "killed": summary.killed,
        "survived": summary.survived,
        "timeout": summary.timeout,
        "min_score": context.min_score,
        "min_coverage": context.min_coverage,
        "coverage_pct": round(context.coverage_pct, 3),
        "max_runtime": context.max_runtime,
        "log_path": str(context.log_path),
        "survivors": visible_survivors,
    }
    payload.update(_mutation_target_fields(context.globs))
    payload.update(
        _mutation_progress_fields(
            total,
            context.total_mutants,
            elapsed=context.elapsed,
            completed=context.completed,
        )
    )
    payload.update(_survivor_truncation_field(len(survivors), len(visible_survivors)))
    payload.update(
        _mutation_result_message_fields(
            summary,
            context,
            failed=failed,
            score_failed=score_failed,
        )
    )
    return payload


def _mutation_skip_payload(
    *,
    reason: str,
    elapsed: float,
    next_action: str,
    min_coverage: float | None = None,
    coverage_pct: float | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "command": "mutation",
        "passed": True,
        "status": "skipped",
        "elapsed_seconds": round(elapsed, 3),
        "reason": reason,
        "next_action": next_action,
    }
    if min_coverage is not None:
        payload["min_coverage"] = min_coverage
    if coverage_pct is not None:
        payload["coverage_pct"] = round(coverage_pct, 3)
    return payload


def _emit_mutation_skip_json(
    *,
    reason: str,
    start: float,
    next_action: str,
    min_coverage: float | None = None,
    coverage_pct: float | None = None,
) -> None:
    ui.print_json(
        _mutation_skip_payload(
            reason=reason,
            elapsed=time.monotonic() - start,
            next_action=next_action,
            min_coverage=min_coverage,
            coverage_pct=coverage_pct,
        )
    )


def _write_mutation_evidence(
    summary: MutationSummary,
    *,
    run_config: _MutationRun,
    execution: _MutationExecution,
) -> None:
    """Mark cached mutmut stats as produced by ``interlocks gate mutation``."""
    project_root = find_project_root()
    evidence_path = project_root / MUTATION_EVIDENCE
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    total = _checked_mutants(summary)
    payload = {
        "command": "mutation",
        "completed": execution.completed,
        "mode": "changed-only" if run_config.changed_only else "full",
        "checked_mutants": total,
        "score": round(summary.score, 3),
        "log_path": str(execution.log_path),
        "generated_at": int(time.time()),
    }
    payload.update(_mutation_target_fields(run_config.globs))
    payload.update(_mutation_progress_fields(total, execution.total_mutants))
    evidence_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _write_mutation_no_results_evidence(
    run_config: _MutationRun,
    *,
    log_path: Path,
    progress: _MutationProgress | None,
) -> None:
    project_root = find_project_root()
    evidence_path = project_root / MUTATION_EVIDENCE
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    checked = progress.checked if progress is not None else 0
    total = _mutation_total_from_progress(run_config, progress)
    payload: dict[str, object] = {
        "command": "mutation",
        "completed": False,
        "mode": "changed-only" if run_config.changed_only else "full",
        "checked_mutants": checked,
        "no_results": True,
        "log_path": str(log_path),
        "generated_at": int(time.time()),
    }
    payload.update(_mutation_target_fields(run_config.globs))
    payload.update(_mutation_progress_fields(checked, total))
    evidence_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_changed_globs(
    cfg: InterlockConfig, *, changed_only: bool, since_ref: str | None = None
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
    changed = changed_py_files_vs(since_ref or cfg.mutation_since_ref)
    globs = _changed_to_globs(changed, cfg.src_dir_arg, cfg.test_dir_arg)
    return globs, changed


def _prepare_mutation_run(
    cfg: InterlockConfig,
    *,
    start: float,
    json_mode: bool,
    changed_only: bool | None,
    min_score_default: float | None,
) -> _MutationRun | None:
    min_cov = float(arg_value("--min-coverage=", str(cfg.mutation_min_coverage)))
    rate = coverage_line_rate()
    if rate is None:
        _skip_mutation_no_coverage(start=start, json_mode=json_mode, min_cov=min_cov)
        return None
    pct = rate * 100
    if pct < min_cov:
        _skip_mutation_low_coverage(
            start=start, json_mode=json_mode, min_cov=min_cov, coverage_pct=pct
        )
        return None

    timeout = int(arg_value("--max-runtime=", str(cfg.mutation_max_runtime)))
    min_score = _resolve_min_score(cfg, default=min_score_default)
    changed_flag = changed_only if changed_only is not None else "--changed-only" in sys.argv
    since_ref = arg_value("--since=", cfg.mutation_since_ref)
    globs, changed = _resolve_changed_globs(
        cfg,
        changed_only=changed_flag,
        since_ref=since_ref,
    )
    if globs == []:
        _skip_mutation_no_changed_src(
            since_ref,
            start=start,
            json_mode=json_mode,
            min_cov=min_cov,
            coverage_pct=pct,
        )
        return None
    if globs and ui.is_verbose() and not json_mode:
        print(f"  mutating {len(globs)} module(s) changed vs {since_ref}")
    return _MutationRun(
        min_coverage=min_cov,
        coverage_pct=pct,
        timeout=timeout,
        min_score=min_score,
        changed_only=changed_flag,
        globs=globs,
        changed=changed,
    )


def _skip_mutation_no_coverage(*, start: float, json_mode: bool, min_cov: float) -> None:
    if json_mode:
        _emit_mutation_skip_json(
            reason="no coverage data",
            start=start,
            next_action="Run `interlocks gate coverage` before `interlocks gate mutation`.",
            min_coverage=min_cov,
        )
        return
    warn_skip("Mutation: no coverage data — run `interlocks gate coverage` first")


def _skip_mutation_low_coverage(
    *, start: float, json_mode: bool, min_cov: float, coverage_pct: float
) -> None:
    if json_mode:
        _emit_mutation_skip_json(
            reason="coverage below mutation minimum",
            start=start,
            next_action="Add tests or lower `mutation_min_coverage`, then rerun mutation.",
            min_coverage=min_cov,
            coverage_pct=coverage_pct,
        )
        return
    warn_skip(f"Mutation: suite coverage {coverage_pct:.1f}% < {min_cov}%")


def _skip_mutation_no_changed_src(
    since_ref: str,
    *,
    start: float,
    json_mode: bool,
    min_cov: float,
    coverage_pct: float,
) -> None:
    reason = f"no changed src files vs {since_ref}"
    if json_mode:
        _emit_mutation_skip_json(
            reason=reason,
            start=start,
            next_action="Run `interlocks gate mutation` without `--changed-only` for a full run.",
            min_coverage=min_cov,
            coverage_pct=coverage_pct,
        )
        return
    warn_skip(f"Mutation: {reason}")


def _skip_mutation_no_results(
    log_path: Path,
    *,
    context: _NoResultsContext,
) -> None:
    failed = _mutation_no_results_failed(context.run_config, completed=context.completed)
    if not context.completed:
        _write_mutation_no_results_evidence(
            context.run_config,
            log_path=log_path,
            progress=context.progress,
        )
    if context.json_mode:
        payload = _mutation_no_results_payload(
            log_path,
            context=context,
        )
        ui.print_json(payload)
        if failed:
            sys.exit(1)
        return
    if failed:
        _fail_mutation_no_results(log_path, context=context)
    warn_skip(f"Mutation: {_mutation_no_results_reason(context)} — see {log_path}")


def _mutation_no_results_failed(run_config: _MutationRun, *, completed: bool) -> bool:
    return run_config.min_score is not None and not completed


def _mutation_no_results_payload(
    log_path: Path,
    *,
    context: _NoResultsContext,
) -> dict[str, object]:
    payload = _mutation_skip_payload(
        reason=_mutation_no_results_reason(context),
        elapsed=time.monotonic() - context.start,
        next_action=_mutation_no_results_next_action(log_path, context=context),
        min_coverage=context.run_config.min_coverage,
        coverage_pct=context.run_config.coverage_pct,
    )
    if _mutation_no_results_failed(context.run_config, completed=context.completed):
        payload.update({
            "passed": False,
            "status": "partial",
            "completed": False,
            "min_score": context.run_config.min_score,
            "max_runtime": context.run_config.timeout,
            "log_path": str(log_path),
            "error": _mutation_no_results_error(context),
        })
    if context.progress is not None:
        payload["checked_mutants"] = context.progress.checked
        payload.update(
            _mutation_progress_fields(
                context.progress.checked,
                _mutation_total_from_progress(context.run_config, context.progress),
                elapsed=time.monotonic() - context.start,
                completed=context.completed,
            )
        )
    return payload


def _mutation_no_results_reason(context: _NoResultsContext) -> str:
    if _mutation_progress_started(context.progress):
        return "mutmut summary unavailable after partial progress"
    return "no checked mutmut results"


def _mutation_no_results_next_action(log_path: Path, *, context: _NoResultsContext) -> str:
    if _mutation_progress_started(context.progress) and not context.completed:
        return (
            f"Inspect `{log_path}` for the last progress line and rerun "
            "`interlocks gate mutation` with a higher `--max-runtime=`."
        )
    return f"Inspect `{log_path}` and rerun `interlocks gate mutation`."


def _mutation_no_results_error(context: _NoResultsContext) -> str:
    progress = context.progress
    if progress is not None and progress.checked > 0:
        total = f"/{progress.total}"
        return (
            f"Mutation run timed out after progress reached {progress.checked}{total}, "
            "but mutmut results were unavailable"
        )
    return "Mutation run timed out before any mutants were checked"


def _mutation_progress_started(progress: _MutationProgress | None) -> bool:
    return progress is not None and progress.checked > 0


def _fail_mutation_no_results(log_path: Path, *, context: _NoResultsContext) -> NoReturn:
    fail(f"Mutation: {_mutation_no_results_error(context)}")
    print(f"  log: {log_path}")
    sys.exit(1)


def _run_mutation_command(
    cfg: InterlockConfig, run_config: _MutationRun, *, json_mode: bool
) -> tuple[bool, Path]:
    if json_mode:
        print("interlocks: [mutation] mutmut run running", file=sys.stderr)
    return _run_mutmut(
        uv_run_with(
            "interlocks-mutmut",
            "python",
            "-m",
            "mutmut",
            "run",
            *(run_config.globs or []),
            version=cfg.tool_version("interlocks-mutmut"),
        ),
        run_config.timeout,
    )


def _finish_mutation(
    summary: MutationSummary,
    run_config: _MutationRun,
    *,
    execution: _MutationExecution,
    json_mode: bool,
) -> None:
    _write_mutation_evidence(
        summary,
        run_config=run_config,
        execution=execution,
    )
    if json_mode:
        _emit_mutation_json(summary, run_config, execution)
        return
    if _report_mutation(
        summary,
        run_config.min_score,
        completed=execution.completed,
        changed=run_config.changed,
        log_path=execution.log_path,
    ):
        sys.exit(1)


def _emit_mutation_json(
    summary: MutationSummary,
    run_config: _MutationRun,
    execution: _MutationExecution,
) -> None:
    payload = _mutation_payload(
        summary,
        _MutationPayloadContext(
            min_score=run_config.min_score,
            completed=execution.completed,
            changed_only=run_config.changed_only,
            globs=run_config.globs,
            changed=run_config.changed,
            log_path=execution.log_path,
            elapsed=time.monotonic() - execution.start,
            max_runtime=run_config.timeout,
            min_coverage=run_config.min_coverage,
            coverage_pct=run_config.coverage_pct,
            total_mutants=execution.total_mutants,
        ),
    )
    ui.print_json(payload)
    if payload["passed"] is False:
        sys.exit(1)


def cmd_mutation(
    *, changed_only: bool | None = None, min_score_default: float | None = None
) -> None:
    """Mutation score via mutmut (reads ``[tool.mutmut]``).

    CLI flags ``--min-coverage=`` / ``--max-runtime=`` / ``--min-score=`` win;
    ``--since=`` overrides the ``--changed-only`` base ref. Otherwise thresholds
    come from ``cfg.mutation_min_coverage`` / ``cfg.mutation_max_runtime`` /
    ``cfg.mutation_min_score`` (defaults 70.0 / 600 / 80.0, overridable via
    ``[tool.interlocks]``). Advisory by default; enforced runs exit 1 when the
    score is low or the run times out before completion.

    Stages call programmatically: ``changed_only`` overrides ``--changed-only`` argv
    sniffing; ``min_score_default`` supplies a fallback threshold when no
    ``--min-score=`` flag is present (CLI flag still wins).
    """
    start = time.monotonic()
    cfg = load_config()
    json_mode = ui.is_json()
    run_config = _prepare_mutation_run(
        cfg,
        start=start,
        json_mode=json_mode,
        changed_only=changed_only,
        min_score_default=min_score_default,
    )
    if run_config is None:
        return

    completed, log_path = _run_mutation_command(cfg, run_config, json_mode=json_mode)
    progress = _mutation_progress_from_log(log_path)
    summary = read_mutation_summary(require_interlocks_evidence=False)
    if summary is None:
        _skip_mutation_no_results(
            log_path,
            context=_NoResultsContext(
                start=start,
                json_mode=json_mode,
                run_config=run_config,
                completed=completed,
                progress=progress,
            ),
        )
        return
    _finish_mutation(
        summary,
        run_config=run_config,
        execution=_MutationExecution(
            completed=completed,
            log_path=log_path,
            start=start,
            total_mutants=_mutation_total_from_progress(run_config, progress),
        ),
        json_mode=json_mode,
    )
