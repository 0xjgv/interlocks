from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def test_standalone_behavior_attribution_creates_evidence(tmp_path: Path) -> None:
    _write_tiny_attribution_project(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "behavior-attribution"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert (tmp_path / ".interlocks" / "behavior-attribution.json").is_file()
    assert "[acceptance]" in result.stdout + result.stderr
    assert "[attribution]" in result.stdout + result.stderr


def _write_tiny_attribution_project(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "interlocks"
            version = "0.0.0"
            requires-python = ">=3.13"

            [tool.interlocks]
            src_dir = "pkg"
            test_dir = "tests"
            features_dir = "tests/features"
            acceptance_runner = "pytest-bdd"
            require_acceptance = false
            enforce_behavior_attribution = false
            """
        ),
        encoding="utf-8",
    )
    package = root / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    features = root / "tests" / "features"
    features.mkdir(parents=True)
    (features / "behavior.feature").write_text(
        textwrap.dedent(
            """\
            Feature: behavior attribution

              Scenario: tiny attribution capture
                Given a tiny behavior runs
            """
        ),
        encoding="utf-8",
    )
    step_defs = root / "tests" / "step_defs"
    step_defs.mkdir()
    (step_defs / "test_behavior.py").write_text(
        textwrap.dedent(
            """\
            from pytest_bdd import given, scenarios

            scenarios('../features/behavior.feature')

            @given('a tiny behavior runs')
            def tiny_behavior_runs() -> None:
                assert True
            """
        ),
        encoding="utf-8",
    )
