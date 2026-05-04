"""CRAP complexity x coverage gate."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from interlocks import ui
from interlocks.config import load_config
from interlocks.git import changed_py_files_vs_main
from interlocks.metrics import (
    compute_crap_rows,
    iter_py_files,
    lizard_functions,
    newer_than,
    parse_coverage,
)
from interlocks.runner import arg_value, generate_coverage_xml

if TYPE_CHECKING:
    from collections.abc import Iterator

    from interlocks.config import InterlockConfig
    from interlocks.metrics import CrapRow

_CRAP_ADVISORY_LIMIT = 5


def _print_offender(row: CrapRow) -> None:
    print(
        f"    CRAP={row.crap:6.1f}  CCN={row.ccn:3d}  "
        f"cov={row.coverage * 100:5.1f}%  "
        f"{row.name}@{row.start}-{row.end}@{row.path}"
    )


def cmd_crap() -> None:
    """CRAP = ccn^2 * (1-cov)^3 + ccn per function — lizard + coverage XML.

    Threshold precedence: ``--max=N`` on argv > ``cfg.crap_max`` (default 30.0,
    overridable via ``[tool.interlocks] crap_max``). Blocking depends on
    ``cfg.enforce_crap``.
    """
    cfg = load_config()
    max_crap = float(arg_value("--max=", str(cfg.crap_max)))
    changed = changed_py_files_vs_main() if "--changed-only" in sys.argv else None

    cov_file = generate_coverage_xml()
    command = f"CRAP --max={max_crap}"
    if not cov_file.exists():
        ui.row(
            "crap",
            command,
            "skipped",
            detail="coverage.xml missing — run `interlocks coverage`",
            state="warn",
        )
        sys.exit(1)
    cov_map = parse_coverage(cov_file)
    fns = lizard_functions(cfg.src_dir_arg)
    offenders = compute_crap_rows(fns, cov_map, max_crap=max_crap, changed=changed)

    if not offenders:
        ui.row("crap", command, "ok", state="ok")
        return
    offenders.sort(key=lambda r: r.crap, reverse=True)
    ui.row("crap", command, f"{len(offenders)} function(s) exceed", state="fail")
    for row in offenders[:20]:
        _print_offender(row)
    if cfg.enforce_crap:
        sys.exit(1)


def cmd_crap_cached_advisory(changed: set[str] | None = None) -> None:
    """Print fast advisory CRAP output from fresh cached coverage, or a skip hint."""
    cfg = load_config()
    command = f"CRAP --max={cfg.crap_max}"
    cov_cache = Path(".coverage")
    if not cov_cache.exists():
        ui.row("crap", command, "skipped", detail="no coverage cache", state="warn")
        return
    if _coverage_cache_is_stale(cov_cache, cfg):
        ui.row("crap", command, "skipped", detail="coverage cache is stale", state="warn")
        return

    cov_file = generate_coverage_xml()
    if not cov_file.exists():
        ui.row("crap", command, "skipped", detail="coverage.xml missing", state="warn")
        return

    cov_map = parse_coverage(cov_file)
    offenders = compute_crap_rows(
        lizard_functions(cfg.src_dir_arg), cov_map, max_crap=cfg.crap_max, changed=changed
    )
    offenders.sort(key=lambda r: r.crap, reverse=True)
    if not offenders:
        ui.row("crap", command, "ok", state="ok")
        return
    ui.row(
        "crap",
        command,
        f"{len(offenders)} function(s) exceed",
        detail="cached advisory",
        state="warn",
    )
    for row in offenders[:_CRAP_ADVISORY_LIMIT]:
        _print_offender(row)
    if len(offenders) > _CRAP_ADVISORY_LIMIT:
        print(f"    … {len(offenders) - _CRAP_ADVISORY_LIMIT} more")


def _coverage_cache_is_stale(cov_cache: Path, cfg: InterlockConfig) -> bool:
    try:
        cov_mtime = cov_cache.stat().st_mtime
    except OSError:
        return True
    return any(newer_than(path, cov_mtime) for path in _coverage_inputs(cfg))


def _coverage_inputs(cfg: InterlockConfig) -> Iterator[Path]:
    yield cfg.project_root / "pyproject.toml"
    for root in (cfg.src_dir, cfg.test_dir):
        if root.is_file() and root.suffix == ".py":
            yield root
        elif root.is_dir():
            yield from iter_py_files(root)
