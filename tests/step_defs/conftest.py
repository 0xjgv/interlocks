"""Shared pytest-bdd fixtures for the interlocks acceptance suite."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

# Minimal tmp-project pyproject. `[tool.interlocks]` knobs are tuned so all four
# stages (check/pre-commit/ci/nightly) can run to green in-test without
# tripping thresholds or waiting on mutation for minutes.
_TMP_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "tmp"
    version = "0"
    requires-python = ">=3.13"

    [dependency-groups]
    dev = ["pytest>=9"]

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
    source = ["src/tmp"]
    branch = true

    [tool.coverage.report]
    fail_under = 0
    show_missing = true

    [tool.interlocks]
    src_dir = "src/tmp"
    test_dir = "tests"
    coverage_min = 0
    crap_max = 1000.0
    enforce_crap = false
    # Cap nightly mutation wall time so the scenario completes quickly.
    mutation_max_runtime = 5
    mutation_min_coverage = 100.0
    mutation_min_score = 0.0
    """
)


_FLAT_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "tmp"
    version = "0"
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
    branch = true

    [tool.coverage.report]
    fail_under = 0

    [tool.interlocks]
    coverage_min = 0
    crap_max = 1000.0
    enforce_crap = false
    """
)


def make_flat_tmp_project(tmp_path: Path) -> Path:
    """Materialize a flat-layout tmp project (no ``src/`` subdir).

    Used to exercise ``--changed`` scoping when ``src_dir == "."`` — the case
    where partial-adoption / un-configured repos live, and the case the prefix
    bug regressed against.
    """
    (tmp_path / "pyproject.toml").write_text(_FLAT_PYPROJECT, encoding="utf-8")
    (tmp_path / "main.py").write_text(
        '"""Top-level module."""\n\n\ndef hello() -> str:\n    return "hi"\n',
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text(
        '"""Trivial passing test."""\n\n\ndef test_ok() -> None:\n    assert True\n',
        encoding="utf-8",
    )
    return tmp_path


def make_tmp_project(tmp_path: Path) -> Path:
    """Materialize a minimal clean project under ``tmp_path``.

    Structure:
      - pyproject.toml (with `[tool.interlocks]` threshold overrides)
      - src/tmp/__init__.py
      - tests/test_ok.py (a single `def test_ok(): assert True`)

    ``tests/`` is deliberately *not* a Python package — that keeps the
    default ``interlocks arch`` contract (src ↛ tests) dormant, so the tmp
    project's ``ci`` stage doesn't need ``src/`` on ``PYTHONPATH`` for
    import-linter to resolve ``tmp``.
    """
    (tmp_path / "pyproject.toml").write_text(_TMP_PYPROJECT, encoding="utf-8")
    src_pkg = tmp_path / "src" / "tmp"
    src_pkg.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text('"""Tmp package."""\n', encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text(
        '"""Trivial passing test."""\n\n\ndef test_ok() -> None:\n    assert True\n',
        encoding="utf-8",
    )
    return tmp_path


def run_interlock_in_cwd(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m interlocks.cli <args>`` with ``cwd`` as project root.

    Mirrors the ``_run_interlock`` fixture in ``test_interlock_cli.py`` but lets the
    caller pin ``cwd`` — required for stage scenarios that operate on an inline
    tmp project instead of the interlocks repo itself.
    """
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
