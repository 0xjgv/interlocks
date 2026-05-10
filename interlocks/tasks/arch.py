"""Architectural contracts via import-linter.

Default template catches production code accidentally importing test helpers — a real
bug class. The ``layered`` template exposes import-linter's ``layers`` contract behind
``[tool.interlocks] arch_template = "layered"`` + ``[tool.interlocks.arch_layers]``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from interlocks.config import InterlockConfig, load_config
from interlocks.defaults.tools import entrypoint
from interlocks.defaults_path import has_project_config
from interlocks.defaults_path import path as defaults_path
from interlocks.runner import Task, run, uvx_tool, warn_skip

_DEFAULT_DISPLAY = "lint-imports (default: src ↛ tests)"
_LAYERED_DISPLAY = "lint-imports (default: layered)"


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
    description, display = _bundled_descriptions(cfg)
    return Task(
        description,
        uvx_tool(
            "import-linter",
            "--config",
            str(default_cfg),
            version=version,
            entrypoint=script,
        ),
        label="arch",
        display=display,
    )


def cmd_arch() -> None:
    cfg = load_config()
    task = task_arch()
    if task is None:
        warn_skip(_skip_reason(cfg))
        return
    run(task)


def _bundled_descriptions(cfg: InterlockConfig) -> tuple[str, str]:
    if cfg.arch_template == "layered":
        return ("Architecture (default: layered)", _LAYERED_DISPLAY)
    return ("Architecture (default: src ↛ tests)", _DEFAULT_DISPLAY)


def _skip_reason(cfg: InterlockConfig) -> str:
    if cfg.arch_template == "layered":
        return (
            "arch: layered template selected but [tool.interlocks.arch_layers] layers is empty "
            "— list layer modules ordered top → bottom (high-level first)"
        )
    return (
        "arch: no [tool.importlinter] contracts — "
        "default needs src_dir and test_dir to be Python packages"
    )


def _write_default_config(cfg: InterlockConfig) -> Path | None:
    if cfg.arch_template == "layered":
        return _write_layered_config(cfg)
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


def _write_layered_config(cfg: InterlockConfig) -> Path | None:
    if not cfg.arch_layers:
        return None
    src_init = cfg.src_dir / "__init__.py"
    if not src_init.is_file():
        return None
    root_pkg = cfg.src_dir.name
    layers_block = "\n".join(f"    {name}" for name in cfg.arch_layers)
    template = defaults_path("importlinter_layered.ini").read_text(encoding="utf-8")
    body = template.format(root_pkg=root_pkg, layers_block=layers_block)
    out = Path(tempfile.gettempdir()) / f"interlocks-arch-layered-{root_pkg}.ini"
    out.write_text(body, encoding="utf-8")
    return out
