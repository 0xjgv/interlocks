"""Integration tests for interlocks.tasks.lint."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from interlocks import baseline, run_summary
from interlocks import config as cfg_mod
from interlocks.config import load_config
from interlocks.tasks import lint as lint_mod

PYPROJECT = textwrap.dedent("""
    [project]
    name = "sample"
    version = "0.0.0"
    requires-python = ">=3.11"

    [tool.ruff]
    target-version = "py311"
    line-length = 99

    [tool.ruff.lint]
    select = ["E", "F"]
""")

CLEAN = "x = 1\n"
VIOLATING = "x = y\n"  # F821 undefined-name


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(("source", "expected_rc"), [(CLEAN, 0), (VIOLATING, 1)])
def test_lint_cli(tmp_project: Path, source: str, expected_rc: int) -> None:
    (tmp_project / "sample.py").write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "lint"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_rc


def test_lint_clean_in_process(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks.lint import cmd_lint

    (tmp_project / "sample.py").write_text(CLEAN, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_lint()

    out = capsys.readouterr().out
    assert "[lint]" in out
    assert "ok" in out


def test_lint_violating_in_process(tmp_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from interlocks.tasks.lint import cmd_lint

    (tmp_project / "sample.py").write_text(VIOLATING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as exc:
        cmd_lint()
    assert exc.value.code != 0


# ─────────────── bundled ruff defaults fallback ─────────────────────


_BARE_PYPROJECT = textwrap.dedent("""
    [project]
    name = "bare"
    version = "0.0.0"
    requires-python = ">=3.11"
""")


def test_lint_injects_bundled_config_when_project_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare project with no [tool.ruff]: task_lint must pass --config <bundled>."""
    from interlocks.tasks.lint import task_lint

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cmd = task_lint().cmd
    assert "--config" in cmd
    cfg_path = Path(cmd[cmd.index("--config") + 1])
    assert cfg_path.name == "ruff.toml"
    assert cfg_path.is_file()


def test_lint_omits_config_when_project_has_tool_ruff(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project with [tool.ruff]: task_lint must NOT pass --config."""
    from interlocks.tasks.lint import task_lint

    monkeypatch.chdir(tmp_project)
    assert "--config" not in task_lint().cmd


def test_lint_omits_config_when_project_has_ruff_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project with ruff.toml sidecar: task_lint must NOT pass --config."""
    from interlocks.tasks.lint import task_lint

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    (tmp_path / "ruff.toml").write_text("line-length = 99\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert "--config" not in task_lint().cmd


# ─────────────── progressive count-mode ─────────────────────


_PROGRESSIVE_PYPROJECT = textwrap.dedent("""
    [project]
    name = "p"
    version = "0"

    [tool.interlocks]
    preset = "progressive"
""")

_THREE_VIOLATIONS = (
    "a.py:1:1: F401 `os` imported but unused\n"
    "b.py:7:1: E501 line too long\n"
    "c.py:3:1: F841 unused variable `z`\n"
)


@dataclass
class _StubProc:
    stdout: str
    stderr: str = ""
    returncode: int = 1


def _stub_capture(stdout: str, returncode: int = 1) -> Callable[[object], _StubProc]:
    return lambda _cmd: _StubProc(stdout=stdout, returncode=returncode)


@pytest.fixture
def progressive_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PROGRESSIVE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    run_summary.reset()
    return tmp_path


def _write_lint_baseline(cap: int) -> None:
    baseline.write_baseline(load_config(), baseline.BaselineFloor(lint_violations_max=cap))
    cfg_mod.clear_cache()


def test_progressive_lint_records_count_and_passes_with_no_cap(
    progressive_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lint_mod, "capture", _stub_capture(_THREE_VIOLATIONS))
    lint_mod.cmd_lint_progressive()
    assert run_summary.current().lint_violations == 3


@pytest.mark.parametrize(("cap", "exit_code"), [(5, None), (2, 1)])
def test_progressive_lint_gates_on_cap(
    progressive_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    cap: int,
    exit_code: int | None,
) -> None:
    _write_lint_baseline(cap)
    monkeypatch.setattr(lint_mod, "capture", _stub_capture(_THREE_VIOLATIONS))
    if exit_code is None:
        lint_mod.cmd_lint_progressive()
        return
    with pytest.raises(SystemExit) as exc:
        lint_mod.cmd_lint_progressive()
    assert exc.value.code == exit_code


def test_progressive_lint_warns_when_ruff_crashes(
    progressive_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lint_mod, "capture", _stub_capture("", returncode=2))
    lint_mod.cmd_lint_progressive()
    assert run_summary.current().lint_violations is None


def test_cmd_lint_dispatches_to_progressive_under_preset(
    progressive_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        lint_mod, "cmd_lint_progressive", lambda files=None: calls.append("progressive")
    )
    monkeypatch.setattr(lint_mod, "run", lambda _t: calls.append("binary"))
    lint_mod.cmd_lint()
    assert calls == ["progressive"]
