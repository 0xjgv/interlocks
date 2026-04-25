"""Step defs for tests/features/interlock_tasks.feature.

Each scenario builds a minimal self-contained project on tmp_path and shells
out to `python -m interlock.cli <task>` — same entry point the installed CLI
uses — so the feature file acts as a behavioral guardrail on each task's
exit-code + output shape.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_tasks.feature"))


# ─────────────── layout builders ─────────────────────

_AUDIT_PYPROJECT = textwrap.dedent(
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

_DEPS_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "deps-probe"
    version = "0.0.1"
    requires-python = ">=3.13"
    dependencies = ["requests>=2"]

    [build-system]
    requires = ["setuptools>=61"]
    build-backend = "setuptools.build_meta"
    """
)

_ARCH_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "arch-probe"
    version = "0.0.1"
    requires-python = ">=3.13"
    dependencies = []

    [build-system]
    requires = ["setuptools>=61"]
    build-backend = "setuptools.build_meta"

    [tool.interlock]
    src_dir = "arch_probe"
    test_dir = "tests"
    """
)

_COV_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "cov-probe"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.coverage.report]
    show_missing = true
    """
)

_CRAP_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "crap-probe"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.coverage.report]
    show_missing = true
    """
)

_MUTATION_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "mut-probe"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.interlock]
    mutation_max_runtime = 5

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.mutmut]
    paths_to_mutate = ["mypkg/"]
    tests_dir = ["tests/"]
    """
)

_TRIVIAL_MODULE = "def double(x):\n    return x * 2\n"
_TRIVIAL_TEST = textwrap.dedent(
    """\
    import unittest
    from mypkg.mod import double

    class TestDouble(unittest.TestCase):
        def test_double(self):
            self.assertEqual(double(3), 6)
    """
)


def _make_audit(root: Path) -> None:
    (root / "pyproject.toml").write_text(_AUDIT_PYPROJECT, encoding="utf-8")


def _make_deps(root: Path) -> None:
    (root / "pyproject.toml").write_text(_DEPS_PYPROJECT, encoding="utf-8")
    pkg = root / "deps_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Minimal package."""\n', encoding="utf-8")
    (pkg / "core.py").write_text(
        "import os\n\nHOME = os.environ.get('HOME', '')\n", encoding="utf-8"
    )


def _make_arch(root: Path) -> None:
    (root / "pyproject.toml").write_text(_ARCH_PYPROJECT, encoding="utf-8")
    src = root / "arch_probe"
    src.mkdir()
    (src / "__init__.py").write_text('"""Src package."""\n', encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text('"""Tests package."""\n', encoding="utf-8")


def _make_trivial_package(root: Path, pyproject: str) -> None:
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    pkg = root / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_TRIVIAL_MODULE, encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text(_TRIVIAL_TEST, encoding="utf-8")


def _make_coverage(root: Path) -> None:
    _make_trivial_package(root, _COV_PYPROJECT)


def _make_crap(root: Path) -> None:
    """Crap needs `.coverage` on disk before the gate runs."""
    _make_trivial_package(root, _CRAP_PYPROJECT)
    subprocess.run(
        [sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _make_mutation(root: Path) -> None:
    _make_trivial_package(root, _MUTATION_PYPROJECT)


_LAYOUTS = {
    "audit": _make_audit,
    "deps": _make_deps,
    "arch": _make_arch,
    "coverage": _make_coverage,
    "crap": _make_crap,
    "mutation": _make_mutation,
}


@dataclass(frozen=True)
class CliResult:
    rc: int
    output: str


# ─────────────── Given/When/Then ─────────────────────


@given(parsers.parse('a tmp project with layout "{layout}"'), target_fixture="project_root")
def _tmp_project(layout: str, tmp_path: Path) -> Path:
    _LAYOUTS[layout](tmp_path)
    return tmp_path


@when(parsers.parse('I run "{cmd}" in that project'), target_fixture="cli_result")
def _run_in_project(cmd: str, project_root: Path) -> CliResult:
    # cmd starts with "interlock <subcmd> …"; drop the "interlock" sentinel.
    _, *argv = cmd.split()
    result = subprocess.run(
        [sys.executable, "-m", "interlock.cli", *argv],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return CliResult(rc=result.returncode, output=result.stdout + result.stderr)


@then("the exit code is 0")
def _rc_zero(cli_result: CliResult) -> None:
    assert cli_result.rc == 0, f"rc={cli_result.rc}\n{cli_result.output}"


@then("the exit code is not 0")
def _rc_nonzero(cli_result: CliResult) -> None:
    assert cli_result.rc != 0, f"rc={cli_result.rc}\n{cli_result.output}"


@then(parsers.parse('the exit code is 0 or the output mentions "{needle}"'))
def _rc_zero_or_output(needle: str, cli_result: CliResult) -> None:
    assert cli_result.rc == 0 or needle in cli_result.output, (
        f"rc={cli_result.rc}\n{cli_result.output}"
    )


@then(parsers.parse('the output contains "{needle}"'))
def _output_contains(needle: str, cli_result: CliResult) -> None:
    assert needle in cli_result.output, f"expected {needle!r} in output; got:\n{cli_result.output}"
