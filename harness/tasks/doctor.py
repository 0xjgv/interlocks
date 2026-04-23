"""Preflight diagnostic: detect project layout, bundled tool resolution, and venv status.

``doctor`` is intentionally permissive — it reports warnings but exits 0 unless
the project is structurally broken (e.g. an unreadable ``pyproject.toml``). The
output is plain human-readable key/value lines grouped under section headers.
Stdlib-only.
"""

from __future__ import annotations

import shutil
import sys
import tomllib
from typing import TYPE_CHECKING

from harness.config import find_project_root, load_config

if TYPE_CHECKING:
    from pathlib import Path

    from harness.config import HarnessConfig
    from harness.runner import Task

# CLIs pyharness invokes via subprocess — reporting their resolution helps
# users diagnose missing tools (e.g. basedpyright not installed in the venv).
_BUNDLED_TOOLS = (
    "ruff",
    "basedpyright",
    "coverage",
    "mutmut",
    "pytest",
    "pip-audit",
    "deptry",
    "import-linter",
    "lizard",
)


def task_doctor() -> Task | None:
    """Doctor is CLI-only — never runs as a composable ``Task``."""
    return None


def cmd_doctor() -> None:
    project_root = find_project_root()
    pyproject_path = project_root / "pyproject.toml"

    warnings: list[str] = []
    failures: list[str] = []

    print("Project:")
    print(f"  project_root           {project_root}")
    cfg = _safe_load_config(pyproject_path, failures)
    _print_project(cfg, pyproject_path, warnings)

    print()
    print("Tools:")
    for name in _BUNDLED_TOOLS:
        resolved = shutil.which(name)
        if resolved:
            print(f"  {name:<22} {resolved}")
        else:
            print(f"  {name:<22} (not found)")
            warnings.append(f"tool not found on PATH: {name}")

    print()
    print("Venv:")
    venv_python = _venv_python(project_root)
    if venv_python.is_file():
        print(f"  venv_python            {venv_python}")
    else:
        print(f"  venv_python            (missing: {venv_python})")
        warnings.append("no .venv found under project root")

    print()
    print("Summary:")
    _print_summary(warnings, failures)

    if failures:
        sys.exit(1)


def _safe_load_config(pyproject_path: Path, failures: list[str]) -> HarnessConfig | None:
    """Load config, recording a failure when ``pyproject.toml`` is unreadable."""
    try:
        return load_config()
    except (OSError, tomllib.TOMLDecodeError) as exc:
        failures.append(f"cannot read {pyproject_path}: {exc}")
        return None


def _print_project(cfg: HarnessConfig | None, pyproject_path: Path, warnings: list[str]) -> None:
    if pyproject_path.is_file():
        print(f"  pyproject.toml         {pyproject_path}")
    else:
        print("  pyproject.toml         (missing)")
        warnings.append("no pyproject.toml at project root")
    if cfg is None:
        return
    print(f"  src_dir                {cfg.src_dir_arg}")
    print(f"  test_dir               {cfg.test_dir_arg}")
    print(f"  test_runner            {cfg.test_runner}")
    print(f"  test_invoker           {cfg.test_invoker}")
    features = cfg.features_dir_arg
    print(f"  features_dir           {features if features is not None else '(none)'}")


def _venv_python(project_root: Path) -> Path:
    """Return the conventional in-project venv Python path for this platform."""
    if sys.platform == "win32":
        return project_root / ".venv" / "Scripts" / "python.exe"
    return project_root / ".venv" / "bin" / "python"


def _print_summary(warnings: list[str], failures: list[str]) -> None:
    if failures:
        print(f"  fail {len(failures)}")
        for msg in failures:
            print(f"    - {msg}")
        return
    if warnings:
        print(f"  warn {len(warnings)}")
        for msg in warnings:
            print(f"    - {msg}")
        return
    print("  ok")
