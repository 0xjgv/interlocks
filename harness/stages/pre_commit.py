"""Pre-commit stage — staged checks + tests if source files staged."""

from __future__ import annotations

from harness.git import staged_py_files
from harness.paths import SRC_DIR
from harness.tasks.fix import cmd_fix
from harness.tasks.format import cmd_format
from harness.tasks.test import cmd_test
from harness.tasks.typecheck import cmd_typecheck


def cmd_pre_commit() -> None:
    """Staged checks + tests if source files staged."""
    files = staged_py_files()
    if not files:
        print("No staged Python files — skipping checks")
        return

    print("\n=== Pre-commit Checks ===\n")
    cmd_fix(files)
    cmd_format(files)
    cmd_typecheck()

    if any(f.startswith(f"{SRC_DIR}/") for f in files):
        cmd_test()
