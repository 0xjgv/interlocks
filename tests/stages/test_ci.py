"""Integration tests for `interlocks ci` (format_check, lint, complexity, typecheck, coverage)."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.conftest import TmpProjectFactory

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "tmpproj"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.ruff]
    target-version = "py313"
    line-length = 99

    [tool.ruff.lint]
    select = ["E", "F", "I"]

    [tool.basedpyright]
    pythonVersion = "3.13"
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
    markers = ("interlocks v", "CI Checks", "[format]", "[lint]", "[complexity]", "[typecheck]")
    for marker in markers:
        assert marker in out, f"missing marker {marker!r}\n{out}"
    assert "[coverage]" in out
    assert "Completed in" in out
    assert (tmp_project / ".coverage").exists()


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
