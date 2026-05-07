"""Dependency freshness via explicit package-index lookup."""

from __future__ import annotations

import json
import sys

from interlocks.config import InterlockConfig, invoker_prefix, load_config
from interlocks.runner import capture, dump_and_exit, fail, ok


def freshness_cmd(cfg: InterlockConfig) -> list[str]:
    return [*invoker_prefix(cfg), "pip", "list", "--outdated", "--format=json"]


def cmd_deps_freshness() -> None:
    result = capture(freshness_cmd(load_config()))
    if result.returncode != 0:
        fail("Dependency freshness: package-index lookup failed")
        dump_and_exit(result.returncode, result.stdout, result.stderr)

    outdated = _outdated_packages(result.stdout)
    if not outdated:
        ok("Dependency freshness: dependencies current")
        return

    fail(f"Dependency freshness: {len(outdated)} outdated package(s)")
    for pkg in outdated:
        print(
            f"  - {pkg.get('name', '?')}: "
            f"{pkg.get('version', '?')} -> {pkg.get('latest_version', '?')}"
        )
    sys.exit(1)


def _outdated_packages(output: str) -> list[dict[str, object]]:
    try:
        data = json.loads(output or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [package for package in data if isinstance(package, dict)]
