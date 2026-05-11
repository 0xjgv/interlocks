"""Integration test for `cmd_complexity` — lizard CCN gate (threshold 15)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

_SIMPLE_SRC = textwrap.dedent(
    """\
    def add(a, b):
        return a + b
    """
)

# 16 nested ifs → CCN 17, above the 15 threshold.
_COMPLEX_SRC = textwrap.dedent(
    """\
    def tangled(n):
        if n == 1: return 1
        if n == 2: return 2
        if n == 3: return 3
        if n == 4: return 4
        if n == 5: return 5
        if n == 6: return 6
        if n == 7: return 7
        if n == 8: return 8
        if n == 9: return 9
        if n == 10: return 10
        if n == 11: return 11
        if n == 12: return 12
        if n == 13: return 13
        if n == 14: return 14
        if n == 15: return 15
        if n == 16: return 16
        return 0
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Project layout lizard scans: `interlocks/` and `tests/`."""
    (tmp_path / "interlocks").mkdir()
    (tmp_path / "interlocks" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_complexity_passes_on_simple_code(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_project / "interlocks" / "mod.py").write_text(_SIMPLE_SRC, encoding="utf-8")
    monkeypatch.chdir(tmp_project)

    from interlocks.tasks.complexity import cmd_complexity

    cmd_complexity()

    out = capsys.readouterr().out
    assert "[complexity]" in out
    assert "ok" in out


def test_complexity_fails_on_tangled_function(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_project / "interlocks" / "mod.py").write_text(_COMPLEX_SRC, encoding="utf-8")
    monkeypatch.chdir(tmp_project)

    from interlocks.tasks.complexity import cmd_complexity

    with pytest.raises(SystemExit) as exc:
        cmd_complexity()
    assert exc.value.code not in (0, None)


# ─────────────── threshold cascade ─────────────────────


def _flag_value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_complexity_uses_default_thresholds_from_config(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default InterlockConfig thresholds (15/7/100) appear in the lizard argv."""
    monkeypatch.chdir(tmp_project)
    from interlocks.tasks.complexity import task_complexity

    cmd = task_complexity().cmd
    assert _flag_value(cmd, "-C") == "15"
    assert _flag_value(cmd, "-a") == "7"
    assert _flag_value(cmd, "-L") == "100"


def test_complexity_honors_tool_interlock_overrides(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`[tool.interlocks]` threshold keys flow into lizard argv."""
    (tmp_project / "pyproject.toml").write_text(
        textwrap.dedent("""\
            [tool.interlocks]
            complexity_max_ccn = 20
            complexity_max_args = 5
            complexity_max_loc = 150
        """),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_project)
    from interlocks.tasks.complexity import task_complexity

    cmd = task_complexity().cmd
    assert _flag_value(cmd, "-C") == "20"
    assert _flag_value(cmd, "-a") == "5"
    assert _flag_value(cmd, "-L") == "150"


# ─────────────── tool pin propagation ───────────────────────────────


def test_complexity_lizard_pin_override_flows_into_cmd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`[tool.interlocks.tools] lizard` override replaces the bundled pin in uvx argv."""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
            [project]
            name = "pin-probe"
            version = "0.0.0"

            [tool.interlocks.tools]
            lizard = "9.99.0"
        """),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    from interlocks.tasks.complexity import task_complexity

    cmd = task_complexity().cmd
    assert "lizard==9.99.0" in cmd
