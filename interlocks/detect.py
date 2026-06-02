"""Auto-detect the target project's test runner, source/test dirs, and invoker. Stdlib-only.

All helpers are pure — they take the pre-loaded ``pyproject`` dict and the discovered
``project_root`` — so ``interlocks/config.py`` owns discovery and caching.

Test-runner detection order (first match wins):
  1. Pytest config: ``[tool.pytest.*]``, ``pytest.ini``, ``pytest.cfg``, ``<test_dir>/conftest.py``
  2. ``pytest`` declared in project / dep-group / uv dependencies
  3. Otherwise: unittest
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from interlocks.config import AcceptanceRunner, InterlockConfig, TestInvoker, TestRunner


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


def _has_pytest_config(project_root: Path, pyproject: dict[str, Any], test_dir: Path) -> bool:
    tool = pyproject.get("tool", {})
    if isinstance(tool, dict) and "pytest" in tool:
        return True
    if (project_root / "pytest.ini").is_file() or (project_root / "pytest.cfg").is_file():
        return True
    return (test_dir / "conftest.py").is_file()


def _iter_declared_deps(pyproject: dict[str, Any]) -> Iterator[str]:
    project = pyproject.get("project", {})
    if isinstance(project, dict):
        yield from _iter_dep_list(project.get("dependencies"))
    groups = pyproject.get("dependency-groups", {})
    if isinstance(groups, dict):
        for group in groups.values():
            yield from _iter_dep_list(group)
    tool = pyproject.get("tool", {})
    uv_tool = tool.get("uv", {}) if isinstance(tool, dict) else {}
    if not isinstance(uv_tool, dict):
        return
    for key in ("dev-dependencies", "dependencies"):
        yield from _iter_dep_list(uv_tool.get(key))


def _iter_dep_list(value: object) -> Iterator[str]:
    if isinstance(value, list):
        yield from (item for item in value if isinstance(item, str))


def _deps_mention(pattern: re.Pattern[str], pyproject: dict[str, Any]) -> bool:
    return any(pattern.search(str(dep)) for dep in _iter_declared_deps(pyproject))


def dependency_declared(pyproject: dict[str, Any], package: str) -> bool:
    """True when project/dependency-group/uv deps declare ``package`` by normalized name."""
    wanted = _normalize_dependency_name(package)
    return any(
        _normalize_dependency_name(dep) == wanted for dep in _iter_declared_dep_names(pyproject)
    )


def _iter_declared_dep_names(pyproject: dict[str, Any]) -> Iterator[str]:
    for dep in _iter_declared_deps(pyproject):
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)", dep)
        if match is not None:
            yield match.group(1)


def _normalize_dependency_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def detect_test_runner(
    project_root: Path, pyproject: dict[str, Any], test_dir: Path
) -> TestRunner:
    """Pick pytest vs unittest for ``project_root`` using the already-resolved ``test_dir``."""
    if _has_pytest_config(project_root, pyproject, test_dir):
        return "pytest"
    if _deps_mention(_PYTEST_WORD, pyproject):
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
      1. Explicit ``[tool.uv.build-backend] module-name`` (interlocks itself uses this).
      2. Hatch wheel packages: ``[tool.hatch.build.targets.wheel] packages``.
      3. Setuptools flat packages: ``[tool.setuptools] packages`` (list form).
      4. ``src/<pkg>`` layout — first sub-dir of ``src/`` with ``__init__.py``.
      5. First top-level dir with ``__init__.py`` that isn't test/tooling infrastructure.
      6. ``[project] name`` turned into an importable directory, if it exists.
      7. ``project_root`` itself (flat script layout — tools just scan the whole tree).
    """
    for candidate in _declared_package_candidates(project_root, pyproject):
        if candidate.is_dir():
            return candidate.resolve()
    return (
        _src_layout_dir(project_root)
        or _top_level_package_dir(project_root)
        or _project_name_dir(project_root, pyproject)
        or project_root.resolve()
    )


def _src_layout_dir(project_root: Path) -> Path | None:
    """Return ``src/<pkg>`` (first ``__init__.py`` child) or ``src/`` itself if layout exists."""
    src_dir = project_root / "src"
    if not src_dir.is_dir():
        return None
    for entry in sorted(src_dir.iterdir()):
        if entry.is_dir() and (entry / "__init__.py").is_file():
            return entry.resolve()
    return src_dir.resolve()


def _top_level_package_dir(project_root: Path) -> Path | None:
    """First top-level dir with ``__init__.py`` that isn't a tests/tooling dir."""
    for entry in sorted(project_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if _skip_source_dir(entry):
            continue
        if (entry / "__init__.py").is_file():
            return entry.resolve()
    return None


def _skip_source_dir(entry: Path) -> bool:
    if entry.name in _SKIP_SRC_DIRS:
        return True
    return entry.name == "properties" and _looks_like_property_tests_dir(entry)


def _looks_like_property_tests_dir(entry: Path) -> bool:
    return (
        (entry / "conftest.py").is_file()
        or any(entry.glob("test_*.py"))
        or any(entry.glob("*_test.py"))
    )


def _project_name_dir(project_root: Path, pyproject: dict[str, Any]) -> Path | None:
    """``[project] name`` as an importable directory, if it exists on disk."""
    project_name = (pyproject.get("project", {}) or {}).get("name")
    if not isinstance(project_name, str):
        return None
    candidate = project_root / project_name.replace("-", "_")
    return candidate.resolve() if candidate.is_dir() else None


def _declared_package_candidates(project_root: Path, pyproject: dict[str, Any]) -> Iterator[Path]:
    """Yield candidate source dirs from explicit build-backend declarations."""
    tool = pyproject.get("tool", {}) or {}
    for resolver in (_uv_package_path, _hatch_package_path, _setuptools_package_path):
        candidate = resolver(project_root, tool)
        if candidate is not None:
            yield candidate


def _uv_package_path(project_root: Path, tool: dict[str, Any]) -> Path | None:
    uv_module = (tool.get("uv", {}) or {}).get("build-backend", {}) or {}
    module_name = uv_module.get("module-name")
    if not isinstance(module_name, str) or not module_name:
        return None
    module_root = uv_module.get("module-root", "")
    return project_root / str(module_root) / module_name


def _hatch_package_path(project_root: Path, tool: dict[str, Any]) -> Path | None:
    packages = (
        (tool.get("hatch", {}) or {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("packages")
    )
    if not isinstance(packages, list) or not packages:
        return None
    return project_root / str(packages[0])


def _setuptools_package_path(project_root: Path, tool: dict[str, Any]) -> Path | None:
    packages = (tool.get("setuptools", {}) or {}).get("packages")
    if not isinstance(packages, list) or not packages:
        return None
    return project_root / str(packages[0]).replace(".", "/")


def detect_test_invoker(project_root: Path) -> TestInvoker:
    """``uv`` when ``uv.lock`` exists at the project root, else ``python``."""
    if (project_root / "uv.lock").is_file():
        return "uv"
    return "python"


def expected_target_interpreter(project_root: Path) -> Path:
    """Return the conventional in-project venv interpreter path (existence not checked).

    POSIX: ``.venv/bin/python``. Windows: ``.venv/Scripts/python.exe``.
    """
    venv = project_root / ".venv"
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def detect_target_interpreter(project_root: Path) -> Path | None:
    """Return the target project's in-tree venv interpreter, or ``None`` when absent.

    Lets ``invoker_prefix`` prefer the project's venv over pipx's own interpreter.
    """
    candidate = expected_target_interpreter(project_root)
    return candidate if candidate.is_file() else None


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


def detect_acceptance_runner(cfg: InterlockConfig) -> AcceptanceRunner | None:
    """Pick ``pytest-bdd`` | ``behave`` based on explicit override → layout → deps.

    Returns ``None`` when nothing should run: ``acceptance_runner = "off"`` or
    no ``features_dir``. Explicit ``[tool.interlocks] acceptance_runner`` wins.
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
