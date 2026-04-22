"""Architectural contracts via import-linter.

Default catches production code accidentally importing test helpers — a real bug class.
"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

from harness.config import HarnessConfig, _load_pyproject, load_config
from harness.runner import Task, run, tool, warn_skip


def task_arch() -> Task | None:
    cfg = load_config()
    if _user_has_contracts(cfg):
        return Task("Architecture (import-linter)", tool("lint-imports"))
    default_cfg = _write_default_config(cfg)
    if default_cfg is None:
        return None
    return Task(
        "Architecture (default: src ↛ tests)",
        tool("lint-imports", "--config", str(default_cfg)),
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
    if "importlinter" in _load_pyproject(cfg.project_root).get("tool", {}):
        return True
    return any((cfg.project_root / name).is_file() for name in (".importlinter", "setup.cfg"))


def _write_default_config(cfg: HarnessConfig) -> Path | None:
    src_init = cfg.src_dir / "__init__.py"
    test_init = cfg.test_dir / "__init__.py"
    src_pkg, test_pkg = cfg.src_dir.name, cfg.test_dir.name
    if not (src_init.is_file() and test_init.is_file() and src_pkg != test_pkg):
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
    # Stable path — content depends only on (src_pkg, test_pkg), so projects sharing
    # those names share the file safely, and import-linter's graph cache survives runs.
    path = Path(tempfile.gettempdir()) / f"harness-arch-{src_pkg}-{test_pkg}.ini"
    path.write_text(body, encoding="utf-8")
    return path
