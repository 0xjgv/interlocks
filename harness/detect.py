"""Auto-detect the target project's test runner, source/test dirs, and invoker. Stdlib-only.

All helpers are pure — they take the pre-loaded ``pyproject`` dict and the discovered
``project_root`` — so ``harness/config.py`` owns discovery and caching.

Test-runner detection order (first match wins):
  1. Pytest config: ``[tool.pytest.*]``, ``pytest.ini``, ``pytest.cfg``, ``<test_dir>/conftest.py``
  2. ``pytest`` declared in project / dep-group / uv dependencies
  3. Pytest importable in the current interpreter
  4. Otherwise: unittest
"""

from __future__ import annotations

import importlib.util
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from harness.config import AcceptanceRunner, HarnessConfig, TestInvoker, TestRunner


_PYTEST_WORD = re.compile(r"(?<![A-Za-z0-9_-])pytest(?![A-Za-z0-9_-])")
_PYTEST_BDD_WORD = re.compile(r"(?<![A-Za-z0-9_-])pytest[-_]bdd(?![A-Za-z0-9_-])")
_BEHAVE_WORD = re.compile(r"(?<![A-Za-z0-9_-])behave(?![A-Za-z0-9_-])")

_TEST_DIR_CANDIDATES = ("tests", "test", "src/tests")
_SKIP_SRC_DIRS = frozenset({
    "tests",
    "test",
    "docs",
    "examples",
    "scripts",
    "build",
    "dist",
    "site",
    "venv",
    ".venv",
    "env",
    "node_modules",
})


def _pytest_importable() -> bool:
    return importlib.util.find_spec("pytest") is not None


def _has_pytest_config(project_root: Path, pyproject: dict[str, Any], test_dir: Path) -> bool:
    if "pytest" in pyproject.get("tool", {}):
        return True
    if (project_root / "pytest.ini").is_file() or (project_root / "pytest.cfg").is_file():
        return True
    return (test_dir / "conftest.py").is_file()


def _iter_declared_deps(pyproject: dict[str, Any]) -> Iterator[str]:
    yield from pyproject.get("project", {}).get("dependencies", []) or []
    for group in (pyproject.get("dependency-groups", {}) or {}).values():
        yield from group or []
    uv_tool = pyproject.get("tool", {}).get("uv", {}) or {}
    for key in ("dev-dependencies", "dependencies"):
        yield from uv_tool.get(key, []) or []


def _deps_mention(pattern: re.Pattern[str], pyproject: dict[str, Any]) -> bool:
    return any(pattern.search(str(dep)) for dep in _iter_declared_deps(pyproject))


def _deps_mention_pytest(pyproject: dict[str, Any]) -> bool:
    return _deps_mention(_PYTEST_WORD, pyproject)


def detect_test_runner(
    project_root: Path, pyproject: dict[str, Any], test_dir: Path
) -> TestRunner:
    """Pick pytest vs unittest for ``project_root`` using the already-resolved ``test_dir``."""
    if _has_pytest_config(project_root, pyproject, test_dir):
        return "pytest"
    if _deps_mention_pytest(pyproject):
        return "pytest"
    if _pytest_importable():
        return "pytest"
    return "unittest"


def detect_test_dir(project_root: Path) -> Path:
    """Return the first existing test directory, or ``project_root/tests`` as a fallback."""
    for candidate in _TEST_DIR_CANDIDATES:
        path = project_root / candidate
        if path.is_dir():
            return path
    return project_root / "tests"


def detect_src_dir(project_root: Path, pyproject: dict[str, Any]) -> Path:
    """Best-effort guess at the project's source directory.

    Preference order:
      1. Explicit ``[tool.uv.build-backend] module-name`` (pyharness itself uses this).
      2. Hatch wheel packages: ``[tool.hatch.build.targets.wheel] packages``.
      3. Setuptools flat packages: ``[tool.setuptools] packages`` (list form).
      4. ``src/<pkg>`` layout — first sub-dir of ``src/`` with ``__init__.py``.
      5. First top-level dir with ``__init__.py`` that isn't a tests/tooling dir.
      6. ``[project] name`` turned into an importable directory, if it exists.
      7. ``project_root`` itself (flat script layout — tools just scan the whole tree).
    """
    for candidate in _declared_package_candidates(project_root, pyproject):
        if candidate.is_dir():
            return candidate.resolve()

    src_dir = project_root / "src"
    if src_dir.is_dir():
        for entry in sorted(src_dir.iterdir()):
            if entry.is_dir() and (entry / "__init__.py").is_file():
                return entry.resolve()
        return src_dir.resolve()

    for entry in sorted(project_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in _SKIP_SRC_DIRS:
            continue
        if (entry / "__init__.py").is_file():
            return entry.resolve()

    project_name = (pyproject.get("project", {}) or {}).get("name")
    if isinstance(project_name, str):
        candidate = project_root / project_name.replace("-", "_")
        if candidate.is_dir():
            return candidate.resolve()

    return project_root.resolve()


def _declared_package_candidates(project_root: Path, pyproject: dict[str, Any]) -> Iterator[Path]:
    """Yield candidate source dirs from explicit build-backend declarations."""
    tool = pyproject.get("tool", {}) or {}

    uv_module = (tool.get("uv", {}) or {}).get("build-backend", {}) or {}
    module_name = uv_module.get("module-name")
    if isinstance(module_name, str) and module_name:
        module_root = uv_module.get("module-root", "")
        yield project_root / str(module_root) / module_name

    hatch_packages = (
        (tool.get("hatch", {}) or {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("packages")
    )
    if isinstance(hatch_packages, list) and hatch_packages:
        yield project_root / str(hatch_packages[0])

    setuptools_packages = (tool.get("setuptools", {}) or {}).get("packages")
    if isinstance(setuptools_packages, list) and setuptools_packages:
        yield project_root / str(setuptools_packages[0]).replace(".", "/")


def detect_test_invoker(project_root: Path) -> TestInvoker:
    """``uv`` when ``uv.lock`` exists at the project root, else ``python``."""
    if (project_root / "uv.lock").is_file():
        return "uv"
    return "python"


_FEATURES_DIR_CANDIDATES = ("tests/features", "features")


def detect_features_dir(project_root: Path, test_dir: Path) -> Path | None:
    """Return the canonical Gherkin ``features/`` directory if one exists.

    Search order: ``tests/features/``, ``features/``, ``<test_dir>/features/``.
    Returns ``None`` when no directory matches — callers treat that as a no-op.
    """
    for relative in _FEATURES_DIR_CANDIDATES:
        candidate = project_root / relative
        if candidate.is_dir():
            return candidate.resolve()
    in_test_dir = test_dir / "features"
    if in_test_dir.is_dir():
        return in_test_dir.resolve()
    return None


def _behave_layout(features_dir: Path) -> bool:
    """Heuristic: behave mandates ``features/steps/`` + ``features/environment.py``."""
    return (features_dir / "steps").is_dir() and (features_dir / "environment.py").is_file()


def detect_acceptance_runner(cfg: HarnessConfig) -> AcceptanceRunner | None:
    """Pick ``pytest-bdd`` | ``behave`` based on explicit override → layout → deps.

    Returns ``None`` when nothing should run: ``acceptance_runner = "off"`` or
    no ``features_dir``. Explicit ``[tool.harness] acceptance_runner`` wins.
    """
    if cfg.acceptance_runner is not None:
        return None if cfg.acceptance_runner == "off" else cfg.acceptance_runner
    if cfg.features_dir is None:
        return None
    if _behave_layout(cfg.features_dir):
        return "behave"
    pyproject = cfg.pyproject
    if _deps_mention(_BEHAVE_WORD, pyproject) and not _deps_mention(_PYTEST_BDD_WORD, pyproject):
        return "behave"
    return "pytest-bdd"
