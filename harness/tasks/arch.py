"""Architectural contracts via import-linter.

When the project declares contracts (``[tool.importlinter]`` in pyproject.toml,
``.importlinter``, or ``setup.cfg``), those are enforced as-is. Otherwise a default
contract is synthesized: source code must not import from the test package. This
catches a real class of bugs — accidental test-helper imports leaking into production —
and applies to any project layout where both ``src_dir`` and ``test_dir`` are packages.
When the default can't be expressed (e.g., ``test_dir`` has no ``__init__.py``), the
stage skips with a nudge.
"""

from __future__ import annotations

import os
import tempfile
import textwrap
import tomllib
from pathlib import Path

from harness.config import HarnessConfig, load_config
from harness.runner import Task, run, tool, warn_skip


def task_arch() -> Task | None:
    """Return the import-linter Task, or None if no contracts apply."""
    cfg = load_config()
    if _user_has_contracts(cfg):
        return Task("Architecture (import-linter)", tool("lint-imports"))
    default_cfg = _write_default_config(cfg)
    if default_cfg is None:
        return None
    return Task(
        "Architecture (default: src ↛ tests)",
        tool("lint-imports", "--config", str(default_cfg), "--no-cache"),
    )


def cmd_arch() -> None:
    task = task_arch()
    if task is None:
        warn_skip(
            "arch: no [tool.importlinter] contracts — "
            "default needs src_dir and test_dir to be Python packages"
        )
        return
    run(task)


def _user_has_contracts(cfg: HarnessConfig) -> bool:
    """True if any standard import-linter config exists in the project."""
    pyproject = cfg.project_root / "pyproject.toml"
    if pyproject.is_file():
        with pyproject.open("rb") as f:
            data = tomllib.load(f)
        if "importlinter" in data.get("tool", {}):
            return True
    return any((cfg.project_root / name).is_file() for name in (".importlinter", "setup.cfg"))


def _write_default_config(cfg: HarnessConfig) -> Path | None:
    """Write an INI contract: source package must not import from test package.

    Returns None if the layout can't support the default — either dir lacks
    ``__init__.py``, or src and test share a name.
    """
    if not (cfg.src_dir / "__init__.py").is_file():
        return None
    if not (cfg.test_dir / "__init__.py").is_file():
        return None
    src_pkg, test_pkg = cfg.src_dir.name, cfg.test_dir.name
    if src_pkg == test_pkg:
        return None
    body = textwrap.dedent(
        f"""\
        [importlinter]
        root_packages =
            {src_pkg}
            {test_pkg}

        [importlinter:contract:production-no-tests]
        name = Production does not import tests
        type = forbidden
        source_modules =
            {src_pkg}
        forbidden_modules =
            {test_pkg}
        """
    )
    fd, path = tempfile.mkstemp(prefix="harness-arch-", suffix=".ini")
    os.close(fd)
    Path(path).write_text(body, encoding="utf-8")
    return Path(path)
