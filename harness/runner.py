"""Subprocess funnel + output formatting. Stdlib-only."""

from __future__ import annotations

import re
import subprocess
import sys

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"
VERBOSE = "--verbose" in sys.argv


def run(description: str, cmd: list[str], *, no_exit: bool = False) -> None:
    """Run command silently; show output only on failure."""
    if VERBOSE:
        print(f"  -> {' '.join(cmd)}")
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            if no_exit:
                return
            sys.exit(result.returncode)
        return

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        extra = _parse_unittest_summary(result.stderr) if "unittest" in cmd else ""
        print(f"  {GREEN}✓{RESET} {description}{extra}")
    else:
        print(f"  {RED}✗{RESET} {description}")
        print(f"{RED}Command failed: {' '.join(cmd)}{RESET}")
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")
        if no_exit:
            return
        sys.exit(result.returncode)


def _parse_unittest_summary(output: str) -> str:
    """Extract '(N tests, X.Xs)' from unittest output."""
    m = re.search(r"Ran (\d+) tests? in ([\d.]+s)", output)
    return f" ({m.group(1)} tests, {m.group(2)})" if m else ""
