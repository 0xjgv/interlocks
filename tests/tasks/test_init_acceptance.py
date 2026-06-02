"""Tests for `interlocks init --acceptance`."""

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
    result = _run_cli(tmp_project, "init", "--acceptance")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "created tests/features/example.feature" in result.stdout
    assert "created tests/step_defs/test_example.py" in result.stdout
    assert "created tests/step_defs/conftest.py" in result.stdout
    assert "next: add `pytest-bdd>=8`" in result.stdout
    assert "next: run `interlocks gate acceptance`" in result.stdout
    assert (tmp_project / "tests" / "features" / "example.feature").is_file()
    assert (tmp_project / "tests" / "step_defs" / "test_example.py").is_file()
    assert (tmp_project / "tests" / "step_defs" / "conftest.py").is_file()
    feature = (tmp_project / "tests" / "features" / "example.feature").read_text(encoding="utf-8")
    assert "Scenario:" in feature


def test_init_acceptance_preserves_existing_files_and_creates_missing(tmp_project: Path) -> None:
    (tmp_project / "tests" / "step_defs").mkdir()
    existing = tmp_project / "tests" / "step_defs" / "conftest.py"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    result = _run_cli(tmp_project, "init", "--acceptance")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert "created tests/features/example.feature" in result.stdout
    assert "created tests/step_defs/test_example.py" in result.stdout
    assert "kept tests/step_defs/conftest.py" in result.stdout


def test_init_acceptance_json_scaffolds_layout(tmp_project: Path) -> None:
    result = _run_cli(tmp_project, "init", "--acceptance", "--json")
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["command"] == "init"
    assert payload["passed"] is True
    assert payload["status"] == "created"
    assert payload["created"] == [
        "tests/features/example.feature",
        "tests/step_defs/test_example.py",
        "tests/step_defs/conftest.py",
    ]
    assert payload["files"] == [
        {"path": "tests/features/example.feature", "action": "created"},
        {"path": "tests/step_defs/test_example.py", "action": "created"},
        {"path": "tests/step_defs/conftest.py", "action": "created"},
    ]
    assert payload["next_actions"] == [
        "Add `pytest-bdd>=8` to test/dev dependencies if it is missing.",
        "Create or sync the project environment if `interlocks doctor` reports one missing.",
        "Replace the example scenario with project behavior.",
        "Run `interlocks gate acceptance`.",
    ]
    assert (tmp_project / "tests" / "features" / "example.feature").is_file()
    assert (tmp_project / "tests" / "step_defs" / "test_example.py").is_file()
    assert (tmp_project / "tests" / "step_defs" / "conftest.py").is_file()


def test_init_acceptance_omits_dependency_action_when_pytest_bdd_declared(
    tmp_project: Path,
) -> None:
    (tmp_project / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "init-probe"
            version = "0.0.0"
            requires-python = ">=3.11"

            [dependency-groups]
            dev = ["pytest-bdd>=8"]
            """
        ),
        encoding="utf-8",
    )

    result = _run_cli(tmp_project, "init", "--acceptance", "--json")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    payload = json.loads(result.stdout)
    assert (
        "Add `pytest-bdd>=8` to test/dev dependencies if it is missing."
        not in payload["next_actions"]
    )
    assert "Run `interlocks gate acceptance`." in payload["next_actions"]


def test_init_acceptance_json_preserves_existing_files_and_creates_missing(
    tmp_project: Path,
) -> None:
    (tmp_project / "tests" / "step_defs").mkdir()
    existing = tmp_project / "tests" / "step_defs" / "conftest.py"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    result = _run_cli(tmp_project, "init", "--acceptance", "--json")
    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["command"] == "init"
    assert payload["passed"] is True
    assert payload["status"] == "scaffold-present"
    assert payload["created"] == [
        "tests/features/example.feature",
        "tests/step_defs/test_example.py",
    ]
    assert payload["files"] == [
        {"path": "tests/features/example.feature", "action": "created"},
        {"path": "tests/step_defs/test_example.py", "action": "created"},
        {"path": "tests/step_defs/conftest.py", "action": "kept"},
    ]
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert (tmp_project / "tests" / "features" / "example.feature").is_file()
    assert (tmp_project / "tests" / "step_defs" / "test_example.py").is_file()


def test_init_acceptance_keeps_domain_features_without_adding_example(tmp_project: Path) -> None:
    features = tmp_project / "tests" / "features"
    features.mkdir()
    domain = features / "billing.feature"
    domain.write_text(
        "Feature: Billing\n  Scenario: charge a card\n    Given a card\n",
        encoding="utf-8",
    )

    result = _run_cli(tmp_project, "init", "--acceptance")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "kept tests/features/" in result.stdout
    assert "next: run `interlocks gate acceptance`" in result.stdout
    assert not (features / "example.feature").exists()
    assert not (tmp_project / "tests" / "step_defs").exists()


def test_init_acceptance_json_keeps_domain_features_without_adding_example(
    tmp_project: Path,
) -> None:
    features = tmp_project / "tests" / "features"
    features.mkdir()
    domain = features / "billing.feature"
    domain.write_text(
        "Feature: Billing\n  Scenario: charge a card\n    Given a card\n",
        encoding="utf-8",
    )

    result = _run_cli(tmp_project, "init", "--acceptance", "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "command": "init",
        "passed": True,
        "status": "domain-acceptance-present",
        "created": [],
        "files": [],
        "domain_acceptance_feature_count": 1,
        "domain_acceptance_features": ["tests/features/billing.feature"],
        "next_actions": ["Run `interlocks gate acceptance`."],
    }
    assert not (features / "example.feature").exists()
    assert not (tmp_project / "tests" / "step_defs").exists()


def test_init_acceptance_success_payload_is_exact(tmp_path: Path) -> None:
    from interlocks.config import InterlockConfig
    from interlocks.tasks import init_acceptance as mod

    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    cfg = InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "pkg",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
    )
    files = [
        {"path": "tests/features/example.feature", "action": "kept"},
        {"path": "tests/step_defs/test_example.py", "action": "created"},
    ]

    assert mod._init_acceptance_success_payload(cfg, files) == {
        "command": "init",
        "passed": True,
        "status": "scaffold-present",
        "created": ["tests/step_defs/test_example.py"],
        "files": files,
        "next_actions": [
            "Add `pytest-bdd>=8` to test/dev dependencies if it is missing.",
            "Create or sync the project environment if `interlocks doctor` reports one missing.",
            "Replace the example scenario with project behavior.",
            "Run `interlocks gate acceptance`.",
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
    monkeypatch.setattr(sys, "argv", ["interlocks", "init", "--acceptance", "--json"])
    from interlocks.tasks.init_acceptance import cmd_init_acceptance

    cmd_init_acceptance()

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "created"
    assert payload["created"] == [
        "tests/features/example.feature",
        "tests/step_defs/test_example.py",
        "tests/step_defs/conftest.py",
    ]


def test_init_acceptance_in_process_preserves_existing_files(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_project / "tests" / "step_defs").mkdir()
    existing = tmp_project / "tests" / "step_defs" / "conftest.py"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    from interlocks.tasks.init_acceptance import cmd_init_acceptance

    cmd_init_acceptance()

    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
    assert (tmp_project / "tests" / "features" / "example.feature").is_file()
    assert (tmp_project / "tests" / "step_defs" / "test_example.py").is_file()


def test_init_acceptance_in_process_json_preserves_existing_files(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_project / "tests" / "step_defs").mkdir()
    existing = tmp_project / "tests" / "step_defs" / "conftest.py"
    existing.write_text("# pre-existing\n", encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "init", "--acceptance", "--json"])
    from interlocks.tasks.init_acceptance import cmd_init_acceptance

    cmd_init_acceptance()

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "scaffold-present"
    assert payload["files"][-1] == {"path": "tests/step_defs/conftest.py", "action": "kept"}
    assert existing.read_text(encoding="utf-8") == "# pre-existing\n"
