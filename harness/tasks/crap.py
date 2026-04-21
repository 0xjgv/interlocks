"""CRAP complexity x coverage gate. Advisory. Raw subprocess + sys.argv sniffs preserved."""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from harness.paths import SRC_DIR
from harness.runner import GREEN, RED, RESET


def cmd_crap() -> None:
    """CRAP = ccn^2 * (1-cov)^3 + ccn per function. Advisory — lizard + coverage XML."""
    max_crap = float(
        next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--max=")), "30")
    )
    changed_only = "--changed-only" in sys.argv

    # Emit coverage XML quietly; cmd_coverage must have populated .coverage.
    subprocess.run(
        ["uv", "run", "coverage", "xml", "-o", "coverage.xml", "-q"],
        capture_output=True,
        text=True,
        check=False,
    )
    cov_file = Path("coverage.xml")
    if not cov_file.exists():
        print(f"  {RED}✗{RESET} CRAP: coverage XML not found — run `harness coverage` first")
        sys.exit(1)

    cov_map: dict[str, dict[int, int]] = {}
    for cls in ET.parse(cov_file).iter("class"):
        fn = cls.get("filename", "")
        cov_map[fn] = {
            int(ln.get("number", "0")): int(ln.get("hits", "0"))
            for ln in cls.iter("line")
            if ln.get("number")
        }

    changed: set[str] | None = None
    if changed_only:
        res = subprocess.run(
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        changed = {f.strip() for f in res.stdout.splitlines() if f.strip().endswith(".py")}

    lizard_res = subprocess.run(
        ["uv", "run", "lizard", SRC_DIR],
        capture_output=True,
        text=True,
        check=False,
    )
    line_re = re.compile(r"^\s*(\d+)\s+(\d+)\s+\d+\s+\d+\s+\d+\s+(\S+)@(\d+)-(\d+)@(.+)$")
    offenders: list[tuple[float, int, float, str]] = []
    for out_line in lizard_res.stdout.splitlines():
        m = line_re.match(out_line)
        if not m:
            continue
        _, ccn_s, func, start_s, end_s, path = m.groups()
        if changed is not None and path not in changed:
            continue
        ccn = int(ccn_s)
        start, end = int(start_s), int(end_s)
        lines = cov_map.get(path) or cov_map.get(path.lstrip("./")) or {}
        in_range = [n for n in range(start, end + 1) if n in lines]
        cov = (sum(1 for n in in_range if lines[n] > 0) / len(in_range)) if in_range else 0.0
        crap = ccn * ccn * (1 - cov) ** 3 + ccn
        if crap > max_crap:
            offenders.append((crap, ccn, cov, f"{func}@{start}-{end}@{path}"))

    if not offenders:
        print(f"  {GREEN}✓{RESET} CRAP: all functions below {max_crap}")
        return
    offenders.sort(reverse=True)
    print(f"  {RED}✗{RESET} CRAP: {len(offenders)} function(s) exceed {max_crap}")
    for crap, ccn, cov, loc in offenders[:20]:
        print(f"    CRAP={crap:6.1f}  CCN={ccn:3d}  cov={cov * 100:5.1f}%  {loc}")
    sys.exit(1)
