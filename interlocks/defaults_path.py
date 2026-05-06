"""Locate bundled default configs and detect when the target project has its own.

Tools like ruff/basedpyright/deptry need real filesystem paths (not zipfile
URIs), so `path()` uses ``importlib.resources.as_file`` via an ExitStack that
lives for the CLI's lifetime — the extracted file survives until interpreter
exit, which is fine for our one-shot-per-invocation model.
"""

from __future__ import annotations

import atexit
from contextlib import ExitStack
from dataclasses import dataclass
from functools import cache
from importlib.resources import as_file, files
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from interlocks.config import InterlockConfig

_extractor = ExitStack()
atexit.register(_extractor.close)


@dataclass(frozen=True)
class ToolConfigSpec:
    tool: str
    section: str
    filename: str
    flag: str
    sidecars: tuple[str, ...] = ()


TOOL_CONFIG_SPECS: dict[str, ToolConfigSpec] = {
    "ruff": ToolConfigSpec("ruff", "ruff", "ruff.toml", "--config", ("ruff.toml", ".ruff.toml")),
    "basedpyright": ToolConfigSpec(
        "basedpyright",
        "basedpyright",
        "pyrightconfig.json",
        "--project",
        ("pyrightconfig.json", "pyrightconfig.toml"),
    ),
    "coverage": ToolConfigSpec("coverage", "coverage", "coveragerc", "--rcfile", (".coveragerc",)),
    "import-linter": ToolConfigSpec(
        "import-linter",
        "importlinter",
        "importlinter_template.ini",
        "--config",
        (".importlinter", "setup.cfg"),
    ),
}


@dataclass(frozen=True)
class ToolConfigSource:
    tool: str
    source: str
    path: Path
    bundled_path: Path
    flag: str

    @property
    def is_bundled(self) -> bool:
        return self.source == "bundled"


@cache
def path(name: str) -> Path:
    """Return a real filesystem path to ``interlocks/defaults/<name>``.

    When the package is imported from a zipfile, the file is extracted to a
    temp location; the extraction lives for the remainder of the process.
    Cached so each bundled file is resolved at most once per process.
    """
    resource = files("interlocks.defaults") / name
    return Path(_extractor.enter_context(as_file(resource)))


def has_project_config(cfg: InterlockConfig, section: str, sidecars: Iterable[str] = ()) -> bool:
    """True if the target project owns its own config for ``section``.

    Checks for ``[tool.<section>]`` in the project's pyproject.toml, then for
    any of ``sidecars`` (e.g. ``ruff.toml``, ``.ruff.toml``) in the project root.
    """
    return project_config_source(cfg, section, sidecars=sidecars) is not None


def project_config_source(
    cfg: InterlockConfig, section: str, sidecars: Iterable[str] = ()
) -> tuple[str, Path] | None:
    if section in cfg.pyproject.get("tool", {}):
        return (f"pyproject.toml [tool.{section}]", cfg.project_root / "pyproject.toml")
    for name in sidecars:
        candidate = cfg.project_root / name
        if candidate.is_file():
            return (name, candidate)
    return None


def tool_config_source(cfg: InterlockConfig, tool: str) -> ToolConfigSource:
    spec = TOOL_CONFIG_SPECS[tool]
    bundled = path(spec.filename)
    project = project_config_source(cfg, spec.section, sidecars=spec.sidecars)
    if project is not None:
        label, project_path = project
        return ToolConfigSource(tool, f"project: {label}", project_path, bundled, spec.flag)
    return ToolConfigSource(tool, "bundled", bundled, bundled, spec.flag)


def config_flag_if_absent(
    cfg: InterlockConfig,
    *,
    section: str,
    filename: str,
    flag: str,
    sidecars: Iterable[str] = (),
) -> list[str]:
    """Return ``[flag, <bundled-path>]`` when the project owns no config, else ``[]``.

    Each tool takes its config via a different flag (``--config``, ``--rcfile``,
    ``--project``); callers pass the tool-appropriate one. Safe to splat into a
    command list regardless of outcome.
    """
    if has_project_config(cfg, section, sidecars):
        return []
    return [flag, str(path(filename))]
