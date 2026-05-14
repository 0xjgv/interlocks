"""Shared pytest-bdd fixtures for the interlocks acceptance suite."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.conftest import stub_project_venv

# Minimal tmp-project pyproject. `[tool.interlocks]` knobs are tuned so all four
# stages (check/pre-commit/ci/nightly) can run to green in-test without
# tripping thresholds or waiting on mutation for minutes.
_TMP_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "tmp"
    version = "0"
    requires-python = ">=3.11"

    [dependency-groups]
    dev = ["pytest>=9"]

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
    stub_project_venv(tmp_path)
    return tmp_path


_LEGACY_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "legacy"
    version = "0"
    requires-python = ">=3.11"

    [tool.ruff]
    target-version = "py311"
    line-length = 99

    [tool.ruff.lint]
    select = ["E", "F", "I", "W", "UP"]

    [tool.coverage.run]
    source = ["src/legacy"]
    branch = true

    [tool.coverage.report]
    fail_under = 0

    [tool.interlocks]
    src_dir = "src/legacy"
    test_dir = "tests"
    coverage_min = 0
    crap_max = 1000.0
    enforce_crap = false
    skip = ["audit", "deps"]
    """
)

_LEGACY_CLEAN_VIEWS = '"""Views."""\n'
_LEGACY_CLEAN_ADMIN = '"""Admin."""\n'
# Combined I001 (unsorted) + F401 (unused json) + UP007 (Optional) + W292
# (no trailing newline). Exercises the mixed-violation pattern from spec §1.
_LEGACY_DIRTY_VIEWS = (
    "import sys\n"
    "import os\n"
    "import json\n"
    "from typing import Optional\n"
    "\n"
    "def fetch(x: Optional[int]) -> int:\n"
    "    print(sys.version, os.name)\n"
    "    return x or 0"
)
# I001 in the admin-path risk zone (spec §10.2, +4 risk).
_LEGACY_DIRTY_ADMIN = (
    "import sys\nimport os\n\ndef register() -> None:\n    print(sys.version, os.name)\n"
)


def make_legacy_greenfield_project(tmp_path: Path, *, dirty: bool = True) -> Path:
    """Materialize a legacy greenfield project (spec §1 reproduction).

    Seeds an unadopted-codebase layout: minimal ``[tool.interlocks]`` (no
    preset, no thresholds tightened), a source module with mixed violations
    (I001 + F401 + UP007 + W292), an ``admin.py`` in the path-risk zone
    (spec §10.2, +4), a trivial smoke test, and a git repo with a clean
    baseline commit followed by an uncommitted "dirty" overwrite — so
    ``--base=HEAD`` resolves and the harness sees the violations as the
    candidate diff for ``fix-plan`` / ``fix-rule`` / ``fix-optimize``.

    ``audit`` and ``deps`` are skipped via ``[tool.interlocks].skip`` so
    ``interlocks check`` stays deterministic without network access.

    Pass ``dirty=False`` to leave the working tree matching HEAD — the
    "no candidates" baseline used by ``fix-optimize`` empty-plan tests.
    """
    project = tmp_path
    (project / "pyproject.toml").write_text(_LEGACY_PYPROJECT, encoding="utf-8")
    src = project / "src" / "legacy"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('"""Legacy package."""\n', encoding="utf-8")
    (src / "views.py").write_text(_LEGACY_CLEAN_VIEWS, encoding="utf-8")
    (src / "admin.py").write_text(_LEGACY_CLEAN_ADMIN, encoding="utf-8")
    tests = project / "tests"
    tests.mkdir()
    (tests / "test_smoke.py").write_text(
        '"""Smoke."""\n\n\ndef test_ok() -> None:\n    assert True\n',
        encoding="utf-8",
    )

    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)

    _git("init", "-q", "-b", "main")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "Test")
    _git("config", "commit.gpgsign", "false")
    _git("config", "core.hooksPath", "/dev/null")
    _git("add", "-A")
    _git("commit", "-q", "-m", "baseline")

    if dirty:
        (src / "views.py").write_text(_LEGACY_DIRTY_VIEWS, encoding="utf-8")
        (src / "admin.py").write_text(_LEGACY_DIRTY_ADMIN, encoding="utf-8")
    stub_project_venv(project)  # created post-commit — stays out of the baseline tree
    return project


def commit_legacy_dirty_state(project: Path, message: str = "introduce violations") -> None:
    """Stage and commit the current dirty state — used by fix-replay scenarios.

    Mirrors the per-commit "PR introduces a violation" pattern from
    ``test_lintfix_fix_replay.py::repo_with_history``. After this call
    ``git rev-list --first-parent -n1 main`` resolves to the new commit
    and the new commit's parent carries the clean baseline.
    """
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=project, check=True, capture_output=True
    )


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
    stub_project_venv(tmp_path)
    return tmp_path


def run_interlock_in_cwd(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m interlocks.cli <args>`` with ``cwd`` as project root.

    Used by every step-def that drives the CLI as a subprocess. Pass ``env``
    to override the inherited environment (e.g. crash-injection scenarios or
    PYTHONPATH augmentation via :func:`interlocks_pythonpath_env`).

    Injects ``--verbose`` so chrome-asserting Gherkin scenarios keep working
    under the new minimal-default polarity (rows/sections/footers). Scenarios
    that explicitly need to assert minimal output overwrite ``args`` themselves.
    """
    extra = ("--verbose",) if "--verbose" not in args and "--quiet" not in args else ()
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", *args, *extra],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def run_interlock_text(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run the CLI and return combined stdout+stderr.

    Convenience wrapper for scenarios that only assert on textual output.
    """
    result = run_interlock_in_cwd(cwd, *args, env=env)
    return result.stdout + result.stderr


def interlocks_pythonpath_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environ dict with the in-tree interlocks package on PYTHONPATH.

    Subprocess probes need this when an outer interpreter's site-packages
    might shadow the in-tree source — same concern flagged in
    ``test_preflight.py`` and ``test_doctor.py``.
    """
    import interlocks  # local to keep module-import cheap

    env = dict(base) if base is not None else os.environ.copy()
    pkg_root = str(Path(interlocks.__file__).resolve().parent.parent)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{pkg_root}{os.pathsep}{existing}" if existing else pkg_root
    return env
