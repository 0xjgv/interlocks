"""Step defs for tests/features/interlock_stages.feature.

End-to-end stage smoke tests: materialize a minimal inline project, shell out
to ``python -m interlocks.cli <stage>``, and assert exit-code + output-shape
contracts. Mirrors the ``_run_interlock`` pattern in ``test_interlock_cli.py`` but
with a per-scenario tmp cwd so each stage operates on an isolated project.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from tests.step_defs.conftest import make_tmp_project, run_interlock_in_cwd

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_stages.feature"))


@given("a minimal tmp project", target_fixture="tmp_project")
def _tmp_project(tmp_path: Path) -> Path:
    return make_tmp_project(tmp_path)


@given("a tmp project with behavior-attribution failure", target_fixture="tmp_project")
def _tmp_project_with_attribution_failure(tmp_path: Path) -> Path:
    from tests.step_defs.test_interlock_tasks import _make_behavior_attribution_unattributed

    _make_behavior_attribution_unattributed(tmp_path)
    return tmp_path


@given("a minimal tmp project initialized as a git repo", target_fixture="tmp_project")
def _tmp_project_git(tmp_path: Path) -> Path:
    project = make_tmp_project(tmp_path)
    _git_init_with_baseline(project)
    return project


@given("the tmp project has a changed Python file")
def _tmp_project_changed_file(tmp_project: Path) -> None:
    """Create an untracked .py file under the configured src dir.

    ``changed_py_files_vs`` treats ``ls-files --others --exclude-standard``
    output as 'changed', so an untracked file is sufficient — no need to
    re-stage or commit.
    """
    new_file = tmp_project / "src" / "tmp" / "added.py"
    new_file.write_text('"""Added module."""\n\n\ndef hello() -> str:\n    return "hi"\n')


@given(parsers.parse('the tmp project sets changed_ref to "{ref}"'))
def _tmp_project_set_changed_ref(tmp_project: Path, ref: str) -> None:
    pyproject = tmp_project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + f'changed_ref = "{ref}"\n',
        encoding="utf-8",
    )


def _git_init_with_baseline(project: Path) -> None:
    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)

    _git("init", "-q", "-b", "main")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "Test")
    _git("add", "-A")
    _git("commit", "-q", "-m", "baseline")


@when(
    parsers.parse('I run "interlocks {stage}" in the tmp project'),
    target_fixture="stage_result",
)
def _run_stage(tmp_project: Path, stage: str) -> subprocess.CompletedProcess[str]:
    return run_interlock_in_cwd(tmp_project, *shlex.split(stage))


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
