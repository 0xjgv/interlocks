"""Integration + unit tests for `interlocks gate deps` (deptry dependency hygiene)."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PYPROJECT_TEMPLATE = textwrap.dedent(
    """\
    [project]
    name = "deps-probe"
    version = "0.0.1"
    requires-python = ">=3.11"
    dependencies = [{deps}]

    [build-system]
    requires = ["setuptools>=61"]
    build-backend = "setuptools.build_meta"
    """
)

_SRC_CORE = "import os\n\nHOME = os.environ.get('HOME', '')\n"


def _make_probe(tmp_path: Path, deps: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        _PYPROJECT_TEMPLATE.format(deps=deps), encoding="utf-8"
    )
    pkg = tmp_path / "deps_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Minimal package."""\n', encoding="utf-8")
    (pkg / "core.py").write_text(_SRC_CORE, encoding="utf-8")
    return tmp_path


@pytest.fixture
def clean_project(tmp_path: Path) -> Path:
    return _make_probe(tmp_path, deps="")


@pytest.fixture
def dirty_project(tmp_path: Path) -> Path:
    return _make_probe(tmp_path, deps='"requests>=2"')


def _run_deps(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "gate", "deps"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.slow
def test_deps_passes_on_clean_project(clean_project: Path) -> None:
    result = _run_deps(clean_project)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


@pytest.mark.slow
def test_deps_fails_on_unused_dependency(dirty_project: Path) -> None:
    result = _run_deps(dirty_project)
    assert result.returncode != 0
    assert "DEP002" in (result.stdout + result.stderr)


def test_deps_invokes_deptry_with_known_first_party(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process: cmd_deps builds a Task wrapping deptry + --known-first-party from src_dir."""
    from interlocks.runner import Task
    from interlocks.tasks import deps as deps_mod

    captured: dict[str, Task] = {}

    def fake_run(task: Task, **_: object) -> None:
        captured["task"] = task

    monkeypatch.setattr(deps_mod, "run", fake_run)
    deps_mod.cmd_deps()

    task = captured["task"]
    assert task.description == "Deps (deptry)"
    assert task.start_status == "running"
    cmd = task.cmd
    assert any("deptry" in part for part in cmd), f"deptry missing in cmd: {cmd}"
    assert "--known-first-party" in cmd
    kfp_idx = cmd.index("--known-first-party")
    assert cmd[kfp_idx + 1] == "interlocks"


def test_deps_json_uses_shared_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    from interlocks.runner import Task
    from interlocks.tasks import deps as deps_mod

    captured: list[tuple[str, Task]] = []
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "deps", "--json"])
    monkeypatch.setattr(
        deps_mod,
        "run_task_json",
        lambda command, task: captured.append((command, task)),
    )

    deps_mod.cmd_deps()

    assert len(captured) == 1
    command, task = captured[0]
    assert command == "deps"
    assert task.description == "Deps (deptry)"


def test_deps_json_reports_gate_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.runner import Task
    from interlocks.tasks import deps as deps_mod

    task = Task("Deps (deptry)", [sys.executable, "-c", ""], label="deps", display="deptry")
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "deps", "--json"])
    monkeypatch.setattr(deps_mod, "task_deps", lambda: task)

    deps_mod.cmd_deps()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "deps"
    assert payload["passed"] is True
    assert payload["gates"][0]["name"] == "deps"


def test_deps_excludes_property_tests_from_root_src_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.deps import task_deps

    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "probe-project"
            version = "0.0.0"
            requires-python = ">=3.11"

            [tool.interlocks]
            src_dir = "."
            properties_dir = "properties"
            """
        ),
        encoding="utf-8",
    )
    properties = tmp_path / "properties"
    properties.mkdir()
    (properties / "test_example_properties.py").write_text(
        "from hypothesis import given\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    clear_cache()
    try:
        cmd = task_deps().cmd
    finally:
        clear_cache()

    assert "--extend-exclude" in cmd
    assert cmd[cmd.index("--extend-exclude") + 1] == "properties"
