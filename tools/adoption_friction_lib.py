"""Generated repo fixtures for the adoption-friction lab."""

from __future__ import annotations

import json
import os
import shutil
import textwrap
import time
from typing import TYPE_CHECKING

try:
    from lintfix_playground_lib import (
        PLAYGROUNDS_ROOT,
        git,
        init_git_repo,
        write_files,
        write_text,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised when imported as tools.*
    from tools.lintfix_playground_lib import (
        PLAYGROUNDS_ROOT,
        git,
        init_git_repo,
        write_files,
        write_text,
    )

if TYPE_CHECKING:
    from pathlib import Path

ADOPTION_ROOT = PLAYGROUNDS_ROOT / "adoption-friction"

SMOKE_TEST = textwrap.dedent(
    """\
    import unittest


    class SmokeTest(unittest.TestCase):
        def test_smoke(self) -> None:
            self.assertTrue(True)
    """
)

BARE_DIRTY = textwrap.dedent(
    """\
    import os


    def answer():
        return 42
    """
)

BARE_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "bare-team"
    version = "0.0.0"
    requires-python = ">=3.11"
    """
)

LEGACY_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "legacy-team"
    version = "0.0.0"
    requires-python = ">=3.11"

    [tool.ruff]
    target-version = "py311"
    line-length = 99

    [tool.ruff.lint]
    select = ["F", "I", "W", "UP"]
    """
)

PARTIAL_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "partial-team"
    version = "0.0.0"
    requires-python = ">=3.11"

    [tool.ruff]
    target-version = "py311"
    line-length = 99

    [tool.ruff.lint]
    select = ["F", "I"]

    [tool.interlocks]
    preset = "baseline"
    src_dir = "src/partial"
    test_dir = "tests"
    coverage_min = 0
    crap_max = 1000.0
    enforce_crap = false
    skip = ["audit", "deps"]
    """
)

PROGRESSIVE_PYPROJECT = PARTIAL_PYPROJECT.replace(
    'name = "partial-team"',
    'name = "progressive-team"',
).replace('preset = "baseline"', 'preset = "progressive"')

STRICT_PYPROJECT = PARTIAL_PYPROJECT.replace(
    'name = "partial-team"',
    'name = "strict-team"',
).replace('preset = "baseline"', 'preset = "strict"')

LEGACY_CLEAN = {
    "src/legacy/__init__.py": '"""Legacy package."""\n',
    "src/legacy/core.py": textwrap.dedent(
        """\
        import os
        import sys


        def value() -> str:
            return os.name + sys.version
        """
    ),
    "tests/test_smoke.py": SMOKE_TEST,
}

LEGACY_AI_PATCH = {
    "src/legacy/core.py": textwrap.dedent(
        """\
        import sys
        import os
        import json


        def value() -> str:
            return os.name + sys.version
        """
    ),
    "src/legacy/typing_probe.py": textwrap.dedent(
        """\
        from typing import Optional


        def coerce(x: Optional[int]) -> int:
            return x or 0
        """
    ),
    "tests/test_smoke.py": "def test_smoke() -> None:\n    assert False\n",
}


def prepare_target(target: Path, *, root: Path) -> Path:
    target = target.resolve()
    root = root.resolve()
    if root not in target.parents:
        msg = f"refusing to recreate target outside {root}: {target}"
        raise ValueError(msg)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    return target


def create_bare_repo(target: Path, *, root: Path = ADOPTION_ROOT) -> Path:
    target = prepare_target(target, root=root)
    write_text(target / "pyproject.toml", BARE_PYPROJECT)
    write_text(target / "app.py", "def answer():\n    return 1\n")
    init_git_repo(target)
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "baseline")
    write_text(target / "app.py", BARE_DIRTY)
    return target


def create_legacy_repo(target: Path, *, root: Path = ADOPTION_ROOT) -> Path:
    target = prepare_target(target, root=root)
    write_text(target / "pyproject.toml", LEGACY_PYPROJECT)
    write_files(target, LEGACY_CLEAN)
    init_git_repo(target)
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "baseline")
    write_files(target, LEGACY_AI_PATCH)
    return target


def create_partial_repo(target: Path, *, root: Path = ADOPTION_ROOT) -> Path:
    target = prepare_target(target, root=root)
    write_text(target / "pyproject.toml", PARTIAL_PYPROJECT)
    write_files(
        target,
        {
            "src/partial/__init__.py": '"""Partial package."""\n',
            "src/partial/core.py": "def value() -> int:\n    return 1\n",
            "tests/test_smoke.py": SMOKE_TEST,
        },
    )
    init_git_repo(target)
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "baseline")
    return target


def create_progressive_repo(target: Path, *, root: Path = ADOPTION_ROOT) -> Path:
    target = prepare_target(target, root=root)
    write_text(target / "pyproject.toml", PROGRESSIVE_PYPROJECT)
    write_files(
        target,
        {
            "src/partial/__init__.py": '"""Progressive package."""\n',
            "src/partial/core.py": "import os\n\n\ndef value() -> int:\n    return 1\n",
            "tests/test_smoke.py": SMOKE_TEST,
        },
    )
    write_text(
        target / ".interlocks" / "baseline.json",
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-01-01T00:00:00Z",
                "advanced_from_sha": "seed",
                "floors": {"lint_violations_max": 0, "coverage_min": 0},
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
    )
    write_text(
        target / ".interlocks" / "run-summary.json",
        json.dumps(
            {
                "schema_version": 1,
                "coverage_pct": 0,
                "lint_violations": 1,
                "created_at": time.time(),
            },
            sort_keys=True,
        )
        + "\n",
    )
    init_git_repo(target)
    git(target, "add", "-A")
    git(target, "commit", "-q", "-m", "baseline")
    return target


def create_strict_repo(target: Path, *, root: Path = ADOPTION_ROOT) -> Path:
    target = prepare_target(target, root=root)
    write_text(target / "pyproject.toml", STRICT_PYPROJECT)
    write_files(
        target,
        {
            "src/partial/__init__.py": '"""Strict package."""\n',
            "src/partial/core.py": "def value() -> int:\n    return 1\n",
            "tests/test_smoke.py": SMOKE_TEST,
        },
    )
    init_git_repo(target)
    return target


def isolated_env(target: Path, *, repo_root: Path) -> dict[str, str]:
    """Return a cold-start-ish environment for running interlocks in ``target``."""
    env = os.environ.copy()
    env["HOME"] = str(target / ".lab-home")
    env["XDG_CACHE_HOME"] = str(target / ".lab-cache")
    env["UV_CACHE_DIR"] = str(target / ".lab-uv-cache")
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing}" if existing else str(repo_root)
    return env
