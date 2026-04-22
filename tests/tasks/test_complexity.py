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
    """Project layout lizard scans: `harness/` and `tests/`."""
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_complexity_passes_on_simple_code(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_project / "harness" / "mod.py").write_text(_SIMPLE_SRC, encoding="utf-8")
    monkeypatch.chdir(tmp_project)

    from harness.tasks.complexity import cmd_complexity

    cmd_complexity()  # no SystemExit → lizard happy


def test_complexity_fails_on_tangled_function(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_project / "harness" / "mod.py").write_text(_COMPLEX_SRC, encoding="utf-8")
    monkeypatch.chdir(tmp_project)

    from harness.tasks.complexity import cmd_complexity

    with pytest.raises(SystemExit) as exc:
        cmd_complexity()
    assert exc.value.code not in (0, None)
