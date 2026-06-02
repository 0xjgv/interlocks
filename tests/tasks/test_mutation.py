"""Integration test for `cmd_mutation` — advisory mutation score via mutmut."""

from __future__ import annotations

import io
import json
import signal
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from interlocks import metrics as metrics_mod
from interlocks.config import InterlockConfig
from interlocks.tasks import mutation as mutation_mod
from interlocks.tasks.mutation import (
    _changed_to_globs,
    _JsonProgress,
    _make_pulse_thread,
    _mutant_in_changed,
    _mutation_progress_from_line,
    _mutation_progress_label,
    _MutationProgress,
    _print_json_progress,
    _print_survivors,
    _PulseState,
    _report_mutation,
    _resolve_min_score,
    _run_mutmut,
    _skip_mutation_no_coverage,
    _wait_for_proc,
    cmd_mutation,
)

_MODULE_SRC = textwrap.dedent(
    """\
    def is_positive(x):
        return x > 0
    """
)

_TEST_SRC = textwrap.dedent(
    """\
    import unittest
    from mypkg.mod import is_positive

    class TestIsPositive(unittest.TestCase):
        def test_positive(self):
            self.assertTrue(is_positive(1))
        def test_zero(self):
            self.assertFalse(is_positive(0))
        def test_negative(self):
            self.assertFalse(is_positive(-1))
    """
)

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "mut-probe"
    version = "0.0.1"
    requires-python = ">=3.11"

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.mutmut]
    paths_to_mutate = ["mypkg/"]
    tests_dir = ["tests/"]
    """
)


def _run_coverage(cwd: Path) -> None:
    """Run the project's unittest suite under coverage so `.coverage` exists."""
    cmd = [sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"]
    subprocess.run(cmd, cwd=cwd, check=True)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Project with `mypkg/mod.py` + covering unittest under `tests/`."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text(_TEST_SRC, encoding="utf-8")
    return tmp_path


def test_mutation_skips_when_coverage_missing(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No .coverage → cmd_mutation should warn_skip, never SystemExit."""
    monkeypatch.chdir(tmp_project)
    # Defaults (min-coverage=70) apply; no coverage.xml exists → skip path.
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation"])

    cmd_mutation()  # no SystemExit expected

    captured = capsys.readouterr()
    assert "mutation" in captured.out.lower()


def test_mutation_progress_label_normalizes_spinner_edges() -> None:
    assert _mutation_progress_label("⠋ Running Listing all tests") == "listing all tests"
    assert _mutation_progress_label("⠋Running Listing all tests") == "listing all tests"
    assert _mutation_progress_label("⠋") == "mutmut"


def test_mutation_progress_from_line_extracts_exact_checked_and_total() -> None:
    assert _mutation_progress_from_line("prefix 12/345 suffix") == _MutationProgress(12, 345)
    assert _mutation_progress_from_line("no fraction here") is None


def test_wait_for_proc_sends_sigint_before_terminating() -> None:
    class _TimeoutThenGracefulProc:
        def __init__(self) -> None:
            self.events: list[str] = []
            self.waits = 0

        def wait(self, timeout: int | None = None) -> int:
            self.events.append(f"wait:{timeout}")
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(["mutmut"], timeout)
            return 0

        def send_signal(self, sig: int) -> None:
            self.events.append(f"signal:{sig}")

        def terminate(self) -> None:
            self.events.append("terminate")

        def kill(self) -> None:
            self.events.append("kill")

    proc = _TimeoutThenGracefulProc()

    completed = _wait_for_proc(proc, timeout=1)  # type: ignore[arg-type]

    assert completed is False
    assert proc.events == ["wait:1", f"signal:{signal.SIGINT}", "wait:10"]


def test_wait_for_proc_terminates_then_kills_when_sigint_is_ignored() -> None:
    class _StubbornProc:
        def __init__(self) -> None:
            self.events: list[str] = []
            self.waits = 0

        def wait(self, timeout: int | None = None) -> int:
            self.events.append(f"wait:{timeout}")
            self.waits += 1
            if self.waits <= 3:
                raise subprocess.TimeoutExpired(["mutmut"], timeout)
            return 0

        def send_signal(self, sig: int) -> None:
            self.events.append(f"signal:{sig}")

        def terminate(self) -> None:
            self.events.append("terminate")

        def kill(self) -> None:
            self.events.append("kill")

    proc = _StubbornProc()

    completed = _wait_for_proc(proc, timeout=1)  # type: ignore[arg-type]

    assert completed is False
    assert proc.events == [
        "wait:1",
        f"signal:{signal.SIGINT}",
        "wait:10",
        "terminate",
        "wait:10",
        "kill",
        "wait:None",
    ]


def _no_results_context(
    progress: _MutationProgress | None,
    *,
    completed: bool = False,
) -> mutation_mod._NoResultsContext:
    return mutation_mod._NoResultsContext(
        start=0.0,
        json_mode=True,
        run_config=mutation_mod._MutationRun(
            min_coverage=80.0,
            coverage_pct=95.0,
            timeout=30,
            min_score=60.0,
            changed_only=False,
            globs=None,
            changed=None,
        ),
        completed=completed,
        progress=progress,
    )


def test_mutation_no_results_helpers_distinguish_progress_states(tmp_path: Path) -> None:
    log_path = tmp_path / "mutation.log"
    no_progress = _no_results_context(None)
    zero_progress = _no_results_context(_MutationProgress(0, 10))
    started = _no_results_context(_MutationProgress(1, 10))
    completed_started = _no_results_context(_MutationProgress(1, 10), completed=True)

    assert mutation_mod._mutation_progress_started(None) is False
    assert mutation_mod._mutation_progress_started(zero_progress.progress) is False
    assert mutation_mod._mutation_progress_started(started.progress) is True

    assert mutation_mod._mutation_no_results_reason(no_progress) == "no checked mutmut results"
    assert mutation_mod._mutation_no_results_reason(zero_progress) == "no checked mutmut results"
    assert mutation_mod._mutation_no_results_reason(started) == (
        "mutmut summary unavailable after partial progress"
    )

    assert mutation_mod._mutation_no_results_next_action(log_path, context=no_progress) == (
        f"Inspect `{log_path}` and rerun `interlocks gate mutation`."
    )
    assert mutation_mod._mutation_no_results_next_action(log_path, context=completed_started) == (
        f"Inspect `{log_path}` and rerun `interlocks gate mutation`."
    )
    assert mutation_mod._mutation_no_results_next_action(log_path, context=started) == (
        f"Inspect `{log_path}` for the last progress line and rerun "
        "`interlocks gate mutation` with a higher `--max-runtime=`."
    )

    assert mutation_mod._mutation_no_results_error(no_progress) == (
        "Mutation run timed out before any mutants were checked"
    )
    assert mutation_mod._mutation_no_results_error(zero_progress) == (
        "Mutation run timed out before any mutants were checked"
    )
    assert mutation_mod._mutation_no_results_error(started) == (
        "Mutation run timed out after progress reached 1/10, but mutmut results were unavailable"
    )


def test_print_json_progress_throttles_and_updates_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(mutation_mod.ui, "is_json", lambda: True)
    progress = _JsonProgress(last_emit=10.0)

    _print_json_progress("mutmut 1/10", progress, now=39.9)
    assert capsys.readouterr().err == ""
    assert progress.last_emit == 10.0

    _print_json_progress("mutmut 2/10", progress, now=40.0)
    assert capsys.readouterr().err == "interlocks: [mutation] mutmut 2/10 running\n"
    assert progress.last_emit == 40.0


@pytest.mark.slow
def test_mutation_runs_and_prints_score(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Happy path: coverage primed, short --max-runtime, mutmut reports a score."""
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    _run_coverage(tmp_project)
    monkeypatch.setattr(
        sys, "argv", ["interlocks", "gate", "mutation", "--max-runtime=30", "--min-coverage=0"]
    )

    cmd_mutation()  # advisory — must never SystemExit

    captured = capsys.readouterr()
    assert "Mutation: score" in captured.out


def test_report_mutation_prints_success_in_default_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(mutation_mod.ui, "is_verbose", lambda: False)
    monkeypatch.setattr(mutation_mod.ui, "is_json", lambda: False)
    summary = metrics_mod.MutationSummary(killed=3, survived=1, timeout=0, score=75.0)

    failed = _report_mutation(
        summary,
        min_score=None,
        completed=True,
        changed=None,
        log_path=tmp_path / "mutation.log",
    )

    assert not failed
    out = capsys.readouterr().out
    assert "Mutation: score 75.0%" in out
    assert "killed 3/4" in out


def test_mutation_json_skips_when_coverage_missing(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation", "--json"])

    cmd_mutation()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["command"] == "mutation"
    assert payload["passed"] is True
    assert payload["status"] == "skipped"
    assert payload["reason"] == "no coverage data"
    assert payload["next_action"] == (
        "Run `interlocks gate coverage` before `interlocks gate mutation`."
    )


def test_skip_mutation_no_coverage_json_passes_min_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_emit_mutation_skip_json(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(mutation_mod, "_emit_mutation_skip_json", fake_emit_mutation_skip_json)

    _skip_mutation_no_coverage(start=1.5, json_mode=True, min_cov=82.5)

    assert captured["reason"] == "no coverage data"
    assert captured["start"] == 1.5
    assert captured["min_coverage"] == 82.5


def test_mutation_json_skips_when_coverage_below_min(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="0.5"></coverage>')
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation", "--json"])

    cmd_mutation()

    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["status"] == "skipped"
    assert payload["reason"] == "coverage below mutation minimum"
    assert payload["coverage_pct"] == 50.0


def test_mutation_json_skips_when_no_changed_src(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(mutation_mod, "changed_py_files_vs", lambda _ref: {"tests/test_x.py"})
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "gate", "mutation", "--json", "--changed-only", "--min-coverage=0"],
    )

    cmd_mutation()

    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["status"] == "skipped"
    assert payload["reason"] == "no changed src files vs origin/main"
    assert "without `--changed-only`" in payload["next_action"]


def test_mutation_json_skips_when_mutmut_results_missing(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(
        mutation_mod,
        "_run_mutmut",
        lambda _argv, _timeout: (True, tmp_project / ".interlocks/mutation.log"),
    )
    monkeypatch.setattr(mutation_mod, "read_mutation_summary", lambda **_kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "gate", "mutation", "--json", "--min-coverage=0"],
    )

    cmd_mutation(changed_only=False)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == "interlocks: [mutation] mutmut run running\n"
    assert payload["passed"] is True
    assert payload["status"] == "skipped"
    assert payload["reason"] == "no checked mutmut results"
    assert "mutation.log" in payload["next_action"]


def _write_mutation_log(project: Path, line: str) -> Path:
    log_path = project / ".interlocks/mutation.log"
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text(line, encoding="utf-8")
    return log_path


def test_mutation_json_exits_when_enforced_timeout_has_no_results(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    log_path = _write_mutation_log(tmp_project, "0/10  🎉 0 🫥 0\n")
    monkeypatch.setattr(
        mutation_mod,
        "_run_mutmut",
        lambda _argv, _timeout: (False, log_path),
    )
    monkeypatch.setattr(mutation_mod, "read_mutation_summary", lambda **_kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "gate", "mutation", "--json", "--min-coverage=0", "--min-score=60"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cmd_mutation(changed_only=False)

    payload = json.loads(capsys.readouterr().out)
    assert excinfo.value.code == 1
    assert payload["passed"] is False
    assert payload["status"] == "partial"
    assert payload["reason"] == "no checked mutmut results"
    assert payload["completed"] is False
    assert payload["checked_mutants"] == 0
    assert payload["total_mutants"] == 10
    assert payload["completion_pct"] == 0.0
    assert payload["error"] == "Mutation run timed out before any mutants were checked"
    evidence = json.loads((tmp_project / ".interlocks/mutation.json").read_text(encoding="utf-8"))
    assert evidence["completed"] is False
    assert evidence["no_results"] is True
    assert evidence["checked_mutants"] == 0
    assert evidence["total_mutants"] == 10


def test_mutation_json_explains_partial_progress_without_summary(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    log_path = _write_mutation_log(tmp_project, "12/100  🎉 5 🫥 6  🙁 1\n")
    monkeypatch.setattr(
        mutation_mod,
        "_run_mutmut",
        lambda _argv, _timeout: (False, log_path),
    )
    monkeypatch.setattr(mutation_mod, "read_mutation_summary", lambda **_kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "gate", "mutation", "--json", "--min-coverage=0", "--min-score=60"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cmd_mutation(changed_only=False)

    payload = json.loads(capsys.readouterr().out)
    assert excinfo.value.code == 1
    assert payload["passed"] is False
    assert payload["status"] == "partial"
    assert payload["reason"] == "mutmut summary unavailable after partial progress"
    assert payload["checked_mutants"] == 12
    assert payload["total_mutants"] == 100
    assert payload["completion_pct"] == 12.0
    assert payload["error"] == (
        "Mutation run timed out after progress reached 12/100, but mutmut results were unavailable"
    )
    assert "higher `--max-runtime=`" in payload["next_action"]
    evidence = json.loads((tmp_project / ".interlocks/mutation.json").read_text(encoding="utf-8"))
    assert evidence["checked_mutants"] == 12
    assert evidence["total_mutants"] == 100


def test_mutation_json_reports_success_and_writes_evidence(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(mutation_mod, "changed_py_files_vs", lambda _ref: {"mypkg/mod.py"})
    log_path = _write_mutation_log(tmp_project, "4/4  🎉 3 🫥 1\n")
    monkeypatch.setattr(
        mutation_mod,
        "_run_mutmut",
        lambda _argv, _timeout: (True, log_path),
    )
    monkeypatch.setattr(
        mutation_mod,
        "read_mutation_summary",
        lambda **_kwargs: metrics_mod.MutationSummary(
            killed=3,
            survived=1,
            timeout=0,
            score=75.0,
            survivors=["mypkg.mod.x__mutmut_1"],
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "gate", "mutation", "--json", "--changed-only", "--min-coverage=0"],
    )

    cmd_mutation()

    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["status"] == "ok"
    assert payload["mode"] == "changed-only"
    assert payload["targets"] == ["mypkg.mod.*"]
    assert payload["checked_mutants"] == 4
    assert "total_mutants" not in payload
    assert "completion_pct" not in payload
    assert payload["score"] == 75.0
    assert payload["survivors"] == ["mypkg.mod.x__mutmut_1"]
    evidence = json.loads((tmp_project / ".interlocks/mutation.json").read_text(encoding="utf-8"))
    assert evidence["score"] == 75.0
    assert "total_mutants" not in evidence
    assert "completion_pct" not in evidence


def test_mutation_json_exits_on_enforced_low_score(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(
        mutation_mod,
        "_run_mutmut",
        lambda _argv, _timeout: (True, tmp_project / ".interlocks/mutation.log"),
    )
    monkeypatch.setattr(
        mutation_mod,
        "read_mutation_summary",
        lambda **_kwargs: metrics_mod.MutationSummary(killed=1, survived=1, timeout=0, score=50.0),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "gate", "mutation", "--json", "--min-coverage=0", "--min-score=80"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cmd_mutation(changed_only=False)

    payload = json.loads(capsys.readouterr().out)
    assert excinfo.value.code == 1
    assert payload["passed"] is False
    assert payload["status"] == "failed"
    assert payload["error"] == "Mutation score 50.0% below threshold 80.0%"


def test_mutation_json_exits_on_enforced_partial_run(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    log_path = _write_mutation_log(tmp_project, "10/20  🎉 9 🫥 1\n")
    monkeypatch.setattr(
        mutation_mod,
        "_run_mutmut",
        lambda _argv, _timeout: (False, log_path),
    )
    monkeypatch.setattr(
        mutation_mod,
        "read_mutation_summary",
        lambda **_kwargs: metrics_mod.MutationSummary(killed=9, survived=1, timeout=0, score=90.0),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "gate", "mutation", "--json", "--min-coverage=0", "--min-score=60"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cmd_mutation(changed_only=False)

    payload = json.loads(capsys.readouterr().out)
    assert excinfo.value.code == 1
    assert payload["passed"] is False
    assert payload["status"] == "partial"
    assert payload["completed"] is False
    assert payload["checked_mutants"] == 10
    assert payload["total_mutants"] == 20
    assert payload["completion_pct"] == 50.0
    assert "estimated_full_runtime_seconds" in payload
    assert "timed out" in payload["error"]
    assert "partial" in payload["error"]


# ─────────────── threshold cascade ─────────────────────


def test_mutation_min_coverage_comes_from_config(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """[tool.interlocks] mutation_min_coverage = 95 → skip message mentions 95.0%."""
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + "\n[tool.interlocks]\nmutation_min_coverage = 95\n", encoding="utf-8"
    )
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="0.5"></coverage>')
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation"])

    cmd_mutation()  # advisory — must never SystemExit
    captured = capsys.readouterr()
    assert "95" in captured.out  # threshold surfaced in the skip message


# ─────────────── _resolve_min_score precedence ─────────────────────


def _cfg(*, enforce: bool = False, min_score: float = 80.0) -> InterlockConfig:
    """Minimal cfg for `_resolve_min_score`; paths aren't touched."""
    root = Path()
    return InterlockConfig(
        project_root=root,
        src_dir=root / "src",
        test_dir=root / "tests",
        test_runner="pytest",
        test_invoker="python",
        enforce_mutation=enforce,
        mutation_min_score=min_score,
    )


def test_resolve_min_score_cli_flag_wins_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--min-score=42.5` beats caller-supplied default."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation", "--min-score=42.5"])
    assert _resolve_min_score(_cfg(), default=99.0) == 42.5


def test_resolve_min_score_default_wins_over_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    """No CLI flag → caller-supplied default beats cfg.mutation_min_score."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation"])
    assert _resolve_min_score(_cfg(enforce=True, min_score=80.0), default=55.0) == 55.0


def test_resolve_min_score_enforce_when_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """No CLI flag, no default → cfg.mutation_min_score when enforcing."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation"])
    assert _resolve_min_score(_cfg(enforce=True, min_score=70.0)) == 70.0


def test_resolve_min_score_returns_none_when_advisory(monkeypatch: pytest.MonkeyPatch) -> None:
    """No CLI flag, no default, advisory → None (no gate)."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation"])
    assert _resolve_min_score(_cfg(enforce=False)) is None


# ─────────────── _mutant_in_changed ─────────────────────


def test_mutant_in_changed_matches_module_path() -> None:
    assert _mutant_in_changed("interlocks.git.x_foo__mutmut_1", {"interlocks/git.py"})


def test_mutant_in_changed_handles_nested_modules() -> None:
    assert _mutant_in_changed(
        "interlocks.tasks.mutation.x__parse_results__mutmut_5", {"interlocks/tasks/mutation.py"}
    )


def test_mutant_in_changed_matches_suffix() -> None:
    """Path matches if any changed file ends with '/<module-path>'."""
    assert _mutant_in_changed("interlocks.git.x_foo__mutmut_1", {"src/interlocks/git.py"})


def test_mutant_in_changed_misses_unrelated() -> None:
    assert not _mutant_in_changed("interlocks.git.x_foo__mutmut_1", {"interlocks/runner.py"})


def test_mutant_in_changed_empty_set_is_miss() -> None:
    assert not _mutant_in_changed("interlocks.git.x_foo__mutmut_1", set())


# ─────────────── _print_survivors ─────────────────────


def test_print_survivors_prints_nothing_when_empty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_survivors([], None)
    assert capsys.readouterr().out == ""


def test_print_survivors_prints_header_and_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_survivors(["interlocks.a.x__mutmut_1", "interlocks.b.x__mutmut_2"], None)
    out = capsys.readouterr().out
    assert "surviving mutants (2 shown)" in out
    assert "interlocks.a.x__mutmut_1" in out
    assert "interlocks.b.x__mutmut_2" in out


def test_print_survivors_caps_at_twenty(capsys: pytest.CaptureFixture[str]) -> None:
    many = [f"interlocks.a.x__mutmut_{i}" for i in range(30)]
    _print_survivors(many, None)
    out = capsys.readouterr().out
    assert "surviving mutants (20 shown)" in out
    assert "interlocks.a.x__mutmut_0" in out
    assert "interlocks.a.x__mutmut_19" in out
    assert "interlocks.a.x__mutmut_20" not in out


def test_print_survivors_filters_to_changed_set(
    capsys: pytest.CaptureFixture[str],
) -> None:
    survivors = ["interlocks.git.x_foo__mutmut_1", "interlocks.runner.x_bar__mutmut_2"]
    _print_survivors(survivors, {"interlocks/git.py"})
    out = capsys.readouterr().out
    assert "interlocks.git.x_foo__mutmut_1" in out
    assert "interlocks.runner.x_bar__mutmut_2" not in out


def test_print_survivors_silent_when_nothing_matches_changed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_survivors(["interlocks.runner.x_foo__mutmut_1"], {"interlocks/git.py"})
    assert capsys.readouterr().out == ""


# ─────────────── coverage fixture (shared with threshold test) ─────────


@pytest.fixture
def primed_coverage_xml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Path]:
    """Return a factory that writes `.coverage` + `coverage.xml` and stubs regeneration."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".coverage").write_text("", encoding="utf-8")
    xml = tmp_path / "coverage.xml"
    monkeypatch.setattr(metrics_mod, "generate_coverage_xml", lambda: xml)

    def _write(body: str) -> Path:
        xml.write_text(body, encoding="utf-8")
        return xml

    return _write


# ─────────────── _changed_to_globs ─────────────────────


def test_changed_to_globs_drops_tests() -> None:
    """Test paths under tests/ never become mutmut globs."""
    globs = _changed_to_globs(
        {"interlocks/tasks/foo.py", "tests/test_x.py"}, "interlocks", "tests"
    )
    assert globs == ["interlocks.tasks.foo.*"]


def test_changed_to_globs_handles_init() -> None:
    """`__init__.py` paths translate to dotted module globs without losing the name."""
    globs = _changed_to_globs({"interlocks/__init__.py"}, "interlocks", "tests")
    assert globs == ["interlocks.__init__.*"]


def test_changed_to_globs_returns_empty_when_no_src_files() -> None:
    """Diff with only test-tree paths produces no globs (caller will skip)."""
    globs = _changed_to_globs({"tests/x.py"}, "interlocks", "tests")
    assert globs == []


def test_changed_to_globs_root_layout_keeps_top_level_modules() -> None:
    """`src_dir == "."` (root layout) → top-level *.py files become globs, tests excluded."""
    globs = _changed_to_globs({"my_mod.py", "tests/test_x.py"}, ".", "tests")
    assert globs == ["my_mod.*"]


def test_changed_to_globs_empty_src_dir_treated_as_root() -> None:
    """Empty ``src_dir`` behaves like ``"."`` — top-level files mutate, tests skipped."""
    globs = _changed_to_globs({"a.py", "tests/test_a.py"}, "", "tests")
    assert globs == ["a.*"]


# ─────────────── cmd_mutation incremental wiring ─────────────────────


def test_cmd_mutation_skips_when_no_changed_src(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--changed-only` with empty src diff → warn_skip + no mutmut launch."""
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.setattr(mutation_mod, "changed_py_files_vs", lambda _ref: {"tests/test_x.py"})

    def _no_run(*_args: object, **_kwargs: object) -> tuple[bool, Path]:
        pytest.fail("_run_mutmut should not run when no src files changed")

    monkeypatch.setattr(mutation_mod, "_run_mutmut", _no_run)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation", "--min-coverage=0"])

    cmd_mutation(changed_only=True)

    captured = capsys.readouterr()
    assert "no changed src files" in captured.out


def test_cmd_mutation_passes_globs_to_mutmut(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--changed-only` with src diff → mutmut argv has `run` BEFORE module globs."""
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(
        mutation_mod,
        "changed_py_files_vs",
        lambda _ref: {"mypkg/mod.py", "mypkg/other.py"},
    )

    captured_argv: list[list[str]] = []

    def _spy_run(argv: list[str], _timeout: int) -> tuple[bool, Path]:
        captured_argv.append(argv)
        return True, tmp_project / ".interlocks" / "mutation.log"

    monkeypatch.setattr(mutation_mod, "_run_mutmut", _spy_run)
    monkeypatch.setattr(
        mutation_mod, "read_mutation_summary", lambda **_kwargs: None
    )  # short-circuit before parsing
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation", "--min-coverage=0"])

    cmd_mutation(changed_only=True)

    assert captured_argv, "expected _run_mutmut to be called"
    argv = captured_argv[0]
    assert "mutmut" in argv
    # mutmut requires `run` BEFORE positional globs. Find the mutmut subcommand `run`
    # (the LAST `run` — the first is `uv run` from `uv_run_with`).
    run_idx = len(argv) - 1 - argv[::-1].index("run")
    assert argv[run_idx - 1] == "mutmut"
    assert argv[run_idx + 1 :] == ["mypkg.mod.*", "mypkg.other.*"]
    out = capsys.readouterr().out
    assert "no checked mutmut results" in out
    assert ".interlocks" in out
    assert "mutation.log" in out


def test_cmd_mutation_changed_only_since_overrides_config_ref(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    seen_refs: list[str] = []

    def _changed_py_files_vs(ref: str) -> set[str]:
        seen_refs.append(ref)
        return {"mypkg/mod.py"}

    monkeypatch.setattr(mutation_mod, "changed_py_files_vs", _changed_py_files_vs)
    monkeypatch.setattr(
        mutation_mod,
        "_run_mutmut",
        lambda _argv, _timeout: (True, tmp_project / ".interlocks" / "mutation.log"),
    )
    monkeypatch.setattr(mutation_mod, "read_mutation_summary", lambda **_kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "gate", "mutation", "--min-coverage=0", "--since=HEAD~1"],
    )

    cmd_mutation(changed_only=True)

    assert seen_refs == ["HEAD~1"]


def test_cmd_mutation_invokes_popen_with_run_then_globs(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end argv guard: subprocess.Popen receives `... run <glob1> <glob2>`.

    Catches the prior ordering bug where `run` was appended AFTER globs (which
    mutmut would parse as `mutmut <globs> run` — invalid).
    """
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(
        mutation_mod,
        "changed_py_files_vs",
        lambda _ref: {"mypkg/mod.py", "mypkg/other.py"},
    )

    captured: dict[str, list[str]] = {}

    class _FakeProc:
        stdout = io.StringIO("")

        def wait(self, timeout: int | None = None) -> int:
            return 0

        def terminate(self) -> None:  # pragma: no cover - never timed out
            pass

        def kill(self) -> None:  # pragma: no cover - never timed out
            pass

    def _fake_popen(argv: list[str], **_kwargs: object) -> _FakeProc:
        captured["argv"] = argv
        return _FakeProc()

    monkeypatch.setattr(mutation_mod.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(mutation_mod, "read_mutation_summary", lambda **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation", "--min-coverage=0"])

    cmd_mutation(changed_only=True)

    argv = captured["argv"]
    assert "mutmut" in argv
    # Find the mutmut subcommand `run` — the LAST `run`, since `uv run` precedes it.
    run_idx = len(argv) - 1 - argv[::-1].index("run")
    assert argv[run_idx - 1] == "mutmut"
    assert argv[run_idx + 1 :] == ["mypkg.mod.*", "mypkg.other.*"]


def test_cmd_mutation_full_run_uses_run_subcommand(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-incremental path still passes `run` to mutmut (no trailing globs)."""
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)

    captured_argv: list[list[str]] = []

    def _spy_run(argv: list[str], _timeout: int) -> tuple[bool, Path]:
        captured_argv.append(argv)
        return True, tmp_project / ".interlocks" / "mutation.log"

    monkeypatch.setattr(mutation_mod, "_run_mutmut", _spy_run)
    monkeypatch.setattr(mutation_mod, "read_mutation_summary", lambda **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation", "--min-coverage=0"])

    cmd_mutation(changed_only=False)

    assert captured_argv, "expected _run_mutmut to be called"
    assert captured_argv[0][-1] == "run"


def test_cmd_mutation_writes_interlocks_evidence(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(mutation_mod, "changed_py_files_vs", lambda _ref: {"mypkg/mod.py"})
    monkeypatch.setattr(
        mutation_mod,
        "_run_mutmut",
        lambda _argv, _timeout: (True, tmp_project / ".interlocks/mutation.log"),
    )
    monkeypatch.setattr(
        mutation_mod,
        "read_mutation_summary",
        lambda **_kwargs: metrics_mod.MutationSummary(
            killed=3, survived=1, timeout=0, score=75.0, survivors=["mypkg.mod.x__mutmut_1"]
        ),
    )
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation", "--min-coverage=0"])

    cmd_mutation(changed_only=True)

    payload = json.loads((tmp_project / ".interlocks/mutation.json").read_text(encoding="utf-8"))
    assert payload["command"] == "mutation"
    assert payload["completed"] is True
    assert payload["mode"] == "changed-only"
    assert payload["targets"] == ["mypkg.mod.*"]
    assert payload["checked_mutants"] == 4
    assert payload["score"] == 75.0


# ─────────────── live progress pulse (`_run_mutmut`) ───────────────────


class _SlowStdout:
    """Iterable stdout that sleeps between yields to give the pulse thread time to fire."""

    def __init__(self, lines: Iterable[str], delay: float) -> None:
        self._lines = list(lines)
        self._delay = delay

    def __iter__(self) -> _SlowStdout:
        return self

    def __next__(self) -> str:
        if not self._lines:
            raise StopIteration
        time.sleep(self._delay)
        return self._lines.pop(0)

    def close(self) -> None:
        self._lines = []


class _FakePopen:
    """Minimal `subprocess.Popen` stand-in that streams `lines` then exits 0."""

    def __init__(self, lines: Iterable[str], delay: float = 0.05) -> None:
        self.stdout = _SlowStdout(lines, delay)
        self._lines = list(lines)
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        # Block until the reader has drained stdout. The fake stdout sleeps between
        # yields, so the pulse thread fires while we wait here.
        deadline = time.monotonic() + (timeout if timeout is not None else 60.0)
        while self.stdout._lines and time.monotonic() < deadline:
            time.sleep(0.01)
        return 0

    def terminate(self) -> None:
        self.stdout._lines = []

    def kill(self) -> None:
        self.stdout._lines = []


class _ClosableSlowStdout:
    def __init__(self, lines: Iterable[str], delay: float = 0.05) -> None:
        self._lines = list(lines)
        self._delay = delay
        self.closed = False

    def __iter__(self) -> _ClosableSlowStdout:
        return self

    def __next__(self) -> str:
        time.sleep(self._delay)
        if self.closed:
            raise ValueError("I/O operation on closed file.")
        if not self._lines:
            raise StopIteration
        return self._lines.pop(0)

    def close(self) -> None:
        self.closed = True


class _ImmediatePopen:
    """Popen stand-in whose process exits before stdout is fully drained."""

    def __init__(self, lines: Iterable[str], delay: float = 0.05) -> None:
        self.stdout = _ClosableSlowStdout(lines, delay)
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def terminate(self) -> None:
        self.stdout.close()

    def kill(self) -> None:
        self.stdout.close()


_PULSE_LINES = [
    "1/100  🎉 0 🫥 1\n",
    "2/100  🎉 0 🫥 2\n",
    "3/100  🎉 0 🫥 3\n",
    "4/100  🎉 0 🫥 4\n",
    "5/100  🎉 0 🫥 5\n",
]


def _install_fake_popen(
    monkeypatch: pytest.MonkeyPatch, lines: list[str], delay: float = 0.05
) -> None:
    def _factory(*_args: object, **_kwargs: object) -> _FakePopen:
        return _FakePopen(lines, delay=delay)

    monkeypatch.setattr(mutation_mod.subprocess, "Popen", _factory)


def test_run_mutmut_prints_json_progress_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mutation_mod.ui, "is_json", lambda: True)
    monkeypatch.setattr(mutation_mod.ui, "is_verbose", lambda: False)
    monkeypatch.setattr(mutation_mod, "VERBOSE", False)
    monkeypatch.setattr(mutation_mod, "_JSON_PROGRESS_SECONDS", 0.0)
    _install_fake_popen(
        monkeypatch,
        [
            "⠋ Running clean tests\n",
            "1/100  🎉 0 🫥 1\n",
            "2/100  🎉 1 🫥 1\n",
        ],
        delay=0.0,
    )

    completed, _log_path = _run_mutmut(["fake-mutmut"], timeout=10)

    captured = capsys.readouterr()
    assert completed is True
    assert captured.out == ""
    assert "interlocks: [mutation] clean tests running\n" in captured.err
    assert "interlocks: [mutation] mutmut 1/100 running\n" in captured.err


def test_run_mutmut_closes_slow_reader_without_thread_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mutation_mod.ui, "is_json", lambda: True)
    monkeypatch.setattr(mutation_mod.ui, "is_verbose", lambda: False)
    monkeypatch.setattr(mutation_mod, "_READER_JOIN_SECONDS", 0.01)

    def _factory(*_args: object, **_kwargs: object) -> _ImmediatePopen:
        return _ImmediatePopen(["1/100  🎉 0 🫥 1\n"], delay=0.05)

    monkeypatch.setattr(mutation_mod.subprocess, "Popen", _factory)

    completed, _log_path = _run_mutmut(["fake-mutmut"], timeout=10)

    captured = capsys.readouterr()
    assert completed is True
    assert "Exception in thread" not in captured.err


def test_pulse_emits_periodically_to_tty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TTY path: pulse refreshes the in-place progress line at least once before final newline."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mutation_mod, "VERBOSE", False)
    monkeypatch.setattr("interlocks.runner.VERBOSE", False)
    monkeypatch.setattr(mutation_mod, "_PULSE_SECONDS", 0.02)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation"])

    buf = io.StringIO()
    buf.isatty = lambda: True  # type: ignore[method-assign]
    monkeypatch.setattr(sys, "stdout", buf)

    _install_fake_popen(monkeypatch, _PULSE_LINES, delay=0.05)
    completed, _log_path = _run_mutmut(["fake-mutmut"], timeout=10)

    out = buf.getvalue()
    assert completed is True
    # At least one `\r…/…` write occurred BEFORE the final `\n`.
    assert "\r" in out
    cr_index = out.index("\r")
    final_nl = out.rfind("\n")
    assert cr_index < final_nl
    # Final newline emission preserved.
    assert out.endswith("\n")
    # The last progress line is still printed at the end.
    assert "5/100" in out


def test_pulse_silent_when_non_tty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-tty path: NO `\\r` writes — output bit-identical to pre-pulse behavior."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mutation_mod, "VERBOSE", False)
    monkeypatch.setattr("interlocks.runner.VERBOSE", False)
    monkeypatch.setattr(mutation_mod, "_PULSE_SECONDS", 0.02)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation"])

    buf = io.StringIO()
    buf.isatty = lambda: False  # type: ignore[method-assign]
    monkeypatch.setattr(sys, "stdout", buf)

    _install_fake_popen(monkeypatch, _PULSE_LINES, delay=0.02)
    _run_mutmut(["fake-mutmut"], timeout=10)

    out = buf.getvalue()
    assert "\r" not in out
    # Final progress line emission preserved.
    assert "5/100" in out
    assert out.endswith("\n")


def test_make_pulse_thread_returns_none_when_inactive() -> None:
    """`active=False` short-circuits the helper before allocating a Thread."""
    state = _PulseState(active=False)
    stop = threading.Event()
    assert _make_pulse_thread(lambda: None, stop, state) is None


def test_make_pulse_thread_returns_thread_when_active() -> None:
    """`active=True` returns a daemon Thread that exits when `stop` is set."""
    state = _PulseState(active=True)
    stop = threading.Event()
    thread = _make_pulse_thread(lambda: None, stop, state)
    assert thread is not None
    assert thread.daemon is True


def test_pulse_silent_when_verbose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verbose path: pulse disabled even on a tty — raw stream passes through, no `\\r` writes."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mutation_mod, "VERBOSE", True)
    monkeypatch.setattr("interlocks.runner.VERBOSE", True)
    monkeypatch.setattr(mutation_mod, "_PULSE_SECONDS", 0.02)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "mutation", "--verbose"])

    buf = io.StringIO()
    buf.isatty = lambda: True  # type: ignore[method-assign]
    monkeypatch.setattr(sys, "stdout", buf)

    _install_fake_popen(monkeypatch, _PULSE_LINES, delay=0.02)
    _run_mutmut(["fake-mutmut"], timeout=10)

    out = buf.getvalue()
    assert "\r" not in out
