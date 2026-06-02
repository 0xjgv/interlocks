"""Integration test for `cmd_coverage` — threshold enforcement via coverage.py."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from tests.conftest import stub_project_venv

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
    stub_project_venv(tmp_path)
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


def test_coverage_json_reports_gate_result_when_threshold_met(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_project / "tests" / "test_mod.py").write_text(_COVERING_TEST_SRC, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage", "--json"])

    from interlocks.tasks.coverage import cmd_coverage

    cmd_coverage(min_pct=80)

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "coverage"
    assert payload["passed"] is True
    assert payload["min_pct"] == 80
    assert payload["include_properties"] is False
    assert payload["property_profile"] is None
    assert payload["gates"][0]["name"] == "coverage"


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


def _coverage_run_cmds(pre_cmds: tuple[list[str], ...]) -> list[list[str]]:
    return [cmd for cmd in pre_cmds if "coverage" in cmd and "run" in cmd]


def _property_coverage_run_cmd(pre_cmds: tuple[list[str], ...]) -> list[str]:
    return next(cmd for cmd in _coverage_run_cmds(pre_cmds) if "--append" in cmd)


def _coverage_json_cmd(pre_cmds: tuple[list[str], ...]) -> list[str]:
    return next(cmd for cmd in pre_cmds if "coverage" in cmd and "json" in cmd)


def test_coverage_injects_bundled_rcfile_in_bare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No [tool.coverage*] and no .coveragerc: run + report must carry --rcfile=<bundled>."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    stub_project_venv(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])
    task = task_coverage()
    assert task is not None
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
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])
    task = task_coverage()
    assert task is not None
    assert _rcfile_flag(task.cmd) is None
    assert _rcfile_flag(_coverage_run_cmd(task.pre_cmds)) is None


def test_coverage_omits_rcfile_with_coveragerc_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.coveragerc in project root: task must NOT inject --rcfile."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    (tmp_path / ".coveragerc").write_text("[run]\nbranch = True\n", encoding="utf-8")
    stub_project_venv(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])
    task = task_coverage()
    assert task is not None
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
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])

    task = task_coverage()

    assert task is not None
    spec = f"coverage=={default_pin('coverage')}"
    run_cmd = _coverage_run_cmd(task.pre_cmds)
    assert task.pre_cmds == (run_cmd,)
    for cmd in (task.cmd, run_cmd):
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
    from interlocks.detect import expected_target_interpreter
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    stub_project_venv(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])

    task = task_coverage()

    assert task is not None
    assert len(task.pre_cmds) == 2
    assert task.pre_cmds[0][:2] == [str(expected_target_interpreter(tmp_path)), "-c"]
    assert "Coverage.py is not importable" in task.pre_cmds[0][2]


def test_coverage_emits_json_under_progressive_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Progressive's baseline ratchet needs coverage.json; other presets skip it."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(
        _BARE_PYPROJECT + '\n[tool.interlocks]\npreset = "progressive"\n', encoding="utf-8"
    )
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])

    task = task_coverage()
    assert task is not None
    json_cmd = _coverage_json_cmd(task.pre_cmds)
    assert "json" in json_cmd
    assert str(tmp_path / ".interlocks" / "coverage.json") in json_cmd


def test_coverage_can_append_property_tests_before_report(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks.coverage import task_coverage

    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_mod_properties.py").write_text(
        textwrap.dedent(
            """\
            from hypothesis import given
            from hypothesis import strategies as st

            from mypkg.mod import double


            @given(st.integers())
            def test_double_is_even_for_even_inputs(value: int) -> None:
                assert double(value * 2) % 2 == 0
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])

    task = task_coverage(min_pct=80, include_properties=True, property_profile="check")

    assert task is not None
    unit_cmd, property_cmd = _coverage_run_cmds(task.pre_cmds)
    assert "--append" not in unit_cmd
    assert "--append" in property_cmd
    assert "properties" in property_cmd
    assert "--hypothesis-profile=check" in property_cmd
    assert any(".interlocks/property_coverage_runner.py" in " ".join(cmd) for cmd in task.pre_cmds)
    assert task.display == "coverage report --fail-under=80 + properties"
    assert task.start_status == "running"
    assert "unit tests under coverage" in task.progress_steps
    assert "property tests under coverage" in task.progress_steps
    assert task.progress_steps[-1] == "coverage report"


def test_coverage_properties_flag_selects_profile(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.runner import Task
    from interlocks.tasks import coverage as coverage_mod

    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_mod_properties.py").write_text(
        "def test_property() -> None:\n    assert True\n", encoding="utf-8"
    )
    captured: list[Task] = []

    def capture_task(task: Task) -> None:
        captured.append(task)

    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage", "--properties=nightly"])
    monkeypatch.setattr(coverage_mod, "run", capture_task)

    coverage_mod.cmd_coverage()

    task = captured[0]
    property_cmd = _property_coverage_run_cmd(task.pre_cmds)
    assert "--hypothesis-profile=nightly" in property_cmd


def test_coverage_properties_flag_rejects_unknown_profile(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks.coverage import cmd_coverage

    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage", "--properties=slow"])

    with pytest.raises(SystemExit):
        cmd_coverage()


def test_coverage_properties_flag_rejects_unknown_profile_json_before_env_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks.coverage import cmd_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "gate", "coverage", "--properties=slow", "--json"],
    )

    with pytest.raises(SystemExit) as exc:
        cmd_coverage()

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "command": "coverage",
        "passed": False,
        "error": "unsupported property profile 'slow'",
        "expected_property_profiles": ["check", "ci", "nightly", "default"],
    }


def test_coverage_default_min_pct_uses_cfg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``task_coverage()`` without args picks up ``cfg.coverage_min`` (default 80)."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    stub_project_venv(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])
    task = task_coverage()
    assert task is not None
    assert "--fail-under=80" in task.cmd


def test_coverage_config_override_wires_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[tool.interlocks] coverage_min = 95`` flows into --fail-under=95."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(
        _BARE_PYPROJECT + "\n[tool.interlocks]\ncoverage_min = 95\n", encoding="utf-8"
    )
    stub_project_venv(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])
    task = task_coverage()
    assert task is not None
    assert "--fail-under=95" in task.cmd


# ─────────────── project-env guard ─────────────────────


def test_task_coverage_returns_none_without_project_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-uv project, no .venv: task_coverage declines with a warn_skip."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])

    assert task_coverage() is None
    assert "no project environment" in capsys.readouterr().out


def test_cmd_coverage_skips_without_project_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """cmd_coverage returns cleanly (no SystemExit) when the env is absent."""
    from interlocks.tasks.coverage import cmd_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])

    cmd_coverage()  # must not raise SystemExit
    assert "coverage: skipped — no project environment" in capsys.readouterr().out


def test_cmd_coverage_json_reports_missing_project_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks.coverage import cmd_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage", "--json"])

    cmd_coverage()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "coverage"
    assert payload["status"] == "skipped"
    assert payload["min_pct"] == 80
    assert payload["include_properties"] is False
    assert payload["property_profile"] is None
    assert "no project environment" in payload["reason"]


def test_coverage_skip_payload_without_properties_is_exact() -> None:
    from interlocks.tasks.coverage import _coverage_skip_payload

    assert _coverage_skip_payload(
        min_pct=90,
        include_properties=False,
        property_profile="ci",
        reason="no project environment",
        next_action="Create the project environment.",
    ) == {
        "command": "coverage",
        "passed": True,
        "status": "skipped",
        "min_pct": 90,
        "include_properties": False,
        "property_profile": None,
        "reason": "no project environment",
        "next_actions": ["Create the project environment."],
    }


def test_coverage_skip_payload_with_properties_is_exact() -> None:
    from interlocks.tasks.coverage import _coverage_skip_payload

    assert _coverage_skip_payload(
        min_pct=75,
        include_properties=True,
        property_profile="nightly",
        reason="missing environment",
        next_action="Sync dependencies.",
    ) == {
        "command": "coverage",
        "passed": True,
        "status": "skipped",
        "min_pct": 75,
        "include_properties": True,
        "property_profile": "nightly",
        "reason": "missing environment",
        "next_actions": ["Sync dependencies."],
    }


def test_cmd_coverage_can_suppress_json_for_internal_callers(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.runner import Task
    from interlocks.tasks import coverage as coverage_mod

    captured: list[Task] = []
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "trust", "--json"])
    monkeypatch.setattr(coverage_mod, "run", captured.append)

    coverage_mod.cmd_coverage(min_pct=80, emit_json=False)

    assert captured
    assert capsys.readouterr().out == ""


def test_task_coverage_runs_for_uv_project_without_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uv projects short-circuit project_env_ready — the guard never fires."""
    from interlocks.tasks.coverage import task_coverage

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage"])

    assert task_coverage() is not None
