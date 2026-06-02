"""Integration tests for interlocks.tasks.test."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.conftest import stub_project_venv

PYPROJECT = textwrap.dedent("""
    [project]
    name = "sample"
    version = "0.0.0"
    requires-python = ">=3.11"
""")

PASSING = textwrap.dedent("""
    import unittest

    class Passing(unittest.TestCase):
        def test_ok(self) -> None:
            self.assertEqual(1 + 1, 2)
""")

FAILING = textwrap.dedent("""
    import unittest

    class Failing(unittest.TestCase):
        def test_fail(self) -> None:
            self.assertEqual(1 + 1, 3)
""")


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    stub_project_venv(tmp_path)
    return tmp_path


@pytest.mark.parametrize(("source", "expected_rc"), [(PASSING, 0), (FAILING, 1)])
def test_test_cli(tmp_project: Path, source: str, expected_rc: int) -> None:
    (tmp_project / "tests" / "test_sample.py").write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "gate", "test"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_rc


def test_test_passing_in_process(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks.test import cmd_test

    (tmp_project / "tests" / "test_sample.py").write_text(PASSING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_test()

    out = capsys.readouterr().out
    assert "[test]" in out
    assert any(token in out for token in ("ok", "passed", "1 test"))


def test_test_failing_in_process(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from interlocks.tasks.test import cmd_test

    (tmp_project / "tests" / "test_sample.py").write_text(FAILING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as exc:
        cmd_test()
    assert exc.value.code != 0


def test_test_json_passing_in_process(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks.test import cmd_test

    (tmp_project / "tests" / "test_sample.py").write_text(PASSING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "test", "--json"])

    cmd_test()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "test"
    assert payload["passed"] is True
    assert payload["gates"][0]["name"] == "test"
    assert payload["skipped"] == []
    assert captured.err.startswith("interlocks: [test]")


def test_test_json_failing_in_process(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks.test import cmd_test

    (tmp_project / "tests" / "test_sample.py").write_text(FAILING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "test", "--json"])

    with pytest.raises(SystemExit) as exc:
        cmd_test()

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert payload["command"] == "test"
    assert payload["passed"] is False
    assert payload["gates"][0]["status"] == "fail"


@pytest.fixture
def tmp_project_no_tests(tmp_path: Path) -> Path:
    """Greenfield layout: pyproject + src/, no tests/ dir on disk."""
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "sample.py").write_text("", encoding="utf-8")
    stub_project_venv(tmp_path)
    return tmp_path


def test_task_test_returns_none_without_test_dir(
    tmp_project_no_tests: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.test import task_test

    monkeypatch.chdir(tmp_project_no_tests)
    clear_cache()
    assert task_test() is None


def test_cmd_test_skips_without_test_dir(
    tmp_project_no_tests: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.test import cmd_test

    monkeypatch.chdir(tmp_project_no_tests)
    clear_cache()
    cmd_test()
    captured = capsys.readouterr()
    assert "no test dir detected" in captured.out


def test_cmd_test_json_skips_without_test_dir(
    tmp_project_no_tests: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.test import cmd_test

    monkeypatch.chdir(tmp_project_no_tests)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "test", "--json"])
    clear_cache()

    cmd_test()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "command": "test",
        "passed": True,
        "status": "skipped",
        "reason": "no test dir detected",
        "next_actions": ["Run `interlocks init` to scaffold tests/."],
    }


def test_cmd_check_skips_tests_without_test_dir(
    tmp_project_no_tests: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`interlocks check` in a greenfield project skips tests + exits clean."""
    from interlocks.config import clear_cache
    from interlocks.stages.check import cmd_check

    monkeypatch.chdir(tmp_project_no_tests)
    clear_cache()
    cmd_check()
    captured = capsys.readouterr()
    assert "no test dir detected" in captured.out


def test_cmd_test_skips_without_project_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Env-skip nudge wins over the no-test-dir nudge and over running tests."""
    from interlocks.config import clear_cache
    from interlocks.tasks.test import cmd_test

    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()  # test dir present — env-skip must still win
    monkeypatch.chdir(tmp_path)
    clear_cache()

    cmd_test()  # must not raise SystemExit
    out = capsys.readouterr().out
    assert "test: skipped — no project environment" in out
    assert "no test dir detected" not in out


def test_cmd_test_json_skips_without_project_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.test import cmd_test

    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "test", "--json"])
    clear_cache()

    cmd_test()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "test"
    assert payload["passed"] is True
    assert payload["status"] == "skipped"
    assert "no project environment" in payload["reason"]
    assert payload["next_actions"] == [
        "Create or sync the project environment, then rerun `interlocks gate test`."
    ]


def test_task_test_unchanged_when_env_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """task_test() itself still returns a Task whenever a test dir exists —
    the env guard lives only in cmd_test (design Q4)."""
    from interlocks.config import clear_cache
    from interlocks.tasks.test import task_test

    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    monkeypatch.chdir(tmp_path)
    clear_cache()

    assert task_test() is not None


def test_task_test_appends_extra_pytest_args(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.test import task_test

    (tmp_project / "pyproject.toml").write_text(
        PYPROJECT + '\n[tool.interlocks]\ntest_runner = "pytest"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_project)
    clear_cache()

    task = task_test(extra_pytest_args=("--ignore=tests/step_defs",))

    assert task is not None
    assert task.cmd[-1] == "--ignore=tests/step_defs"
    assert task.start_status == "running"
