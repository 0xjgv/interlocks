"""Integration tests for `interlocks hook pre-commit` stage."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PYPROJECT = """\
[project]
name = "tmp-proj"
version = "0.0.0"
requires-python = ">=3.11"

[tool.ruff]
target-version = "py311"
line-length = 99

[tool.basedpyright]
pythonVersion = "3.11"
typeCheckingMode = "standard"
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)


def _git_capture(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    # interlocks/ exists but without __init__.py so it doesn't shadow the installed pkg
    (tmp_path / "interlocks").mkdir()
    (tmp_path / "tests").mkdir()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@e.co")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _run_pre_commit(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "hook", "pre-commit"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pre_commit_skips_broad_format_and_leaves_staged_file(tmp_project: Path) -> None:
    (tmp_project / "tests" / "__init__.py").write_text("", encoding="utf-8")
    _git(tmp_project, "add", "-A")
    _git(tmp_project, "commit", "-q", "-m", "base")
    target = tmp_project / "tests" / "test_a.py"
    target.write_text("x = [1,2,3]\n", encoding="utf-8")
    _git(tmp_project, "add", "tests/test_a.py")

    result = _run_pre_commit(tmp_project)

    assert result.returncode == 0, result.stdout + result.stderr
    assert target.read_text(encoding="utf-8") == "x = [1,2,3]\n"
    diff = _git_capture(tmp_project, "diff", "--cached", "tests/test_a.py")
    assert "x = [1,2,3]" in diff
    payload = json.loads((tmp_project / ".lintfix" / "optimize.json").read_text(encoding="utf-8"))
    assert payload["not_selected"][0]["reason"] == "would exceed outside-author-hunk budget"


def test_pre_commit_noop_when_nothing_staged(tmp_project: Path) -> None:
    result = _run_pre_commit(tmp_project)

    assert result.returncode == 0, result.stderr
    assert "pre-commit: skipped — no staged python files" in result.stdout


def test_pre_commit_noop_in_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from interlocks.stages import pre_commit as pre_commit_mod

    monkeypatch.setattr(pre_commit_mod, "staged_py_files", list)
    pre_commit_mod.cmd_pre_commit()
    assert "pre-commit: skipped — no staged python files" in capsys.readouterr().out


def test_pre_commit_noop_json_in_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from interlocks.stages import pre_commit as pre_commit_mod

    monkeypatch.setattr(sys, "argv", ["interlocks", "hook", "pre-commit", "--json"])
    monkeypatch.setattr(pre_commit_mod, "staged_py_files", list)

    pre_commit_mod.cmd_pre_commit()

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "pre-commit"
    assert payload["passed"] is True
    assert payload["gates"] == []
    assert payload["skipped"] == [{"name": "pre-commit", "reason": "no staged Python files"}]


def test_pre_commit_json_reports_stage_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from types import SimpleNamespace

    from interlocks.runner import Task, record_result
    from interlocks.skip import SkipPolicy
    from interlocks.stages import pre_commit as pre_commit_mod

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(sys, "argv", ["interlocks", "hook", "pre-commit", "--json"])
    monkeypatch.setattr(pre_commit_mod, "load_config", lambda: SimpleNamespace(src_dir_arg="src"))
    monkeypatch.setattr(
        pre_commit_mod,
        "current_skip_policy",
        lambda: SkipPolicy(frozenset(), "cli"),
    )
    monkeypatch.setattr(pre_commit_mod, "staged_py_files", lambda: ["src/mod.py"])
    monkeypatch.setattr(pre_commit_mod, "stage", lambda files: calls.append(("stage", files)))
    monkeypatch.setattr(
        pre_commit_mod,
        "task_typecheck",
        lambda: Task("Type check", ["python", "-c", "pass"], label="typecheck"),
    )
    monkeypatch.setattr(
        pre_commit_mod,
        "task_test",
        lambda: Task("Run tests", ["python", "-c", "pass"], label="test"),
    )

    def fake_budgeted_mutation(_policy: object) -> None:
        calls.append(("budgeted-mutation", None))
        record_result("fix", status="ok", elapsed=None, detail=None)

    def fake_run_tasks(tasks: list[Task]) -> None:
        labels = [task.label or task.description for task in tasks]
        calls.append(("run_tasks", labels))
        for label in labels:
            record_result(label, status="ok", elapsed=None, detail=None)

    monkeypatch.setattr(pre_commit_mod, "_run_budgeted_mutation", fake_budgeted_mutation)
    monkeypatch.setattr(pre_commit_mod, "run_tasks", fake_run_tasks)

    pre_commit_mod.cmd_pre_commit()

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "pre-commit"
    assert payload["passed"] is True
    assert [gate["name"] for gate in payload["gates"]] == ["fix", "typecheck", "test"]
    assert payload["skipped"] == []
    assert calls == [
        ("budgeted-mutation", None),
        ("stage", ["src/mod.py"]),
        ("run_tasks", ["typecheck", "test"]),
    ]


@pytest.mark.parametrize(
    ("staged", "expected_task_descs"),
    [
        (["interlocks/mod.py"], ["Type check", "Run tests"]),
        (["tests/test_x.py"], ["Type check"]),
    ],
    ids=["src-runs-tests", "non-src-skips-tests"],
)
def test_pre_commit_in_process_dispatches(
    monkeypatch: pytest.MonkeyPatch,
    staged: list[str],
    expected_task_descs: list[str],
) -> None:
    calls = _pre_commit_calls(monkeypatch, staged)

    from interlocks.stages import pre_commit as pre_commit_mod

    pre_commit_mod.cmd_pre_commit()
    assert calls == [
        ("budgeted-mutation", None),
        ("stage", staged),
        ("run_tasks", expected_task_descs),
    ]


@pytest.mark.parametrize(
    "skip",
    ["fix", "format", "fix,format"],
    ids=["skip-fix", "skip-format", "skip-both-mutators"],
)
def test_pre_commit_skip_disables_restaging(
    monkeypatch: pytest.MonkeyPatch,
    skip: str,
) -> None:
    """Skipping `fix` or `format` skips the budgeted mutation, so nothing is re-staged.

    The mutation itself is skipped inside `run_budgeted_mutation` (stubbed here);
    pre-commit's own job is to drop the `stage(files)` re-stage when either
    alias label is skipped.
    """
    calls = _pre_commit_calls(monkeypatch, ["interlocks/mod.py"], skip=skip)

    from interlocks.stages import pre_commit as pre_commit_mod

    pre_commit_mod.cmd_pre_commit()

    assert [call[0] for call in calls] == ["budgeted-mutation", "run_tasks"]


def test_pre_commit_delegates_parallel_task_skips_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _pre_commit_calls(monkeypatch, ["interlocks/mod.py"], skip="typecheck,test")

    from interlocks.stages import pre_commit as pre_commit_mod

    pre_commit_mod.cmd_pre_commit()

    assert calls[-1] == ("run_tasks", ["Type check", "Run tests"])


def _pre_commit_calls(
    monkeypatch: pytest.MonkeyPatch, staged: list[str], *, skip: str | None = None
) -> list[tuple[str, object]]:
    from interlocks.stages import pre_commit as pre_commit_mod
    from interlocks.tasks import typecheck as typecheck_mod

    calls: list[tuple[str, object]] = []
    argv = ["interlocks", "hook", "pre-commit"]
    if skip is not None:
        argv.append(f"--skip={skip}")
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(typecheck_mod, "project_env_ready", lambda _cfg: True)
    monkeypatch.setattr(pre_commit_mod, "staged_py_files", lambda: staged)
    monkeypatch.setattr(
        pre_commit_mod,
        "_run_budgeted_mutation",
        lambda _policy: calls.append(("budgeted-mutation", None)),
    )
    monkeypatch.setattr(pre_commit_mod, "stage", lambda files: calls.append(("stage", files)))
    monkeypatch.setattr(
        pre_commit_mod,
        "run_tasks",
        lambda tasks: calls.append(("run_tasks", [task.description for task in tasks])),
    )
    return calls
