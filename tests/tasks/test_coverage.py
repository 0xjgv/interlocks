"""Integration test for `cmd_coverage` — threshold enforcement via coverage.py."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

_MODULE_SRC = textwrap.dedent(
    """\
    def double(x):
        return x * 2
    """
)

_COVERING_TEST_SRC = textwrap.dedent(
    """\
    import unittest
    from mypkg.mod import double

    class TestDouble(unittest.TestCase):
        def test_double(self):
            self.assertEqual(double(3), 6)
    """
)

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "cov-probe"
    version = "0.0.1"
    requires-python = ">=3.11"

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.coverage.report]
    show_missing = true
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Project with `mypkg/mod.py` and an empty `tests/` dir."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_coverage_passes_when_threshold_met(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_project / "tests" / "test_mod.py").write_text(_COVERING_TEST_SRC, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))

    from interlocks.tasks.coverage import cmd_coverage

    cmd_coverage(min_pct=80)

    out = capsys.readouterr().out
    assert "[coverage]" in out
    assert (tmp_project / ".coverage").is_file()


def test_coverage_fails_below_threshold(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # no tests → 0% on the module
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))

    from interlocks.tasks.coverage import cmd_coverage

    with pytest.raises(SystemExit) as exc:
        cmd_coverage(min_pct=80)
    assert exc.value.code not in (0, None)


# ─────────────── bundled coveragerc fallback ─────────────────────

_BARE_PYPROJECT = textwrap.dedent("""\
    [project]
    name = "bare"
    version = "0.0.0"
    requires-python = ">=3.11"
""")


def _rcfile_flag(cmd: list[str]) -> str | None:
    return next((a for a in cmd if a.startswith("--rcfile=")), None)


def _coverage_run_cmd(pre_cmds: tuple[list[str], ...]) -> list[str]:
    return next(cmd for cmd in pre_cmds if "coverage" in cmd and "run" in cmd)


def test_coverage_injects_bundled_rcfile_in_bare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No [tool.coverage*] and no .coveragerc: run + report must carry --rcfile=<bundled>."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "coverage"])
    task = task_coverage()
    for cmd in (task.cmd, _coverage_run_cmd(task.pre_cmds)):
        flag = _rcfile_flag(cmd)
        assert flag is not None
        assert Path(flag.split("=", 1)[1]).name == "coveragerc"


def test_coverage_omits_rcfile_when_project_has_tool_coverage(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[tool.coverage.run] in project pyproject: task must NOT inject --rcfile."""
    from interlocks.tasks.coverage import task_coverage

    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "coverage"])
    task = task_coverage()
    assert _rcfile_flag(task.cmd) is None
    assert _rcfile_flag(_coverage_run_cmd(task.pre_cmds)) is None


def test_coverage_omits_rcfile_with_coveragerc_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.coveragerc in project root: task must NOT inject --rcfile."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    (tmp_path / ".coveragerc").write_text("[run]\nbranch = True\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "coverage"])
    task = task_coverage()
    assert _rcfile_flag(task.cmd) is None
    assert _rcfile_flag(_coverage_run_cmd(task.pre_cmds)) is None


def test_coverage_uv_injects_coverage_without_project_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uv projects get Coverage.py via `--with`, not from a project console script."""
    from interlocks.defaults.tools import default_pin
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "coverage"])

    task = task_coverage()

    spec = f"coverage=={default_pin('coverage')}"
    assert task.pre_cmds == (_coverage_run_cmd(task.pre_cmds),)
    for cmd in (task.cmd, task.pre_cmds[0]):
        assert cmd[:8] == [
            "uv",
            "run",
            "--with",
            spec,
            "--index-strategy",
            "first-index",
            "python",
            "-m",
        ]
        assert "uv run coverage" not in " ".join(cmd)


def test_coverage_non_uv_preflights_target_coverage_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "coverage"])

    task = task_coverage()

    assert len(task.pre_cmds) == 2
    assert task.pre_cmds[0][:2] == [sys.executable, "-c"]
    assert "Coverage.py is not importable" in task.pre_cmds[0][2]


def test_coverage_default_min_pct_uses_cfg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``task_coverage()`` without args picks up ``cfg.coverage_min`` (default 80)."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "coverage"])
    assert "--fail-under=80" in task_coverage().cmd


def test_coverage_config_override_wires_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[tool.interlocks] coverage_min = 95`` flows into --fail-under=95."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(
        _BARE_PYPROJECT + "\n[tool.interlocks]\ncoverage_min = 95\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "coverage"])
    assert "--fail-under=95" in task_coverage().cmd
