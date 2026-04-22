"""Locate bundled default configs and detect when the target project has its own.

Tools like ruff/basedpyright/deptry need real filesystem paths (not zipfile
URIs), so `path()` uses ``importlib.resources.as_file`` via an ExitStack that
lives for the CLI's lifetime — the extracted file survives until interpreter
exit, which is fine for our one-shot-per-invocation model.
"""

from __future__ import annotations

import atexit
from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path
from typing import TYPE_CHECKING

from harness.config import _load_pyproject

if TYPE_CHECKING:
    from collections.abc import Iterable

    from harness.config import HarnessConfig

_extractor = ExitStack()
atexit.register(_extractor.close)


def path(name: str) -> Path:
    """Return a real filesystem path to ``harness/defaults/<name>``.

    When the package is imported from a zipfile, the file is extracted to a
    temp location; the extraction lives for the remainder of the process.
    """
    resource = files("harness.defaults") / name
    return Path(_extractor.enter_context(as_file(resource)))


def has_project_config(cfg: HarnessConfig, section: str, sidecars: Iterable[str] = ()) -> bool:
    """True if the target project owns its own config for ``section``.

    Checks for ``[tool.<section>]`` in the project's pyproject.toml, then for
    any of ``sidecars`` (e.g. ``ruff.toml``, ``.ruff.toml``) in the project root.
    """
    if section in _load_pyproject(cfg.project_root).get("tool", {}):
        return True
    return any((cfg.project_root / name).is_file() for name in sidecars)


def config_flag_if_absent(
    cfg: HarnessConfig,
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
