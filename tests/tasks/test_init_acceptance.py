"""Tests for `interlocks init-acceptance`."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "init-probe"
    version = "0.0.0"
    requires-python = ">=3.11"
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    return tmp_path


def _run_cli(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )


def test_init_acceptance_scaffolds_layout(tmp_project: Path) -> None:
    result = _run_cli(tmp_project, "init-acceptance")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "created tests/features/example.feature" in result.stdout
    assert "created tests/step_defs/test_example.py" in result.stdout
    assert "created tests/step_defs/conftest.py" in result.stdout
    assert "next: add `pytest-bdd>=8`" in result.stdout
    assert "next: run `interlocks acceptance`" in result.stdout
    assert (tmp_project / "tests" / "features" / "example.feature").is_file()
    assert (tmp_project / "tests" / "step_defs" / "test_example.py").is_file()
    assert (tmp_project / "tests" / "step_defs" / "conftest.py").is_file()
    feature = (tmp_project / "tests" / "features" / "example.feature").read_text(encoding="utf-8")
    assert "Scenario:" in feature


def test_init_acceptance_refuses_to_overwrite(tmp_project: Path) -> None:
    (tmp_project / "tests" / "features").mkdir()
    existing = tmp_project / "tests" / "features" / "example.feature"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    result = _run_cli(tmp_project, "init-acceptance")
    assert result.returncode != 0
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert "refusing to overwrite" in result.stdout


def test_init_acceptance_json_scaffolds_layout(tmp_project: Path) -> None:
    result = _run_cli(tmp_project, "init-acceptance", "--json")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["command"] == "init-acceptance"
    assert payload["passed"] is True
    assert payload["status"] == "created"
    assert payload["created"] == [
        "tests/features/example.feature",
        "tests/step_defs/test_example.py",
        "tests/step_defs/conftest.py",
    ]
    assert payload["next_actions"] == [
        "Add `pytest-bdd>=8` to test/dev dependencies if it is missing.",
        "Create or sync the project environment if `interlocks doctor` reports one missing.",
        "Replace the example scenario with project behavior.",
        "Run `interlocks acceptance`.",
    ]
    assert (tmp_project / "tests" / "features" / "example.feature").is_file()
    assert (tmp_project / "tests" / "step_defs" / "test_example.py").is_file()
    assert (tmp_project / "tests" / "step_defs" / "conftest.py").is_file()


def test_init_acceptance_json_refuses_to_overwrite(tmp_project: Path) -> None:
    (tmp_project / "tests" / "features").mkdir()
    existing = tmp_project / "tests" / "features" / "example.feature"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    result = _run_cli(tmp_project, "init-acceptance", "--json")
    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["command"] == "init-acceptance"
    assert payload["passed"] is False
    assert payload["status"] == "refused"
    assert payload["existing_paths"] == ["tests/features/example.feature"]
    assert payload["created"] == []
    assert payload["error"] == (
        "refusing to overwrite existing files: tests/features/example.feature"
    )
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert not (tmp_project / "tests" / "step_defs").exists()


def test_init_acceptance_refusal_payload_is_exact() -> None:
    from interlocks.tasks import init_acceptance as mod

    assert mod._init_acceptance_refusal_payload([
        "tests/features/example.feature",
        "tests/step_defs/test_example.py",
    ]) == {
        "command": "init-acceptance",
        "passed": False,
        "status": "refused",
        "error": (
            "refusing to overwrite existing files: "
            "tests/features/example.feature, tests/step_defs/test_example.py"
        ),
        "existing_paths": [
            "tests/features/example.feature",
            "tests/step_defs/test_example.py",
        ],
        "created": [],
        "next_actions": [
            "Inspect existing acceptance files before scaffolding the example layout."
        ],
    }


def test_init_acceptance_in_process_scaffolds(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """In-process call — lets coverage.py see the happy path."""
    monkeypatch.chdir(tmp_project)
    from interlocks.tasks.init_acceptance import cmd_init_acceptance

    cmd_init_acceptance()
    out = capsys.readouterr().out
    assert "created tests/features/example.feature" in out
    assert "next: replace the example scenario with project behavior" in out
    assert (tmp_project / "tests" / "features" / "example.feature").is_file()
    assert (tmp_project / "tests" / "step_defs" / "test_example.py").is_file()
    assert (tmp_project / "tests" / "step_defs" / "conftest.py").is_file()


def test_init_acceptance_in_process_json_scaffolds(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "init-acceptance", "--json"])
    from interlocks.tasks.init_acceptance import cmd_init_acceptance

    cmd_init_acceptance()

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "created"
    assert payload["created"] == [
        "tests/features/example.feature",
        "tests/step_defs/test_example.py",
        "tests/step_defs/conftest.py",
    ]


def test_init_acceptance_in_process_refuses_overwrite(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In-process call — exercises the refuse-to-overwrite branch for coverage."""
    (tmp_project / "tests" / "features").mkdir()
    existing = tmp_project / "tests" / "features" / "example.feature"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    from interlocks.tasks.init_acceptance import cmd_init_acceptance

    with pytest.raises(SystemExit):
        cmd_init_acceptance()
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"


def test_init_acceptance_in_process_json_refuses_overwrite(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_project / "tests" / "features").mkdir()
    existing = tmp_project / "tests" / "features" / "example.feature"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "init-acceptance", "--json"])
    from interlocks.tasks.init_acceptance import cmd_init_acceptance

    with pytest.raises(SystemExit) as excinfo:
        cmd_init_acceptance()

    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "refused"
    assert payload["existing_paths"] == ["tests/features/example.feature"]
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
