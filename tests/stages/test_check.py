"""Integration tests for `interlocks check` local edit-loop composition."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from interlocks.runner import Task
from tests.conftest import TmpProjectFactory, stub_project_venv

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "tmpproj"
    version = "0.0.1"
    requires-python = ">=3.11"

    [tool.ruff]
    target-version = "py311"
    line-length = 99

    [tool.ruff.lint]
    select = ["E", "F", "I"]

    [tool.basedpyright]
    pythonVersion = "3.11"
    typeCheckingMode = "standard"
    reportMissingTypeStubs = false
    """
)

_INIT_SRC = '"""Tmp project package."""\n\nfrom interlocks.core import add\n\n__all__ = ["add"]\n'

_CLEAN_SRC = textwrap.dedent(
    '''\
    """Tiny module."""


    def add(a: int, b: int) -> int:
        return a + b
    '''
)

_TEST_SRC = textwrap.dedent(
    '''\
    """Tiny test."""

    import unittest

    from interlocks.core import add


    class TestAdd(unittest.TestCase):
        def test_add(self) -> None:
            self.assertEqual(add(2, 3), 5)
    '''
)


@pytest.fixture
def tmp_project(make_tmp_project: TmpProjectFactory) -> Path:
    return make_tmp_project(
        pyproject=_PYPROJECT,
        src_files={
            "interlocks/__init__.py": _INIT_SRC,
            "interlocks/core.py": _CLEAN_SRC,
        },
        test_files={
            "__init__.py": "",
            "test_add.py": _TEST_SRC,
        },
    )


def _run_check(cwd: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "check", *extra],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_check_json(cwd: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "check", "--json", *extra],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_passes_on_clean_project(tmp_project: Path) -> None:
    result = _run_check(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = result.stdout
    # Minimal-default: no chrome, but each running gate now emits one row.
    assert "Quality Checks" not in out
    assert "Parallel" not in out
    assert "Suppressions" not in out
    assert "Completed in" not in out
    # Per-gate rows print in default mode (no more near-silent run).
    assert "[fix]" in out
    assert "[format]" in out
    assert "[test]" in out
    # The fix-optimize summary leak is gone: no bare `plan` line, no orphaned
    # kv_block keys from the verbose-only SELECTED / plan blocks.
    assert "plan .lintfix/optimize.json" not in out
    assert "author cost" not in out
    assert "total value" not in out
    assert "total cost" not in out
    assert out.strip().splitlines()[-1].startswith("check: ok — ")


def test_check_json_is_parseable(tmp_project: Path) -> None:
    result = _run_check_json(tmp_project)

    payload = json.loads(result.stdout)
    assert payload["command"] == "check"
    assert payload["schema_version"] == 1
    assert isinstance(payload["passed"], bool)
    assert isinstance(payload["elapsed_seconds"], (int, float))
    assert isinstance(payload["gates"], list)
    for gate in payload["gates"]:
        assert {"name", "status", "elapsed_seconds"} <= gate.keys()
        assert "label" not in gate  # `name` is the sole stable identifier
    assert isinstance(payload["skipped"], list)
    assert "evidence_path" not in payload
    assert payload["agent"]["state"] in {"passed", "attention"}
    assert payload["agent"]["required_actions"] == []
    assert any(artifact["kind"] == "run-summary" for artifact in payload["artifacts"])


def test_check_json_exit_code_matches_human_mode(tmp_project: Path) -> None:
    assert _run_check(tmp_project).returncode == _run_check_json(tmp_project).returncode


def test_check_json_dominates_verbose(tmp_project: Path) -> None:
    result = _run_check_json(tmp_project, "--verbose")
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one object, got {result.stdout!r}"
    assert json.loads(lines[0])["command"] == "check"


# A high-complexity, fully-uncovered function — CRAP is far above the 30.0 ceiling,
# so the advisory CRAP gate reaches `_print_offender`.
_CRAP_OFFENDER_SRC = textwrap.dedent(
    '''\
    """Module with one gnarly uncovered function."""


    def add(a: int, b: int) -> int:
        return a + b


    def gnarly(n: int) -> int:
        total = 0
        if n > 0:
            total += 1
        if n > 1:
            total += 2
        if n > 2:
            total += 3
        if n > 3:
            total += 4
        if n > 4:
            total += 5
        if n > 5:
            total += 6
        if n > 6:
            total += 7
        return total
    '''
)


def test_check_json_single_object_with_crap_offenders(tmp_project: Path) -> None:
    """Regression: advisory CRAP must not leak `CRAP=` lines before the JSON object.

    Before the fix, `cmd_crap_cached_advisory` printed raw offender text ahead of
    the JSON object, so `json.loads(stdout)` failed on any project with offenders.
    """
    (tmp_project / "interlocks" / "core.py").write_text(_CRAP_OFFENDER_SRC, encoding="utf-8")
    # Prime a fresh `.coverage` cache so the advisory CRAP gate runs (not skipped).
    subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "ci"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )

    result = _run_check_json(tmp_project)

    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one JSON object, got {result.stdout!r}"
    payload = json.loads(lines[0])
    assert payload["command"] == "check"
    assert "CRAP=" not in result.stdout


def test_check_json_verbose_changed_emits_single_object(tmp_project: Path) -> None:
    """Regression: `check --json --verbose --changed` must not leak a `scope=` header.

    The empty-changed-scope and scoped-files headers were gated only on `is_verbose()`;
    under `--json` they printed raw text before the JSON object.
    """
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_project, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_project, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_project, check=True)

    # Empty changed scope: nothing changed vs HEAD.
    empty = _run_check_json(tmp_project, "--verbose", "--changed")
    empty_lines = [ln for ln in empty.stdout.splitlines() if ln.strip()]
    assert len(empty_lines) == 1, f"expected one object, got {empty.stdout!r}"
    assert json.loads(empty_lines[0])["command"] == "check"
    assert "scope=" not in empty.stdout

    # Non-empty changed scope: a touched file triggers the scoped-files header.
    (tmp_project / "interlocks" / "core.py").write_text(
        _CLEAN_SRC + "\n\ndef sub(a: int, b: int) -> int:\n    return a - b\n",
        encoding="utf-8",
    )
    scoped = _run_check_json(tmp_project, "--verbose", "--changed=HEAD")
    scoped_lines = [ln for ln in scoped.stdout.splitlines() if ln.strip()]
    assert len(scoped_lines) == 1, f"expected one object, got {scoped.stdout!r}"
    payload = json.loads(scoped_lines[0])
    assert payload["command"] == "check"
    skipped = {entry["name"]: entry for entry in payload["skipped"]}
    assert skipped["test"]["next_action"] == "Run `interlocks gate test` for the full suite."
    assert skipped["deps"]["next_action"] == (
        "Run `interlocks gate deps` for dependency graph checks."
    )
    assert skipped["attribution"]["next_action"] == (
        "Run `interlocks gate behavior-attribution` for registry-wide attribution."
    )
    assert "changed vs" not in scoped.stdout


def test_check_passes_on_clean_project_verbose(tmp_project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "check", "--verbose"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = result.stdout
    assert re.search(r"interlocks v\d", out)
    assert "Quality Checks" in out
    assert "Parallel" in out
    assert "Advisory" in out
    assert "[fix]" in out
    assert "[format]" in out
    assert "[typecheck]" in out
    assert "[test]" in out
    assert "Suppressions" in out
    assert "Completed in" in out
    assert "check: ok — " in out


def test_check_skips_format_when_micro_budget_would_touch_outside_hunk(tmp_project: Path) -> None:
    """Small edits get an explainable skip instead of broad default format churn."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_project, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_project, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_project, check=True)
    dirty = textwrap.dedent(
        '''\
        """Tiny module with format drift."""


        def add(a: int, b: int) -> int:
            values = [1,2,3]
            return a + b
        '''
    )
    (tmp_project / "interlocks" / "core.py").write_text(dirty, encoding="utf-8")

    result = _run_check(tmp_project, "--skip=lint")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    payload = json.loads((tmp_project / ".lintfix" / "optimize.json").read_text(encoding="utf-8"))
    [format_candidate] = [
        candidate for candidate in payload["not_selected"] if candidate["kind"] == "format"
    ]
    assert format_candidate["reason"] == "would exceed outside-author-hunk budget"


def test_check_in_process_dispatches_stages(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stub fix/format/run_tasks + suppressions; confirm cmd_check orchestrates them."""
    from interlocks.stages import check as check_mod

    calls: list[object] = []
    monkeypatch.setattr(
        check_mod, "_run_budgeted_mutation", lambda **_k: calls.append("budgeted-mutation")
    )
    monkeypatch.setattr(
        check_mod,
        "run_tasks",
        lambda tasks: calls.append(("run_tasks", [t.description for t in tasks])),
    )
    monkeypatch.setattr(
        check_mod,
        "run",
        lambda task, **kw: calls.append(("run", task.description, kw)),
    )
    monkeypatch.setattr(
        check_mod, "cmd_crap_cached_advisory", lambda *_a, **_k: calls.append("cached-crap")
    )
    monkeypatch.setattr(
        check_mod, "print_suppressions_report", lambda: calls.append("suppressions")
    )

    monkeypatch.chdir(tmp_project)
    check_mod.cmd_check()

    assert calls == [
        "budgeted-mutation",
        ("run_tasks", ["Type check", "Run tests"]),
        ("run", "Deps (deptry)", {"no_exit": True}),
        "cached-crap",
        "suppressions",
    ]
    out = capsys.readouterr().out
    assert "Quality Checks" in out
    assert "Parallel" in out
    assert "Advisory" in out
    assert "Completed in" in out


def test_check_skip_filters_direct_and_parallel_tasks(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from interlocks.stages import check as check_mod

    calls: list[object] = []
    monkeypatch.setattr(sys, "argv", ["interlocks", "check", "--skip=fix,typecheck,deps,crap"])
    monkeypatch.setattr(
        check_mod, "_run_budgeted_mutation", lambda **_k: calls.append("budgeted-mutation")
    )
    monkeypatch.setattr(
        check_mod,
        "run_tasks",
        lambda tasks: calls.append(("run_tasks", [t.label for t in tasks])),
    )
    monkeypatch.setattr(check_mod, "run", lambda task, **kw: calls.append(("run", task.label, kw)))
    monkeypatch.setattr(
        check_mod, "cmd_crap_cached_advisory", lambda *_a, **_k: calls.append("cached-crap")
    )
    monkeypatch.setattr(check_mod, "print_suppressions_report", lambda: None)
    monkeypatch.chdir(tmp_project)

    check_mod.cmd_check()

    # The budgeted-mutation seam is always invoked; `--skip=fix`/`format` is
    # resolved inside `run_budgeted_mutation` (stubbed here). check itself
    # filters the advisory deps/crap gates and threads the policy to run_tasks.
    assert calls == ["budgeted-mutation", ("run_tasks", ["typecheck", "test"])]
    out = capsys.readouterr().out
    assert "skips active" in out
    assert "crap: skipped by global skip policy" in out


def test_check_in_process_runs_suppressions_on_failure(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suppressions report is in a `finally` — runs even when an inner stage raises."""
    from interlocks.stages import check as check_mod

    calls: list[str] = []

    def boom(*_a: object, **_k: object) -> None:
        calls.append("budgeted-mutation")
        raise SystemExit(2)

    monkeypatch.setattr(check_mod, "_run_budgeted_mutation", boom)
    monkeypatch.setattr(check_mod, "run_tasks", lambda tasks: calls.append("run_tasks"))
    monkeypatch.setattr(
        check_mod, "print_suppressions_report", lambda: calls.append("suppressions")
    )

    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit):
        check_mod.cmd_check()
    assert calls == ["budgeted-mutation", "suppressions"]


def test_check_success_is_one_verdict_line(tmp_project: Path) -> None:
    result = _run_check(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = result.stdout
    assert not re.search(r"interlocks v\d", out)
    assert "Quality Checks" not in out
    assert "Parallel" not in out
    assert "Advisory" not in out
    assert "Suppressions" not in out
    assert "Completed in" not in out
    assert out.strip().splitlines()[-1].startswith("check: ok — ")


def test_check_failure_emits_failed_verdict(tmp_project: Path) -> None:
    failing = textwrap.dedent(
        '''\
        """Failing test."""

        import unittest


        class TestBroken(unittest.TestCase):
            def test_broken(self) -> None:
                self.assertEqual(1, 2)
        '''
    )
    (tmp_project / "tests" / "test_add.py").write_text(failing, encoding="utf-8")

    result = _run_check(tmp_project)

    assert result.returncode != 0
    out = result.stdout
    assert "Quality Checks" not in out
    assert "[test]" in out  # failing row preserved
    assert any(line.startswith("check: FAILED — ") for line in out.splitlines()), out


def test_check_quiet_argv_is_rejected(tmp_project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "check", "--quiet"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    # --quiet exits 1 (a usage error); exit 2 is reserved for no-pyproject.
    assert result.returncode == 1
    assert "--quiet was removed" in result.stderr


# ─────────────── require_acceptance + run_acceptance_in_check ───────────────


def _write_require_acceptance_check_project(
    tmp_path: Path, *, run_acceptance_in_check: bool
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "check-req-acc"
            version = "0.0.0"

            [tool.interlocks]
            require_acceptance = true
            run_acceptance_in_check = {"true" if run_acceptance_in_check else "false"}
            """
        ),
        encoding="utf-8",
    )
    stub_project_venv(tmp_path)


def _capture_check_parallel_descriptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    from interlocks.stages import check as check_mod

    captured: list[str] = []
    monkeypatch.setattr(check_mod, "_run_budgeted_mutation", lambda **_k: None)
    monkeypatch.setattr(
        check_mod, "run_tasks", lambda tasks: captured.extend(t.description for t in tasks)
    )
    monkeypatch.setattr(check_mod, "run", lambda task, **_kw: None)
    monkeypatch.setattr(check_mod, "cmd_crap_cached_advisory", lambda *_a, **_k: None)
    monkeypatch.setattr(check_mod, "print_suppressions_report", lambda: None)
    monkeypatch.chdir(tmp_path)
    check_mod.cmd_check()
    return captured


def _capture_check_parallel_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Task]:
    from interlocks.stages import check as check_mod

    captured: list[Task] = []
    monkeypatch.setattr(check_mod, "_run_budgeted_mutation", lambda **_k: None)
    monkeypatch.setattr(check_mod, "run_tasks", captured.extend)
    monkeypatch.setattr(check_mod, "run", lambda task, **_kw: None)
    monkeypatch.setattr(check_mod, "cmd_crap_cached_advisory", lambda *_a, **_k: None)
    monkeypatch.setattr(check_mod, "print_suppressions_report", lambda: None)
    monkeypatch.chdir(tmp_path)
    check_mod.cmd_check()
    return captured


def test_check_does_not_fail_required_when_run_acceptance_in_check_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`require_acceptance = true` is gated to ci unless `run_acceptance_in_check = true`."""
    _write_require_acceptance_check_project(tmp_path, run_acceptance_in_check=False)

    descriptions = _capture_check_parallel_descriptions(tmp_path, monkeypatch)

    assert "Acceptance (required)" not in descriptions
    assert "Acceptance (pytest-bdd)" not in descriptions


def test_check_appends_required_failure_when_both_flags_true(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both flags on + missing features/ → check enforces the required failure task."""
    _write_require_acceptance_check_project(tmp_path, run_acceptance_in_check=True)

    descriptions = _capture_check_parallel_descriptions(tmp_path, monkeypatch)

    assert "Acceptance (required)" in descriptions


def test_check_appends_required_failure_when_behavior_coverage_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_require_acceptance_check_project(tmp_path, run_acceptance_in_check=True)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'name = "check-req-acc"', 'name = "interlocks"'
        )
        + 'features_dir = "tests/features"\n',
        encoding="utf-8",
    )
    features = tmp_path / "tests" / "features"
    features.mkdir(parents=True)
    (features / "smoke.feature").write_text(
        "Feature: smoke\n  Scenario: it works\n    Given a thing\n",
        encoding="utf-8",
    )

    descriptions = _capture_check_parallel_descriptions(tmp_path, monkeypatch)

    assert "Acceptance (required)" in descriptions
    assert "Acceptance (pytest-bdd)" not in descriptions


def test_check_test_gate_ignores_pytest_bdd_targets_when_acceptance_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_require_acceptance_check_project(tmp_path, run_acceptance_in_check=True)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            "require_acceptance = true", "require_acceptance = false"
        )
        + 'features_dir = "tests/features"\ntest_runner = "pytest"\n',
        encoding="utf-8",
    )
    (tmp_path / "tests" / "features").mkdir(parents=True)
    (tmp_path / "tests" / "features" / "smoke.feature").write_text(
        "Feature: smoke\n  Scenario: it works\n    Given a thing\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "step_defs").mkdir()
    (tmp_path / "tests" / "step_defs" / "test_smoke.py").write_text("", encoding="utf-8")

    tasks = _capture_check_parallel_tasks(tmp_path, monkeypatch)
    by_description = {task.description: task for task in tasks}

    assert "Acceptance (pytest-bdd)" in by_description
    test_task = by_description["Run tests"]
    assert "--ignore=tests/features" in test_task.cmd
    assert "--ignore=tests/step_defs" in test_task.cmd


def test_check_test_gate_ignores_collected_property_dir_when_properties_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "tests" / "properties").mkdir(parents=True)
    (tmp_path / "tests" / "properties" / "test_lengths.py").write_text(
        "def test_property_placeholder() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "check-properties"
            version = "0.0.0"

            [tool.interlocks]
            test_runner = "pytest"
            properties_dir = "tests/properties"
            run_properties_in_check = true
            """
        ),
        encoding="utf-8",
    )
    stub_project_venv(tmp_path)

    tasks = _capture_check_parallel_tasks(tmp_path, monkeypatch)
    by_description = {task.description: task for task in tasks}

    assert "Property tests" in by_description
    test_task = by_description["Run tests"]
    assert "--ignore=tests/properties" in test_task.cmd


def test_check_test_gate_keeps_root_property_dir_when_not_collected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "properties").mkdir()
    (tmp_path / "properties" / "test_lengths.py").write_text(
        "def test_property_placeholder() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "check-properties"
            version = "0.0.0"

            [tool.interlocks]
            test_runner = "pytest"
            run_properties_in_check = true
            """
        ),
        encoding="utf-8",
    )
    stub_project_venv(tmp_path)

    tasks = _capture_check_parallel_tasks(tmp_path, monkeypatch)
    by_description = {task.description: task for task in tasks}

    assert "Property tests" in by_description
    test_task = by_description["Run tests"]
    assert "--ignore=properties" not in test_task.cmd


def test_check_skips_dependency_gates_without_project_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-uv project, no .venv: typecheck + test skip with a nudge, not false negatives.

    The skip is now driven by the per-task builders (task_typecheck declines,
    _test_task short-circuits) — the old stage-level guard in
    check._parallel_tasks was deleted. The observable outcome is unchanged.
    """
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "no-env"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    # deliberately no stub_project_venv() — this is the cold-start state

    descriptions = _capture_check_parallel_descriptions(tmp_path, monkeypatch)

    assert descriptions == []
    assert "no project environment" in capsys.readouterr().out


def test_check_fails_when_tests_fail(tmp_project: Path) -> None:
    failing = textwrap.dedent(
        '''\
        """Failing test."""

        import unittest


        class TestBroken(unittest.TestCase):
            def test_broken(self) -> None:
                self.assertEqual(1, 2)
        '''
    )
    (tmp_project / "tests" / "test_add.py").write_text(failing, encoding="utf-8")

    result = _run_check(tmp_project)

    assert result.returncode != 0
    # Failure dump runs from `finally` — verdict line plus the failing-row are preserved.
    out = result.stdout
    assert "[test]" in out
    assert "check: FAILED — " in out
