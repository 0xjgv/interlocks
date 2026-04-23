"""Step defs for tests/features/harness_meta.feature.

Exercises the meta commands (`acceptance`, `init-acceptance`, `setup-hooks`)
end-to-end against a throwaway tmp project. Each scenario gets its own
project directory so state cannot leak between them.

Per-file helpers only — no shared conftest fixture.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/harness_meta.feature")


_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "meta-probe"
    version = "0.0.0"
    requires-python = ">=3.13"
    """
)


def _run_harness(project: Path, subcmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *subcmd.split()],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Throwaway project rooted at tmp_path with a minimal pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    return tmp_path


@pytest.fixture
def cli_results() -> list[subprocess.CompletedProcess[str]]:
    """Collected results across repeated runs within a scenario."""
    return []


@given("a tmp project with no features directory", target_fixture="project")
def _project_no_features(tmp_project: Path) -> Path:
    assert not (tmp_project / "features").exists()
    assert not (tmp_project / "tests" / "features").exists()
    return tmp_project


@given("a tmp project without tests/features/", target_fixture="project")
def _project_without_tests_features(tmp_project: Path) -> Path:
    assert not (tmp_project / "tests" / "features").exists()
    return tmp_project


@given("a tmp project with a .git directory", target_fixture="project")
def _project_with_git(tmp_project: Path) -> Path:
    (tmp_project / ".git" / "hooks").mkdir(parents=True)
    return tmp_project


@when(parsers.parse('I run "harness {subcmd}" in the tmp project'))
@when(parsers.parse('I run "harness {subcmd}" in the tmp project a second time'))
def _run_cmd(
    project: Path,
    subcmd: str,
    cli_results: list[subprocess.CompletedProcess[str]],
) -> None:
    cli_results.append(_run_harness(project, subcmd))


@then("the command exits successfully")
def _exits_success(cli_results: list[subprocess.CompletedProcess[str]]) -> None:
    result = cli_results[-1]
    assert result.returncode == 0, (
        f"expected exit 0; got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@then("the command exits with a non-zero status")
def _exits_nonzero(cli_results: list[subprocess.CompletedProcess[str]]) -> None:
    result = cli_results[-1]
    assert result.returncode != 0, (
        f"expected non-zero exit; got 0\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@then(parsers.parse('the file "{relpath}" exists in the tmp project'))
def _file_exists(project: Path, relpath: str) -> None:
    path = project / relpath
    assert path.is_file(), f"expected {path} to exist"


@then("the pre-commit hook exists in the tmp project")
def _pre_commit_exists(project: Path) -> None:
    hook = project / ".git" / "hooks" / "pre-commit"
    assert hook.is_file(), f"expected {hook} to exist"


@then("the pre-commit hook is executable")
def _pre_commit_executable(project: Path) -> None:
    hook = project / ".git" / "hooks" / "pre-commit"
    mode = hook.stat().st_mode
    assert mode & 0o111, f"expected executable bit on {hook}; mode={mode:o}"
