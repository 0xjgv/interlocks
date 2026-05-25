"""Integration tests for interlocks.tasks.format_check.

The CLI exposes ``format-check`` as the read-only counterpart to ``format``;
the unit layer still invokes ``cmd_format_check`` directly for focused exit-code
coverage.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PYPROJECT = textwrap.dedent("""
    [project]
    name = "sample"
    version = "0.0.0"
    requires-python = ">=3.11"

    [tool.ruff]
    target-version = "py311"
    line-length = 99
""")

CLEAN = 'x = "hello"\n'
UNFORMATTED = "x   =   'hello'\n"


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return tmp_path


def test_format_check_clean_exits_zero(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks.format_check import cmd_format_check

    src = tmp_project / "sample.py"
    src.write_text(CLEAN, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_format_check()

    assert src.read_text(encoding="utf-8") == CLEAN
    out = capsys.readouterr().out
    assert "[format]" in out
    assert "ok" in out


def test_format_check_json_clean_exits_zero(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.format_check import cmd_format_check

    src = tmp_project / "sample.py"
    src.write_text(CLEAN, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "format-check", "--json"])
    clear_cache()

    cmd_format_check()

    assert src.read_text(encoding="utf-8") == CLEAN
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["command"] == "format-check"
    assert payload["passed"] is True
    assert payload["gates"][0]["name"] == "format"
    assert captured.err.startswith("interlocks: [format]")


def test_format_check_unformatted_exits_nonzero(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks.format_check import cmd_format_check

    (tmp_project / "sample.py").write_text(UNFORMATTED, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as excinfo:
        cmd_format_check()
    assert excinfo.value.code != 0


def test_format_check_json_unformatted_exits_nonzero(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.format_check import cmd_format_check

    (tmp_project / "sample.py").write_text(UNFORMATTED, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "format-check", "--json"])
    clear_cache()

    with pytest.raises(SystemExit) as excinfo:
        cmd_format_check()

    payload = json.loads(capsys.readouterr().out)
    assert excinfo.value.code == 1
    assert payload["command"] == "format-check"
    assert payload["passed"] is False
    assert payload["gates"][0]["status"] == "fail"


def test_format_check_injects_bundled_config_in_bare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks.format_check import task_format_check

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='bare'\nversion='0.0.0'\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    cmd = task_format_check().cmd
    assert "--config" in cmd
    assert Path(cmd[cmd.index("--config") + 1]).name == "ruff.toml"


def test_format_check_cli_entrypoint_is_registered(tmp_project: Path) -> None:
    (tmp_project / "sample.py").write_text(CLEAN, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "format-check"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "[format]" in result.stdout
    assert "ok" in result.stdout
