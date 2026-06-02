"""Integration + unit tests for `interlocks gate arch` (import-linter contracts)."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "arch-probe"
    version = "0.0.1"
    requires-python = ">=3.11"
    dependencies = []

    [build-system]
    requires = ["setuptools>=61"]
    build-backend = "setuptools.build_meta"
    """
)

_SRC_INIT = '"""Src package."""\n\nVALUE = 1\n'
_TEST_INIT = '"""Tests package."""\n'
_CLEAN_TEST = textwrap.dedent(
    '''\
    """Clean test."""

    import unittest

    from arch_probe import VALUE


    class TestValue(unittest.TestCase):
        def test_value(self) -> None:
            self.assertEqual(VALUE, 1)
    '''
)


_PIN_DIRS = textwrap.dedent(
    """
    [tool.interlocks]
    src_dir = "arch_probe"
    test_dir = "tests"
    """
)

_DIRTY_INIT = textwrap.dedent(
    '''\
    """Src package that wrongly imports tests."""

    from tests import test_value  # noqa: F401
    '''
)


@pytest.fixture
def clean_project(tmp_path: Path) -> Path:
    """src and tests both packages; src does NOT import tests — default contract passes."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT + _PIN_DIRS, encoding="utf-8")
    src = tmp_path / "arch_probe"
    src.mkdir()
    (src / "__init__.py").write_text(_SRC_INIT, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text(_TEST_INIT, encoding="utf-8")
    (tests / "test_value.py").write_text(_CLEAN_TEST, encoding="utf-8")
    return tmp_path


@pytest.fixture
def dirty_project(clean_project: Path) -> Path:
    """Same layout, but src imports a test helper — default contract MUST fail."""
    (clean_project / "arch_probe" / "__init__.py").write_text(_DIRTY_INIT, encoding="utf-8")
    return clean_project


@pytest.fixture
def non_package_tests(tmp_path: Path) -> Path:
    """tests/ has no __init__.py — default contract can't be built, should skip gracefully."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT + _PIN_DIRS, encoding="utf-8")
    src = tmp_path / "arch_probe"
    src.mkdir()
    (src / "__init__.py").write_text(_SRC_INIT, encoding="utf-8")
    (tmp_path / "tests").mkdir()  # no __init__.py
    return tmp_path


def _run_arch(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "gate", "arch"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_arch_json(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "gate", "arch", "--json"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.slow
def test_arch_passes_on_clean_project(clean_project: Path) -> None:
    result = _run_arch(clean_project)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


@pytest.mark.slow
def test_arch_json_passes_on_clean_project(clean_project: Path) -> None:
    result = _run_arch_json(clean_project)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert payload["command"] == "arch"
    assert payload["passed"] is True
    assert payload["gates"][0]["name"] == "arch"
    assert result.stderr.startswith("interlocks: [arch]")


@pytest.mark.slow
def test_arch_fails_when_src_imports_tests(dirty_project: Path) -> None:
    result = _run_arch(dirty_project)
    assert result.returncode != 0
    assert "Production does not import tests" in (result.stdout + result.stderr)


@pytest.mark.slow
def test_arch_json_fails_when_src_imports_tests(dirty_project: Path) -> None:
    result = _run_arch_json(dirty_project)

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["command"] == "arch"
    assert payload["passed"] is False
    assert payload["gates"][0]["status"] == "fail"
    assert "lint-imports" in payload["gates"][0]["detail"]
    assert result.stderr.startswith("interlocks: [arch]")


@pytest.mark.slow
def test_arch_skips_when_tests_not_a_package(non_package_tests: Path) -> None:
    result = _run_arch(non_package_tests)
    # Skipped gracefully: exit 0 and a nudge message.
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "arch:" in result.stdout
    assert "default needs" in result.stdout


@pytest.mark.slow
def test_arch_json_skips_when_tests_not_a_package(non_package_tests: Path) -> None:
    result = _run_arch_json(non_package_tests)

    payload = json.loads(result.stdout)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert payload["command"] == "arch"
    assert payload["passed"] is True
    assert payload["status"] == "skipped"
    assert "default needs" in payload["reason"]
    assert payload["next_actions"]
    assert result.stderr == ""


@dataclass(frozen=True)
class _ArchProject:
    root: Path
    src: Path
    tests: Path


def _stub_load_config(
    monkeypatch: pytest.MonkeyPatch,
    project: _ArchProject,
    *,
    arch_template: str = "default",
    arch_layers: tuple[str, ...] = (),
) -> None:
    """Point arch's ``load_config`` at a real ``InterlockConfig`` for ``project_root``."""
    from dataclasses import replace

    from interlocks.config import clear_cache, load_config
    from interlocks.tasks import arch as arch_mod

    clear_cache()
    cfg = replace(
        load_config(project.root),
        src_dir=project.src,
        test_dir=project.tests,
        arch_template=arch_template,
        arch_layers=arch_layers,
    )
    monkeypatch.setattr(arch_mod, "load_config", lambda: cfg)


def test_task_arch_uses_user_contracts_when_declared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If pyproject has [tool.importlinter], we invoke lint-imports without --config."""
    from interlocks.tasks import arch as arch_mod

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "x"
            [tool.importlinter]
            root_package = "anything"
            """
        ),
        encoding="utf-8",
    )
    _stub_load_config(monkeypatch, _ArchProject(proj, proj / "src", proj / "tests"))
    task = arch_mod.task_arch()
    assert task is not None
    assert task.description == "Architecture (import-linter)"
    assert task.start_status == "running"
    assert "--config" not in task.cmd


def test_task_arch_synthesizes_default_when_no_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No contracts + both dirs are packages → we build a temp INI and pass --config."""
    from interlocks.tasks import arch as arch_mod

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    src = proj / "pkg"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    tests = proj / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")

    _stub_load_config(monkeypatch, _ArchProject(proj, src, tests))
    task = arch_mod.task_arch()
    assert task is not None
    assert task.description == "Architecture (default: src ↛ tests)"
    assert "--config" in task.cmd
    cfg_path = Path(task.cmd[task.cmd.index("--config") + 1])
    contents = cfg_path.read_text(encoding="utf-8")
    assert "type = forbidden" in contents
    assert "pkg" in contents and "tests" in contents


def test_task_arch_returns_none_when_tests_not_a_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from interlocks.tasks import arch as arch_mod

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    src = proj / "pkg"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (proj / "tests").mkdir()  # no __init__.py

    _stub_load_config(monkeypatch, _ArchProject(proj, src, proj / "tests"))
    assert arch_mod.task_arch() is None


def test_task_arch_layered_template_synthesizes_with_layers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """layered template + arch_layers → INI rendered with `type = layers`."""
    from interlocks.tasks import arch as arch_mod

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    src = proj / "pkg"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (proj / "tests").mkdir()  # tests dir doesn't matter for layered

    layers = ("pkg.high", "pkg.mid", "pkg.low")
    _stub_load_config(
        monkeypatch,
        _ArchProject(proj, src, proj / "tests"),
        arch_template="layered",
        arch_layers=layers,
    )
    task = arch_mod.task_arch()
    assert task is not None
    assert task.description == "Architecture (default: layered)"
    assert "--config" in task.cmd
    cfg_path = Path(task.cmd[task.cmd.index("--config") + 1])
    contents = cfg_path.read_text(encoding="utf-8")
    assert "type = layers" in contents
    for layer in layers:
        assert layer in contents


def test_task_arch_layered_skips_when_no_layers_defined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """layered template with empty arch_layers → task_arch None; cmd_arch warn-skips."""
    from interlocks.tasks import arch as arch_mod

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    src = proj / "pkg"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (proj / "tests").mkdir()

    _stub_load_config(
        monkeypatch,
        _ArchProject(proj, src, proj / "tests"),
        arch_template="layered",
        arch_layers=(),
    )
    assert arch_mod.task_arch() is None

    arch_mod.cmd_arch()
    out = capsys.readouterr().out
    assert "layered template selected" in out
    assert "arch_layers" in out


def test_arch_skip_reason_default_is_exact(tmp_path: Path) -> None:
    from interlocks.config import InterlockConfig
    from interlocks.tasks import arch as arch_mod

    cfg = InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "src",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
    )

    assert arch_mod._skip_reason(cfg) == (
        "arch: no [tool.importlinter] contracts — "
        "default needs src_dir and test_dir to be Python packages"
    )


def test_arch_skip_reason_layered_is_exact(tmp_path: Path) -> None:
    from interlocks.config import InterlockConfig
    from interlocks.tasks import arch as arch_mod

    cfg = InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "src",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
        arch_template="layered",
    )

    assert arch_mod._skip_reason(cfg) == (
        "arch: layered template selected but [tool.interlocks.arch_layers] layers is empty "
        "— list layer modules ordered top → bottom (high-level first)"
    )


def test_cmd_arch_json_skip_emits_exact_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks import arch as arch_mod

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    src = proj / "pkg"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    tests = proj / "tests"
    tests.mkdir()

    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "arch", "--json"])
    _stub_load_config(monkeypatch, _ArchProject(proj, src, tests))

    arch_mod.cmd_arch()

    assert json.loads(capsys.readouterr().out) == {
        "command": "arch",
        "passed": True,
        "status": "skipped",
        "reason": (
            "arch: no [tool.importlinter] contracts — "
            "default needs src_dir and test_dir to be Python packages"
        ),
        "next_actions": [
            "Add import-linter contracts or make the configured source and test dirs packages."
        ],
    }


def test_cmd_arch_json_runs_arch_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from interlocks.config import InterlockConfig
    from interlocks.runner import Task
    from interlocks.tasks import arch as arch_mod

    task = Task("Architecture", ["lint-imports"], label="arch")
    cfg = InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "src",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
    )
    calls: list[tuple[str, Task]] = []

    def fake_run_task_json(command: str, observed_task: Task) -> None:
        calls.append((command, observed_task))

    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "arch", "--json"])
    monkeypatch.setattr(arch_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(arch_mod, "task_arch", lambda: task)
    monkeypatch.setattr(arch_mod, "run_task_json", fake_run_task_json)

    arch_mod.cmd_arch()

    assert calls == [("arch", task)]


def test_cmd_arch_human_runs_arch_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from interlocks.config import InterlockConfig
    from interlocks.runner import Task
    from interlocks.tasks import arch as arch_mod

    task = Task("Architecture", ["lint-imports"], label="arch")
    cfg = InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "src",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
    )
    calls: list[Task] = []

    def fake_run(observed_task: Task) -> None:
        calls.append(observed_task)

    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "arch"])
    monkeypatch.setattr(arch_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(arch_mod, "task_arch", lambda: task)
    monkeypatch.setattr(arch_mod, "run", fake_run)

    arch_mod.cmd_arch()

    assert calls == [task]
