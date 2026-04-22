"""Integration test for `harness audit` (pip-audit on deps)."""

from __future__ import annotations

import subprocess  # noqa: S404 — test harness invokes the CLI
import sys
import textwrap
from pathlib import Path

import pytest

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "audit-probe"
    version = "0.0.1"
    requires-python = ">=3.13"
    dependencies = []

    [build-system]
    requires = ["setuptools>=61"]
    build-backend = "setuptools.build_meta"
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Minimal project with no deps — pip-audit has nothing to scan."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    return tmp_path


@pytest.mark.slow
def test_audit_clean_deps_passes(tmp_project: Path) -> None:
    """pip-audit against a project with no deps should report no vulnerabilities."""
    result = subprocess.run(
        [sys.executable, "-m", "harness.cli", "audit"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    # Either clean exit, or — if the index is unreachable — the known-safe message.
    assert result.returncode == 0 or "No known vulnerabilities" in output, (
        f"audit failed unexpectedly: rc={result.returncode}\n{output}"
    )
