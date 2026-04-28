"""Step defs for tests/features/interlock_tasks.feature.

Each scenario builds a minimal self-contained project on tmp_path and shells
out to `python -m interlocks.cli <task>` — same entry point the installed CLI
uses — so the feature file acts as a behavioral guardrail on each task's
exit-code + output shape.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from interlocks.behavior_coverage import INTERLOCKS_REGISTRY

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

    [tool.interlocks]
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

    [tool.interlocks]
    mutation_max_runtime = 5

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.mutmut]
    paths_to_mutate = ["mypkg/"]
    tests_dir = ["tests/"]
    """
)

# `mutation_min_coverage = 0` bypasses the suite-coverage gate; the layout has
# no git repo, so `git diff` returns empty stdout and the task hits the
# changed-files skip cleanly without invoking mutmut.
_MUTATION_INCREMENTAL_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "mut-probe"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.interlocks]
    mutation_max_runtime = 5
    mutation_min_coverage = 0
    mutation_since_ref = "HEAD"

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


def _make_mutation_incremental_empty(root: Path) -> None:
    """Incremental mutation with primed coverage and an empty diff → clean skip."""
    _make_trivial_package(root, _MUTATION_INCREMENTAL_PYPROJECT)
    subprocess.run(
        [sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"],
        cwd=root,
        check=True,
        capture_output=True,
    )


_REQUIRE_ACCEPTANCE_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "req-acc-probe"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.interlocks]
    require_acceptance = true
    """
)

_INTERLOCKS_REQUIRE_ACCEPTANCE_PYPROJECT = _REQUIRE_ACCEPTANCE_PYPROJECT.replace(
    'name = "req-acc-probe"', 'name = "interlocks"'
)


_FEATURE_STEP_DEFS = textwrap.dedent(
    """\
    from pytest_bdd import given, scenarios

    scenarios("../features/behavior.feature")

    @given("a thing")
    def _thing():
        return None
    """
)


def _make_require_acceptance_no_features(root: Path) -> None:
    """`require_acceptance = true` but no `tests/features/` — `acceptance` must fail."""
    (root / "pyproject.toml").write_text(_REQUIRE_ACCEPTANCE_PYPROJECT, encoding="utf-8")
    (root / "tests").mkdir()


def _make_require_acceptance_behavior(
    root: Path, *, omit: str | None = None, extra: str | None = None
) -> None:
    (root / "pyproject.toml").write_text(
        _INTERLOCKS_REQUIRE_ACCEPTANCE_PYPROJECT, encoding="utf-8"
    )
    features = root / "tests" / "features"
    features.mkdir(parents=True)
    markers = [
        f"  # req: {behavior.behavior_id}\n"
        for behavior in INTERLOCKS_REGISTRY.behaviors
        if behavior.behavior_id != omit
    ]
    if extra is not None:
        markers.append(f"  # req: {extra}\n")
    feature = (
        "Feature: behavior coverage\n\n"
        + "".join(markers)
        + ("  Scenario: behavior coverage\n    Given a thing\n")
    )
    (features / "behavior.feature").write_text(feature, encoding="utf-8")
    step_defs = root / "tests" / "step_defs"
    step_defs.mkdir()
    (step_defs / "test_behavior.py").write_text(_FEATURE_STEP_DEFS, encoding="utf-8")


def _make_require_acceptance_behavior_covered(root: Path) -> None:
    _make_require_acceptance_behavior(root)


def _make_require_acceptance_behavior_uncovered(root: Path) -> None:
    _make_require_acceptance_behavior(root, omit="task-acceptance-behavior-uncovered")


def _make_require_acceptance_behavior_stale(root: Path) -> None:
    _make_require_acceptance_behavior(root, extra="task-removed-behavior")


def _make_require_acceptance_trace_advisory(root: Path) -> None:
    _make_require_acceptance_behavior(root)


_LAYOUTS = {
    "audit": _make_audit,
    "deps": _make_deps,
    "arch": _make_arch,
    "coverage": _make_coverage,
    "crap": _make_crap,
    "mutation": _make_mutation,
    "mutation-incremental-empty": _make_mutation_incremental_empty,
    "require-acceptance-no-features": _make_require_acceptance_no_features,
    "require-acceptance-behavior-covered": _make_require_acceptance_behavior_covered,
    "require-acceptance-behavior-uncovered": _make_require_acceptance_behavior_uncovered,
    "require-acceptance-behavior-stale": _make_require_acceptance_behavior_stale,
    "require-acceptance-trace-advisory": _make_require_acceptance_trace_advisory,
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
    # cmd starts with "interlocks <subcmd> …"; drop the "interlocks" sentinel.
    _, *argv = cmd.split()
    env = None
    if (
        project_root
        .joinpath("pyproject.toml")
        .read_text(encoding="utf-8")
        .find('name = "interlocks"')
        >= 0
    ):
        env = {**os.environ, "INTERLOCKS_ACCEPTANCE_TRACE": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", *argv],
        cwd=project_root,
        env=env,
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
