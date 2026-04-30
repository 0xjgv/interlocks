"""Module entry point for behavior-attribution diagnostics."""

from __future__ import annotations

import sys

from interlocks.tasks.behavior_attribution import cmd_behavior_attribution

if __name__ == "__main__":
    try:
        cmd_behavior_attribution(refresh=False)
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensive diagnostic path
        print(f"behavior-attribution: validator failed: {exc}", file=sys.stderr)
        sys.exit(1)
