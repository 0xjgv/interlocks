"""Integration tests for `interlocks ci` (format_check, lint, complexity, typecheck, coverage)."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

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

    [tool.coverage.run]
    source = ["interlocks"]
    branch = true

    [tool.coverage.report]
    fail_under = 80
    show_missing = true
    """
)

_INIT_SRC = '"""Tmp project package."""\n\nfrom interlocks.core import add\n\n__all__ = ["add"]\n'

_SRC = textwrap.dedent(
    '''\
    """Tiny module — fully covered by tests."""


    def add(a: int, b: int) -> int:
        return a + b
    '''
)

_TEST_SRC = textwrap.dedent(
    '''\
    """Tiny test — exercises the full module."""

    import unittest

    from interlocks.core import add


    class TestAdd(unittest.TestCase):
        def test_add(self) -> None:
            self.assertEqual(add(2, 3), 5)
    '''
)

_UNFORMATTED_SRC = "def add(a: int, b:int)->int:\n    return a+b\n"

_LINT_BAD_SRC = textwrap.dedent(
    '''\
    """Dirty."""

    import os


    def add(a: int, b: int) -> int:
        return a + b
    '''
)


@pytest.fixture
def tmp_project(make_tmp_project: TmpProjectFactory) -> Path:
    return make_tmp_project(
        pyproject=_PYPROJECT,
        src_files={
            "interlocks/__init__.py": _INIT_SRC,
            "interlocks/core.py": _SRC,
        },
        test_files={
            "__init__.py": "",
            "test_add.py": _TEST_SRC,
        },
    )


def _run_ci(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "ci"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ci_passes_on_clean_project(tmp_project: Path) -> None:
    result = _run_ci(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = result.stdout
    # Minimal-default: only the verdict line; chrome lives behind --verbose.
    assert out.strip().splitlines()[-1].startswith("ci: ok — ")
    assert (tmp_project / ".coverage").exists()


def test_ci_passes_verbose(tmp_project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "ci", "--verbose"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    out = result.stdout
    import re as _re

    assert _re.search(r"interlocks v\d", out)
    for marker in ("CI Checks", "[format]", "[lint]", "[complexity]", "[typecheck]"):
        assert marker in out, f"missing marker {marker!r}\n{out}"
    assert "[coverage]" in out
    assert "Completed in" in out
    assert "ci: ok — " in out


@pytest.mark.parametrize(
    ("dirty_src", "expected_fragment"),
    [
        (_UNFORMATTED_SRC, "Format check"),
        (_LINT_BAD_SRC, "Lint check"),
    ],
    ids=["format", "lint"],
)
def test_ci_fails_on_violation(tmp_project: Path, dirty_src: str, expected_fragment: str) -> None:
    (tmp_project / "interlocks" / "core.py").write_text(dirty_src, encoding="utf-8")

    result = _run_ci(tmp_project)

    assert result.returncode != 0
    assert expected_fragment in result.stdout


def test_ci_writes_runtime_evidence(tmp_project: Path) -> None:
    result = _run_ci(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    data = json.loads((tmp_project / ".interlocks" / "ci.json").read_text(encoding="utf-8"))
    assert data["command"] == "interlocks ci"
    assert data["passed"] is True
    assert data["elapsed_seconds"] > 0


def _run_ci_json(cwd: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "ci", "--json", *extra],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ci_json_is_parseable(tmp_project: Path) -> None:
    result = _run_ci_json(tmp_project)

    payload = json.loads(result.stdout)
    assert payload["command"] == "ci"
    assert isinstance(payload["passed"], bool)
    assert isinstance(payload["elapsed_seconds"], (int, float))
    assert isinstance(payload["gates"], list)
    for gate in payload["gates"]:
        assert {"name", "label", "status", "elapsed_seconds"} <= gate.keys()
    assert isinstance(payload["skipped"], list)
    assert payload["evidence_path"].endswith("ci.json")


def test_ci_json_exit_code_matches_human_mode(tmp_project: Path) -> None:
    # Exit-code parity: --json is a rendering mode, never a verdict change.
    assert _run_ci(tmp_project).returncode == _run_ci_json(tmp_project).returncode


def test_ci_json_dominates_verbose(tmp_project: Path) -> None:
    # --json --verbose emits exactly one JSON object — no chrome, no streamed rows.
    result = _run_ci_json(tmp_project, "--verbose")
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one object, got {result.stdout!r}"
    assert json.loads(lines[0])["command"] == "ci"


# A high-complexity, fully-uncovered function — CRAP = ccn^2 * (1-cov)^3 + ccn
# is far above the default 30.0 ceiling, so the CRAP gate reaches `_print_offender`.
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


def test_ci_json_single_object_with_crap_offenders(tmp_project: Path) -> None:
    """Regression: an offender in the CRAP gate must not leak `CRAP=` lines to stdout.

    Before the fix, `_print_offender` printed raw text before the JSON object, so
    `json.loads(stdout)` failed on any project with CRAP offenders.
    """
    (tmp_project / "interlocks" / "core.py").write_text(_CRAP_OFFENDER_SRC, encoding="utf-8")

    result = _run_ci_json(tmp_project)

    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one JSON object, got {result.stdout!r}"
    payload = json.loads(lines[0])
    assert payload["command"] == "ci"
    assert "CRAP=" not in result.stdout


def test_ci_evidence_records_context_env(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``INTERLOCKS_CI_CONTEXT`` set in the workflow env lands in ci.json."""
    monkeypatch.setenv("INTERLOCKS_CI_CONTEXT", "main_push")
    result = _run_ci(tmp_project)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    data = json.loads((tmp_project / ".interlocks" / "ci.json").read_text(encoding="utf-8"))
    assert data["context"] == "main_push"


def test_ci_in_process_queues_all_tasks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stub run_tasks + inline gates — verify cmd_ci composes the expected task list
    plus the sequential post-coverage gates."""
    from interlocks.config import load_config
    from interlocks.stages import ci as ci_mod

    parallel: list[str] = []
    sequential: list[str] = []
    monkeypatch.setattr(
        ci_mod, "run_tasks", lambda tasks: parallel.extend(t.description for t in tasks)
    )
    monkeypatch.setattr(ci_mod, "cmd_crap", lambda: sequential.append("CRAP"))
    monkeypatch.setattr(
        ci_mod,
        "cmd_behavior_attribution",
        lambda refresh=False: sequential.append(f"Attribution:{refresh}"),
    )
    monkeypatch.setattr(ci_mod, "cmd_mutation", lambda **_kw: sequential.append("Mutation"))

    ci_mod.cmd_ci()

    cfg = load_config()
    assert parallel == [
        "Format check",
        "Lint check",
        "Complexity (lizard)",
        "Dep audit",
        "Deps (deptry)",
        "Type check",
        f"Coverage >= {cfg.coverage_min}%",
        "Architecture (import-linter)",
        "Acceptance (pytest-bdd)",
    ]
    expected_sequential = ["CRAP", "Attribution:False"] + (
        ["Mutation"] if cfg.run_mutation_in_ci else []
    )
    assert sequential == expected_sequential
    assert "CI Checks" in capsys.readouterr().out


def test_ci_skip_coverage_warns_and_skips_crap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "ci-skip"
            version = "0.0.0"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci", "--skip=coverage"])

    from interlocks.stages import ci as ci_mod

    sequential: list[str] = []
    monkeypatch.setattr(ci_mod, "run_tasks", lambda tasks: None)
    monkeypatch.setattr(ci_mod, "cmd_crap", lambda: sequential.append("CRAP"))
    monkeypatch.setattr(
        ci_mod,
        "cmd_behavior_attribution",
        lambda refresh=False: sequential.append(f"Attribution:{refresh}"),
    )
    monkeypatch.setattr(ci_mod, "cmd_mutation", lambda **_kw: sequential.append("Mutation"))

    ci_mod.cmd_ci()

    assert sequential == ["Attribution:False"]
    out = capsys.readouterr().out
    assert "skips active" in out
    assert "crap: skipped by global skip policy" in out
    assert "coverage was skipped" in out


def test_ci_skips_typecheck_and_coverage_without_project_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-uv project, no .venv: ci skips typecheck/coverage, runs the rest, exits 0."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "ci-no-env"
            version = "0.0.0"
            requires-python = ">=3.11"
            """
        ),
        encoding="utf-8",
    )
    # deliberately no stub_project_venv() and no uv.lock — cold-start state
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci"])

    from interlocks.stages import ci as ci_mod

    parallel: list[str] = []
    monkeypatch.setattr(
        ci_mod, "run_tasks", lambda tasks: parallel.extend(t.description for t in tasks)
    )
    monkeypatch.setattr(ci_mod, "cmd_crap", lambda: None)
    monkeypatch.setattr(ci_mod, "cmd_behavior_attribution", lambda refresh=False: None)
    monkeypatch.setattr(ci_mod, "cmd_mutation", lambda **_kw: None)

    ci_mod.cmd_ci()  # must not raise SystemExit

    assert "Type check" not in parallel
    assert not any(d.startswith("Coverage >=") for d in parallel)
    # env-independent gates still queued
    assert "Format check" in parallel
    assert "Lint check" in parallel
    assert "Dep audit" in parallel
    assert "Deps (deptry)" in parallel
    out = capsys.readouterr().out
    assert "typecheck: skipped — no project environment" in out
    assert "coverage: skipped — no project environment" in out


def test_ci_writes_failing_runtime_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "ci-evidence"
            version = "0.0.0"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci"])

    from interlocks.stages import ci as ci_mod

    def fail_tasks(_tasks: object) -> None:
        raise SystemExit(7)

    monkeypatch.setattr(ci_mod, "run_tasks", fail_tasks)

    with pytest.raises(SystemExit) as exc:
        ci_mod.cmd_ci()

    assert exc.value.code == 7
    data = json.loads((tmp_path / ".interlocks" / "ci.json").read_text(encoding="utf-8"))
    assert data["passed"] is False


@pytest.mark.parametrize(
    ("failing_gate", "interlocks_config"),
    [
        ("crap", ""),
        ("attribution", ""),
        ("mutation", 'mutation_ci_mode = "full"\n'),
    ],
    ids=["crap", "attribution", "mutation"],
)
def test_ci_reports_sequential_gate_failure_in_verdict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failing_gate: str,
    interlocks_config: str,
) -> None:
    (tmp_path / "tests").mkdir()
    tool_table = f"\n[tool.interlocks]\n{interlocks_config}" if interlocks_config else ""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "ci-post-gate"
            version = "0.0.0"
            {tool_table}
            """
        ),
        encoding="utf-8",
    )
    stub_project_venv(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci"])

    from interlocks.stages import ci as ci_mod

    def fail_if_gate(label: str) -> None:
        if label == failing_gate:
            raise SystemExit(1)

    monkeypatch.setattr(ci_mod, "run_tasks", lambda tasks: None)
    monkeypatch.setattr(ci_mod, "cmd_crap", lambda: fail_if_gate("crap"))
    monkeypatch.setattr(
        ci_mod,
        "cmd_behavior_attribution",
        lambda refresh=False: fail_if_gate("attribution"),
    )
    monkeypatch.setattr(ci_mod, "cmd_mutation", lambda **_kw: fail_if_gate("mutation"))

    with pytest.raises(SystemExit) as exc:
        ci_mod.cmd_ci()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert f"ci: FAILED — {failing_gate}" in out
    assert "ci: ok —" not in out
    data = json.loads((tmp_path / ".interlocks" / "ci.json").read_text(encoding="utf-8"))
    assert data["passed"] is False


def test_ci_in_process_includes_mutation_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`run_mutation_in_ci = true` → cmd_ci also runs cmd_mutation sequentially."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "ci-mut"
            version = "0.0.0"

            [tool.interlocks]
            run_mutation_in_ci = true
            """
        ),
        encoding="utf-8",
    )
    stub_project_venv(tmp_path)
    monkeypatch.chdir(tmp_path)

    from interlocks.stages import ci as ci_mod

    sequential: list[str] = []
    monkeypatch.setattr(ci_mod, "run_tasks", lambda tasks: None)
    monkeypatch.setattr(ci_mod, "cmd_crap", lambda: sequential.append("CRAP"))
    monkeypatch.setattr(
        ci_mod,
        "cmd_behavior_attribution",
        lambda refresh=False: sequential.append(f"Attribution:{refresh}"),
    )
    monkeypatch.setattr(ci_mod, "cmd_mutation", lambda **_kw: sequential.append("Mutation"))

    ci_mod.cmd_ci()
    assert sequential == ["CRAP", "Attribution:False", "Mutation"]


# ─────────────── mutation_ci_mode dispatch ─────────────────────


def _write_mode_project(tmp_path: Path, table: str) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "ci-mode"
            version = "0.0.0"

            [tool.interlocks]
            {table}
            """
        ),
        encoding="utf-8",
    )
    stub_project_venv(tmp_path)


@pytest.mark.parametrize(
    ("table", "expected_sequential", "expected_changed_only"),
    [
        ('mutation_ci_mode = "off"', ["CRAP", "Attribution:False"], None),
        ('mutation_ci_mode = "full"', ["CRAP", "Attribution:False", "Mutation"], False),
        (
            'mutation_ci_mode = "incremental"',
            ["CRAP", "Attribution:False", "Mutation"],
            True,
        ),
        ("run_mutation_in_ci = true", ["CRAP", "Attribution:False", "Mutation"], False),
    ],
    ids=["off", "full", "incremental", "legacy-bool"],
)
def test_ci_mode_dispatches_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    table: str,
    expected_sequential: list[str],
    expected_changed_only: bool | None,
) -> None:
    """Verify mode → mutation invocation: skip / full / incremental / legacy boolean."""
    _write_mode_project(tmp_path, table)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci"])

    from interlocks.stages import ci as ci_mod

    sequential: list[str] = []
    captured_kwargs: list[dict[str, object]] = []
    monkeypatch.setattr(ci_mod, "run_tasks", lambda tasks: None)
    monkeypatch.setattr(ci_mod, "cmd_crap", lambda: sequential.append("CRAP"))
    monkeypatch.setattr(
        ci_mod,
        "cmd_behavior_attribution",
        lambda refresh=False: sequential.append(f"Attribution:{refresh}"),
    )

    def fake_mutation(**kwargs: object) -> None:
        sequential.append("Mutation")
        captured_kwargs.append(kwargs)

    monkeypatch.setattr(ci_mod, "cmd_mutation", fake_mutation)

    ci_mod.cmd_ci()

    assert sequential == expected_sequential
    if expected_changed_only is None:
        assert captured_kwargs == []
    else:
        assert captured_kwargs == [{"changed_only": expected_changed_only}]


# ─────────────── require_acceptance integration in CI ─────────────────────


def _write_require_acceptance_project(tmp_path: Path, *, body: str = "") -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "ci-req-acc"
            version = "0.0.0"

            [tool.interlocks]
            require_acceptance = true
            {body}
            """
        ),
        encoding="utf-8",
    )
    # env-ready: the acceptance gate is dependency-aware and skips without a venv
    stub_project_venv(tmp_path)


def _capture_ci_task_descriptions(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from interlocks.stages import ci as ci_mod

    captured: list[str] = []
    monkeypatch.setattr(
        ci_mod, "run_tasks", lambda tasks: captured.extend(t.description for t in tasks)
    )
    monkeypatch.setattr(ci_mod, "cmd_crap", lambda: None)
    monkeypatch.setattr(ci_mod, "cmd_mutation", lambda **_kw: None)
    ci_mod.cmd_ci()
    return captured


def test_ci_appends_required_failure_task_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_require_acceptance_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci"])

    descriptions = _capture_ci_task_descriptions(monkeypatch)

    assert "Acceptance (required)" in descriptions
    assert "Acceptance (pytest-bdd)" not in descriptions


def test_ci_runs_acceptance_when_runnable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_require_acceptance_project(tmp_path)
    features = tmp_path / "tests" / "features"
    features.mkdir()
    (features / "smoke.feature").write_text(
        "Feature: smoke\n  Scenario: it works\n    Given a thing\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci"])

    descriptions = _capture_ci_task_descriptions(monkeypatch)

    assert "Acceptance (pytest-bdd)" in descriptions
    assert "Acceptance (required)" not in descriptions


def test_ci_appends_required_failure_task_when_behavior_coverage_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_require_acceptance_project(
        tmp_path,
        body='features_dir = "tests/features"\n',
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'name = "ci-req-acc"', 'name = "interlocks"'
        ),
        encoding="utf-8",
    )
    features = tmp_path / "tests" / "features"
    features.mkdir(parents=True)
    (features / "smoke.feature").write_text(
        "Feature: smoke\n  Scenario: it works\n    Given a thing\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci"])

    descriptions = _capture_ci_task_descriptions(monkeypatch)

    assert "Acceptance (required)" in descriptions
    assert "Acceptance (pytest-bdd)" not in descriptions


def test_ci_skips_acceptance_when_optional_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Default policy (`require_acceptance = false`) + missing features/ → silent skip."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "ci-default-acc"
            version = "0.0.0"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "ci"])

    descriptions = _capture_ci_task_descriptions(monkeypatch)

    assert "Acceptance (required)" not in descriptions
    assert "Acceptance (pytest-bdd)" not in descriptions
