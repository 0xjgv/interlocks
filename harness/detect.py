"""Auto-detect the project's test runner (pytest vs unittest). Stdlib-only.

Detection order (first match wins):
  1. `[tool.harness] test_runner` explicit override
  2. Pytest config on disk (`[tool.pytest.*]`, `pytest.ini`, `pytest.cfg`, `tests/conftest.py`)
  3. `pytest` declared in project/dep-group/uv dependencies
  4. Pytest importable in the current interpreter
  5. Otherwise: unittest
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

TestRunner = Literal["pytest", "unittest"]

_PYTEST_WORD = re.compile(r"(?<![A-Za-z0-9_-])pytest(?![A-Za-z0-9_-])")


def _load_pyproject() -> dict[str, Any]:
    path = Path("pyproject.toml")
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _explicit_override(pyproject: dict[str, Any]) -> TestRunner | None:
    value = pyproject.get("tool", {}).get("harness", {}).get("test_runner")
    if value in ("pytest", "unittest"):
        return value
    return None


def _has_pytest_config(pyproject: dict[str, Any]) -> bool:
    if "pytest" in pyproject.get("tool", {}):
        return True
    if Path("pytest.ini").is_file() or Path("pytest.cfg").is_file():
        return True
    return (Path("tests") / "conftest.py").is_file()


def _iter_declared_deps(pyproject: dict[str, Any]) -> Iterator[str]:
    yield from pyproject.get("project", {}).get("dependencies", []) or []
    for group in (pyproject.get("dependency-groups", {}) or {}).values():
        yield from group or []
    uv_tool = pyproject.get("tool", {}).get("uv", {}) or {}
    for key in ("dev-dependencies", "dependencies"):
        yield from uv_tool.get(key, []) or []


def _deps_mention_pytest(pyproject: dict[str, Any]) -> bool:
    return any(_PYTEST_WORD.search(str(dep)) for dep in _iter_declared_deps(pyproject))


def _pytest_importable() -> bool:
    return importlib.util.find_spec("pytest") is not None


@cache
def detect_test_runner() -> TestRunner:
    pyproject = _load_pyproject()

    override = _explicit_override(pyproject)
    if override is not None:
        return override

    if _has_pytest_config(pyproject):
        return "pytest"

    if _deps_mention_pytest(pyproject):
        return "pytest"

    if _pytest_importable():
        return "pytest"

    return "unittest"
