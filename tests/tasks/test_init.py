"""Tests for `interlocks init` (greenfield scaffold)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_init_scaffolds_greenfield_project(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "init")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "created pyproject.toml" in result.stdout
    assert "interlocks presets set progressive" in result.stdout
    assert "interlocks init-properties" in result.stdout
    pyproject = tmp_path / "pyproject.toml"
    assert pyproject.is_file()
    body = pyproject.read_text(encoding="utf-8")
    assert f'name = "{tmp_path.name}"' in body
    assert 'requires-python = ">=3.11"' in body
    assert "dependencies = []" in body
    assert 'dev = ["pytest>=8", "hypothesis>=6"]' in body
    assert "[tool.interlocks]" in body
    assert (tmp_path / "tests" / "__init__.py").is_file()
    smoke = tmp_path / "tests" / "test_smoke.py"
    assert smoke.is_file()
    assert "def test_smoke()" in smoke.read_text(encoding="utf-8")
    assert "git init" in result.stdout
    assert "interlocks setup" in result.stdout


def test_init_refuses_to_overwrite_existing_pyproject(tmp_path: Path) -> None:
    existing = tmp_path / "pyproject.toml"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    result = _run_cli(tmp_path, "init")
    assert result.returncode != 0
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert not (tmp_path / "tests").exists()
    assert "refusing to overwrite" in result.stdout


def test_init_json_scaffolds_greenfield_project(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "init", "--json")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["command"] == "init"
    assert payload["passed"] is True
    assert payload["status"] == "created"
    assert payload["project_name"] == tmp_path.name
    assert payload["created"] == ["pyproject.toml", "tests/__init__.py", "tests/test_smoke.py"]
    assert payload["files"] == [
        {"path": "pyproject.toml", "action": "created"},
        {"path": "tests/__init__.py", "action": "created"},
        {"path": "tests/test_smoke.py", "action": "created"},
    ]
    assert payload["next_actions"] == [
        "Run `git init`, then `interlocks setup` to install local integrations.",
        "Run `interlocks presets set progressive` for ratcheting defaults.",
        "Run `interlocks init-properties` to scaffold property tests.",
    ]
    assert (tmp_path / "pyproject.toml").is_file()
    assert (tmp_path / "tests" / "__init__.py").is_file()
    assert (tmp_path / "tests" / "test_smoke.py").is_file()


def test_init_json_refuses_to_overwrite_existing_pyproject(tmp_path: Path) -> None:
    existing = tmp_path / "pyproject.toml"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    result = _run_cli(tmp_path, "init", "--json")
    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["command"] == "init"
    assert payload["passed"] is False
    assert payload["status"] == "refused"
    assert payload["existing_path"] == "pyproject.toml"
    assert payload["created"] == []
    assert payload["error"] == "refusing to overwrite existing pyproject.toml"
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert not (tmp_path / "tests").exists()


def test_init_preserves_existing_tests_dir_and_creates_missing_files(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    result = _run_cli(tmp_path, "init")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "created pyproject.toml" in result.stdout
    assert "created tests/__init__.py" in result.stdout
    assert "created tests/test_smoke.py" in result.stdout
    assert (tmp_path / "pyproject.toml").is_file()
    assert (tmp_path / "tests" / "__init__.py").is_file()
    assert (tmp_path / "tests" / "test_smoke.py").is_file()


def test_init_preserves_existing_smoke_test_without_overwrite(tmp_path: Path) -> None:
    smoke = tmp_path / "tests" / "test_smoke.py"
    smoke.parent.mkdir()
    smoke.write_text("# custom\n", encoding="utf-8")

    result = _run_cli(tmp_path, "init", "--json")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert smoke.read_text(encoding="utf-8") == "# custom\n"
    payload = json.loads(result.stdout)
    assert payload["status"] == "scaffold-present"
    assert payload["created"] == ["pyproject.toml", "tests/__init__.py"]
    assert payload["files"] == [
        {"path": "pyproject.toml", "action": "created"},
        {"path": "tests/__init__.py", "action": "created"},
        {"path": "tests/test_smoke.py", "action": "kept"},
    ]


def test_init_in_process_scaffolds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """In-process call — lets coverage.py see the happy path."""
    monkeypatch.chdir(tmp_path)
    from interlocks.tasks.init import cmd_init

    cmd_init()
    out = capsys.readouterr().out
    assert "created pyproject.toml" in out
    assert "git init" in out
    assert "interlocks setup" in out
    assert "interlocks init-properties" in out
    assert (tmp_path / "pyproject.toml").is_file()
    assert (tmp_path / "tests" / "__init__.py").is_file()
    assert (tmp_path / "tests" / "test_smoke.py").is_file()


def test_init_in_process_json_scaffolds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "init", "--json"])
    from interlocks.tasks.init import cmd_init

    cmd_init()
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "created"
    assert payload["created"] == ["pyproject.toml", "tests/__init__.py", "tests/test_smoke.py"]
    assert payload["files"] == [
        {"path": "pyproject.toml", "action": "created"},
        {"path": "tests/__init__.py", "action": "created"},
        {"path": "tests/test_smoke.py", "action": "created"},
    ]


def test_init_in_process_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In-process call — exercises the refuse-to-overwrite branch for coverage."""
    existing = tmp_path / "pyproject.toml"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from interlocks.tasks.init import cmd_init

    with pytest.raises(SystemExit):
        cmd_init()
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert not (tmp_path / "tests").exists()


def test_init_in_process_json_refuses_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    existing = tmp_path / "pyproject.toml"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "init", "--json"])
    from interlocks.tasks.init import cmd_init

    with pytest.raises(SystemExit) as excinfo:
        cmd_init()

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "refused"
    assert payload["existing_path"] == "pyproject.toml"
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert not (tmp_path / "tests").exists()


def test_task_init_returns_none() -> None:
    from interlocks.tasks.init import task_init

    assert task_init() is None
