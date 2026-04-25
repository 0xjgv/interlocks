"""Step defs for tests/features/interlock_stages.feature.

End-to-end stage smoke tests: materialize a minimal inline project, shell out
to ``python -m interlock.cli <stage>``, and assert exit-code + output-shape
contracts. Mirrors the ``_run_interlock`` pattern in ``test_interlock_cli.py`` but
with a per-scenario tmp cwd so each stage operates on an isolated project.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from tests.step_defs.conftest import make_tmp_project, run_interlock_in_cwd

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_stages.feature"))


@given("a minimal tmp project", target_fixture="tmp_project")
def _tmp_project(tmp_path: Path) -> Path:
    return make_tmp_project(tmp_path)


@when(
    parsers.parse('I run "interlock {stage}" in the tmp project'),
    target_fixture="stage_result",
)
def _run_stage(tmp_project: Path, stage: str) -> subprocess.CompletedProcess[str]:
    return run_interlock_in_cwd(tmp_project, stage)


@then(parsers.parse("the stage exits {code:d}"))
def _stage_exits(stage_result: subprocess.CompletedProcess[str], code: int) -> None:
    assert stage_result.returncode == code, (
        f"expected exit {code}, got {stage_result.returncode}\n"
        f"stdout:\n{stage_result.stdout}\nstderr:\n{stage_result.stderr}"
    )


@then(parsers.parse('the stage output contains "{fragment}"'))
def _stage_output_contains(stage_result: subprocess.CompletedProcess[str], fragment: str) -> None:
    combined = stage_result.stdout + stage_result.stderr
    assert fragment in combined, f"expected {fragment!r} in stage output; got:\n{combined}"
