"""CRAP complexity x coverage gate. Advisory."""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from harness.git import changed_py_files_vs_main
from harness.paths import SRC_DIR
from harness.runner import GREEN, RED, RESET, arg_value, fail_skip, generate_coverage_xml, tool

if TYPE_CHECKING:
    from pathlib import Path

_LIZARD_LINE = re.compile(r"^\s*(\d+)\s+(\d+)\s+\d+\s+\d+\s+\d+\s+(\S+)@(\d+)-(\d+)@(.+)$")


def _parse_coverage(cov_file: Path) -> dict[str, dict[int, int]]:
    """Return {filename: {lineno: hits}} from a coverage.xml file."""
    cov_map: dict[str, dict[int, int]] = {}
    for cls in ET.parse(cov_file).iter("class"):
        fn = cls.get("filename", "")
        cov_map[fn] = {
            int(ln.get("number", "0")): int(ln.get("hits", "0"))
            for ln in cls.iter("line")
            if ln.get("number")
        }
    return cov_map


def _function_coverage(lines: dict[int, int], start: int, end: int) -> float:
    in_range = [n for n in range(start, end + 1) if n in lines]
    return (sum(1 for n in in_range if lines[n] > 0) / len(in_range)) if in_range else 0.0


def _compute_offenders(
    lizard_stdout: str,
    cov_map: dict[str, dict[int, int]],
    changed: set[str] | None,
    max_crap: float,
) -> list[tuple[float, int, float, str]]:
    offenders: list[tuple[float, int, float, str]] = []
    for out_line in lizard_stdout.splitlines():
        m = _LIZARD_LINE.match(out_line)
        if not m:
            continue
        _, ccn_s, func, start_s, end_s, path = m.groups()
        if changed is not None and path not in changed:
            continue
        ccn = int(ccn_s)
        start, end = int(start_s), int(end_s)
        lines = cov_map.get(path) or cov_map.get(path.lstrip("./")) or {}
        cov = _function_coverage(lines, start, end)
        crap = ccn * ccn * (1 - cov) ** 3 + ccn
        if crap > max_crap:
            offenders.append((crap, ccn, cov, f"{func}@{start}-{end}@{path}"))
    return offenders


def cmd_crap() -> None:
    """CRAP = ccn^2 * (1-cov)^3 + ccn per function. Advisory — lizard + coverage XML."""
    max_crap = float(arg_value("--max=", "30"))
    changed = changed_py_files_vs_main() if "--changed-only" in sys.argv else None

    cov_file = generate_coverage_xml()
    if not cov_file.exists():
        fail_skip("CRAP: coverage.xml not generated — run `harness coverage` first")
    cov_map = _parse_coverage(cov_file)
    lizard_res = subprocess.run(
        tool("lizard", SRC_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    offenders = _compute_offenders(lizard_res.stdout, cov_map, changed, max_crap)

    if not offenders:
        print(f"  {GREEN}✓{RESET} CRAP: all functions below {max_crap}")
        return
    offenders.sort(reverse=True)
    print(f"  {RED}✗{RESET} CRAP: {len(offenders)} function(s) exceed {max_crap}")
    for crap, ccn, cov, loc in offenders[:20]:
        print(f"    CRAP={crap:6.1f}  CCN={ccn:3d}  cov={cov * 100:5.1f}%  {loc}")
