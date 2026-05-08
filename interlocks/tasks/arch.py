"""Architectural contracts via import-linter.

Default catches production code accidentally importing test helpers — a real bug class.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from interlocks.config import InterlockConfig, load_config
from interlocks.defaults.tools import entrypoint
from interlocks.defaults_path import has_project_config
from interlocks.defaults_path import path as defaults_path
from interlocks.runner import Task, run, uvx_tool, warn_skip


def task_arch() -> Task | None:
    cfg = load_config()
    version = cfg.tool_version("import-linter")
    script = entrypoint("import-linter")
    if has_project_config(cfg, "importlinter", sidecars=(".importlinter", "setup.cfg")):
        return Task(
            "Architecture (import-linter)",
            uvx_tool("import-linter", version=version, entrypoint=script),
            label="arch",
            display="lint-imports",
        )
    default_cfg = _write_default_config(cfg)
    if default_cfg is None:
        return None
    return Task(
        "Architecture (default: src ↛ tests)",
        uvx_tool(
            "import-linter",
            "--config",
            str(default_cfg),
            version=version,
            entrypoint=script,
        ),
        label="arch",
        display="lint-imports (default: src ↛ tests)",
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


def _write_default_config(cfg: InterlockConfig) -> Path | None:
    src_init = cfg.src_dir / "__init__.py"
    test_init = cfg.test_dir / "__init__.py"
    src_pkg, test_pkg = cfg.src_dir.name, cfg.test_dir.name
    if not (src_init.is_file() and test_init.is_file() and src_pkg != test_pkg):
        return None
    template = defaults_path("importlinter_template.ini").read_text(encoding="utf-8")
    body = template.format(src_pkg=src_pkg, test_pkg=test_pkg)
    # Stable path — content depends only on (src_pkg, test_pkg), so projects sharing
    # those names share the file safely, and import-linter's graph cache survives runs.
    out = Path(tempfile.gettempdir()) / f"interlocks-arch-{src_pkg}-{test_pkg}.ini"
    out.write_text(body, encoding="utf-8")
    return out
