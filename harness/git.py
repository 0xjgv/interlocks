"""Git helpers. Stdlib-only."""

from __future__ import annotations

import subprocess

from harness.config import load_config


def _src_test_prefixes() -> tuple[str, ...]:
    cfg = load_config()
    prefixes: list[str] = []
    for name in (cfg.src_dir_arg, cfg.test_dir_arg):
        if name and name != ".":
            prefixes.append(f"{name}/")
    return tuple(prefixes) or ("",)


def staged_py_files() -> list[str]:
    """Return staged .py files under the project's src/test dirs, excluding deletions."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=d", "--relative"],
        capture_output=True,
        text=True,
        check=False,
    )
    prefixes = _src_test_prefixes()
    return [
        f
        for f in result.stdout.strip().splitlines()
        if f.endswith(".py") and f.startswith(prefixes)
    ]


def changed_py_files() -> list[str]:
    """Return .py files with uncommitted changes under the project's src/test dirs."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    prefixes = _src_test_prefixes()
    return [
        line[3:]
        for line in result.stdout.strip().splitlines()
        if len(line) > 3 and line[3:].endswith(".py") and line[3:].startswith(prefixes)
    ]


def changed_py_files_vs(ref: str) -> set[str]:
    """Return .py files changed vs ``ref`` on the current branch (renames followed).

    Filtered by the project's configured src/test dirs, matching the
    behaviour of ``staged_py_files`` and ``changed_py_files``.
    """
    res = subprocess.run(
        ["git", "diff", "--name-only", "--find-renames=90%", f"{ref}...HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    prefixes = _src_test_prefixes()
    return {f for f in res.stdout.splitlines() if f.endswith(".py") and f.startswith(prefixes)}


def changed_py_files_vs_main() -> set[str]:
    """Return .py files changed vs origin/main on the current branch."""
    return changed_py_files_vs("origin/main")


def stage(files: list[str]) -> None:
    """Stage the given files (no-op if list is empty)."""
    if not files:
        return
    subprocess.run(["git", "add", *files], check=False)
