#!/usr/bin/env python3
"""Create a local nested repo for manually exercising lint-fix optimization."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lintfix_playground_lib import REPO_ROOT, create_optimizer_repo

DEFAULT_TARGET = REPO_ROOT / ".factory" / "playgrounds" / "lintfix-optimizer"


def create_playground(target: Path = DEFAULT_TARGET, *, repo_root: Path = REPO_ROOT) -> Path:
    """Recreate ``target`` as a nested git repo with a dirty lint-fix workload.

    Fixtures and git wiring come from :mod:`lintfix_playground_lib`; this
    wrapper only adds the strict single-path guard so the destructive
    recreate can never escape the one expected playground directory.
    """
    target = target.resolve()
    _assert_safe_target(target, repo_root=repo_root)
    return create_optimizer_repo(target, playgrounds_root=repo_root / ".factory" / "playgrounds")


def _assert_safe_target(target: Path, *, repo_root: Path) -> None:
    playground_root = (repo_root / ".factory" / "playgrounds").resolve()
    expected = (playground_root / "lintfix-optimizer").resolve()
    if target != expected:
        msg = f"refusing to recreate unexpected target: {target}"
        raise ValueError(msg)


def _commands(target: Path, *, repo_root: Path) -> tuple[str, ...]:
    prefix = f"PYTHONPATH={repo_root}"
    return (
        f"cd {target}",
        f"{prefix} {sys.executable} -m interlocks.cli fix-plan --base=HEAD",
        f"{prefix} {sys.executable} -m interlocks.cli fix-optimize --base=HEAD",
        (
            f"{prefix} {sys.executable} -m interlocks.cli fix-optimize --base=HEAD "
            f'--apply --verify-cmd="{sys.executable} -c pass"'
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    target = create_playground()
    print(f"created lint-fix optimizer playground: {target}")
    print()
    print("Try:")
    for command in _commands(target, repo_root=REPO_ROOT):
        print(f"  {command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
