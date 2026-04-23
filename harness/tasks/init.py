"""Scaffold a greenfield Python project in the current working directory.

Writes ``pyproject.toml`` (from a bundled template), ``tests/__init__.py``, and
``tests/test_smoke.py``. Refuses to run when a ``pyproject.toml`` is already
present so existing projects are never overwritten. Stdlib-only.
"""

from __future__ import annotations

from pathlib import Path

from harness.defaults_path import path as defaults_path
from harness.runner import Task, fail_skip, ok, section


def task_init() -> Task | None:
    """Not a gate — ``init`` is a one-shot scaffolding utility."""
    return None


def cmd_init() -> None:
    section("Init project")
    cwd = Path.cwd()
    pyproject = cwd / "pyproject.toml"
    tests_dir = cwd / "tests"
    tests_init = tests_dir / "__init__.py"
    smoke = tests_dir / "test_smoke.py"
    for existing in (pyproject, tests_init, smoke):
        if existing.exists():
            fail_skip(f"init: refusing to overwrite existing {existing.relative_to(cwd)}")

    template = defaults_path("scaffold_pyproject.toml").read_text(encoding="utf-8")
    pyproject.write_text(template.replace("{project_name}", cwd.name), encoding="utf-8")
    ok(f"created {pyproject.name}")

    tests_dir.mkdir(exist_ok=True)
    tests_init.write_text("", encoding="utf-8")
    ok("created tests/__init__.py")

    smoke.write_bytes(defaults_path("scaffold_test_example.py").read_bytes())
    ok("created tests/test_smoke.py")
