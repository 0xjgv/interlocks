"""Git helpers. Stdlib-only."""

from __future__ import annotations

import subprocess

from harness.paths import SRC_DIR, TEST_DIR


def staged_py_files() -> list[str]:
    """Return staged .py files under src/ and tests/, excluding deleted files."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=d", "--relative"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        f
        for f in result.stdout.strip().splitlines()
        if f.endswith(".py") and f.startswith((f"{SRC_DIR}/", f"{TEST_DIR}/"))
    ]


def changed_py_files() -> list[str]:
    """Return .py files with uncommitted changes under src/ and tests/."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        line[3:]
        for line in result.stdout.strip().splitlines()
        if len(line) > 3
        and line[3:].endswith(".py")
        and line[3:].startswith((f"{SRC_DIR}/", f"{TEST_DIR}/"))
    ]


def changed_py_files_vs_main() -> set[str]:
    """Return .py files changed vs origin/main on the current branch."""
    res = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {f.strip() for f in res.stdout.splitlines() if f.strip().endswith(".py")}


def stage(files: list[str]) -> None:
    """Stage the given files (no-op if list is empty)."""
    if not files:
        return
    subprocess.run(["git", "add", *files], check=False)
