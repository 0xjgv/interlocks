"""Tests for `interlocks doctor` preflight diagnostic."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import interlocks
from interlocks.defaults_path import path as defaults_path
from tests.conftest import stub_project_venv

_MUTMUT_INCOMPATIBLE = pytest.mark.mutmut_incompatible

# When running under an outer interpreter whose site-packages .pth shadows
# this checkout (e.g. a parent-repo pre-commit hook), point the subprocess's
# PYTHONPATH at the in-tree interlocks so `python -m interlocks.cli` sees the
# code under test — not the shadowed install.
_INTERLOCK_PARENT = str(Path(interlocks.__file__).resolve().parent.parent)


def _run_doctor(cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_INTERLOCK_PARENT}{os.pathsep}{existing}" if existing else _INTERLOCK_PARENT
    )
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "doctor"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _run_doctor_json(cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_INTERLOCK_PARENT}{os.pathsep}{existing}" if existing else _INTERLOCK_PARENT
    )
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "doctor", "--json"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _run_doctor_strict(cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_INTERLOCK_PARENT}{os.pathsep}{existing}" if existing else _INTERLOCK_PARENT
    )
    return subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "doctor", "--strict"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@_MUTMUT_INCOMPATIBLE
def test_doctor_tmpdir_flags_missing_pyproject(tmp_path: Path) -> None:
    result = _run_doctor(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    # Minimal-default doctor emits a single status line + bulletized blockers.
    assert result.stdout.startswith("doctor: blocked")
    assert "missing pyproject.toml" in result.stdout


@_MUTMUT_INCOMPATIBLE
def test_doctor_tmpdir_verbose_full_report(tmp_path: Path) -> None:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_INTERLOCK_PARENT}{os.pathsep}{existing}" if existing else _INTERLOCK_PARENT
    )
    result = subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "doctor", "--verbose"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "pyproject.toml" in result.stdout
    assert "(missing)" in result.stdout
    assert "status                 blocked" in result.stdout
    assert "missing pyproject.toml" in result.stdout
    assert "── Readiness" in result.stdout
    assert "── Detected Configuration" in result.stdout
    assert "── Blockers" in result.stdout
    assert "── Warnings" in result.stdout
    assert "── Next Steps" in result.stdout


@_MUTMUT_INCOMPATIBLE
def test_doctor_json_is_parseable(tmp_path: Path) -> None:
    # Missing pyproject → status "blocked", exit 0 (doctor exits 1 only on failures).
    result = _run_doctor_json(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["command"] == "doctor"
    assert payload["status"] == "blocked"
    assert isinstance(payload["blockers"], list)
    assert isinstance(payload["warnings"], list)
    assert payload["next_steps"] == [
        {"message": "Fix blockers in Setup Checklist above, then rerun `interlocks doctor`."}
    ]
    assert {"project_root", "preset", "src_dir", "test_dir"} <= payload["detected"].keys()
    assert isinstance(payload["setup_checklist"], list)
    for entry in payload["setup_checklist"]:
        assert {"name", "target", "detail", "state"} == entry.keys()


def test_doctor_json_well_formed_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A well-formed project yields a ready status with detected config populated."""
    (tmp_path / "probe").mkdir()
    (tmp_path / "probe" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    stub_project_venv(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "doctor", "--json"])

    from interlocks.config import clear_cache
    from interlocks.tasks.doctor import cmd_doctor

    clear_cache()
    try:
        cmd_doctor()
    finally:
        clear_cache()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "doctor"
    assert payload["status"].startswith("ready")
    assert payload["detected"]["pyproject_path"] is not None
    assert payload["detected"]["src_dir"] == "probe"
    assert payload["detected"]["test_dir"] == "tests"


def test_doctor_in_process_reports_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """In-process call gives coverage of the happy path under a tmp project."""
    (tmp_path / "probe").mkdir()
    (tmp_path / "probe" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    stub_project_venv(tmp_path)
    monkeypatch.chdir(tmp_path)

    from interlocks.config import clear_cache
    from interlocks.tasks.doctor import cmd_doctor, task_doctor

    clear_cache()
    try:
        cmd_doctor()
    finally:
        clear_cache()

    captured = capsys.readouterr()
    assert "── Readiness" in captured.out
    assert "── Detected Configuration" in captured.out
    assert "── Setup Checklist" in captured.out
    assert "src_dir" in captured.out
    assert "test_runner" in captured.out
    # Warn-only project is non-blocking; status shows gap count.
    assert "status                 ready" in captured.out
    assert "ready (" in captured.out  # "ready (N gaps)"
    # Derived Next Steps flags the missing preset + CI, not the generic line.
    assert "Run `interlocks presets set progressive`" in captured.out
    assert "Run `interlocks setup --ci=github`" in captured.out
    # The budgeted-mutation note is documentation (`explain check` / `check
    # --help`), not a doctor warning — it no longer appears in the report.
    assert "default check mutation is budgeted by author diff" not in captured.out
    # task_doctor is CLI-only — it never composes into a stage pipeline.
    assert task_doctor() is None


def test_doctor_reports_configured_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "probe").mkdir()
    (tmp_path / "probe" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "\n".join([
            "[project]",
            'name = "probe"',
            'version = "0.0.0"',
            "",
            "[tool.interlocks]",
            'preset = "baseline"',
        ]),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    from interlocks.config import clear_cache
    from interlocks.tasks.doctor import cmd_doctor

    clear_cache()
    try:
        cmd_doctor()
    finally:
        clear_cache()

    out = capsys.readouterr().out
    import re

    def _row(key: str, value: str) -> re.Pattern[str]:
        return re.compile(rf"^\s*{re.escape(key)}\s+{re.escape(value)}\s*$", re.MULTILINE)

    assert _row("preset", "baseline (project-configured)").search(out), out
    assert _row("coverage_min", "70 (preset-derived)").search(out), out
    assert _row("enforce_crap", "False (preset-derived)").search(out), out


def test_doctor_reports_unsupported_preset_as_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "probe").mkdir()
    (tmp_path / "probe" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "\n".join([
            "[project]",
            'name = "probe"',
            'version = "0.0.0"',
            "",
            "[tool.interlocks]",
            'preset = "agent-safe"',
        ]),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    from interlocks.config import clear_cache
    from interlocks.tasks.doctor import cmd_doctor

    clear_cache()
    try:
        cmd_doctor()
    finally:
        clear_cache()

    out = capsys.readouterr().out
    assert "status                 blocked" in out
    assert "unsupported preset: project-configured: agent-safe" in out


def test_doctor_reports_missing_paths_as_blockers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "\n".join([
            "[project]",
            'name = "probe"',
            'version = "0.0.0"',
            "",
            "[tool.interlocks]",
            'src_dir = "src"',
            'test_dir = "tests"',
        ]),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    from interlocks.config import clear_cache
    from interlocks.tasks.doctor import cmd_doctor

    clear_cache()
    try:
        cmd_doctor()
    finally:
        clear_cache()

    out = capsys.readouterr().out
    assert "status                 blocked" in out
    assert "missing source path" in out
    assert "missing test path" in out


def _write_probe_project(tmp_path: Path, *, tool_interlock: str = "") -> None:
    (tmp_path / "probe").mkdir()
    (tmp_path / "probe" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    body = '[project]\nname = "probe"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n'
    if tool_interlock:
        body += "\n[tool.interlocks]\n" + tool_interlock.strip() + "\n"
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")


def _run_cmd_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> str:
    monkeypatch.chdir(tmp_path)
    from interlocks.config import clear_cache
    from interlocks.tasks.doctor import cmd_doctor

    clear_cache()
    try:
        cmd_doctor()
    finally:
        clear_cache()
    return capsys.readouterr().out


def _run_cmd_doctor_default_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> str:
    """Run ``cmd_doctor`` in *default* (non-verbose) mode.

    The autouse ``_isolate_test_env`` fixture forces ``ui.is_verbose`` to return
    True so chrome assertions keep working; default-mode render tests re-patch it
    back to False to exercise the ``else`` branch of ``cmd_doctor``.
    """
    from interlocks import ui as interlock_ui

    monkeypatch.setattr(interlock_ui, "is_verbose", lambda: False)
    return _run_cmd_doctor(tmp_path, monkeypatch, capsys)


def test_doctor_default_mode_names_warn_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Default mode names the warn-row gaps inline, not just the gap count."""
    _write_probe_project(tmp_path)  # no preset, no CI workflow -> warn rows
    stub_project_venv(tmp_path)

    out = _run_cmd_doctor_default_mode(tmp_path, monkeypatch, capsys)
    # Verdict line still present...
    assert out.startswith("doctor: ready (")
    # ...and the warn-row gaps are now named inline (no --verbose needed).
    # The bare probe project's first warn rows are preset + interlocks cfg.
    assert "preset: run `interlocks presets set progressive`" in out
    assert "interlocks cfg: defaults apply" in out


def test_doctor_default_mode_caps_gaps_at_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With more than 3 warn rows, default mode prints 3 bullets + an overflow bullet."""
    _write_probe_project(tmp_path)  # bare probe project: many warn rows, no fails
    stub_project_venv(tmp_path)

    out = _run_cmd_doctor_default_mode(tmp_path, monkeypatch, capsys)
    gap_bullets = [
        line
        for line in out.splitlines()
        if line.startswith("  - ") and "more, run --verbose" not in line
    ]
    # 3 capped gap bullets (the bare probe project has >3 warn rows).
    assert len(gap_bullets) == 3, out
    assert "more, run --verbose for the full list" in out


def test_doctor_json_next_steps_recommend_progressive_and_ci_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path)
    stub_project_venv(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "doctor", "--json"])

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)

    payload = json.loads(out)
    next_steps = [entry["message"] for entry in payload["next_steps"]]
    warnings = [entry["message"] for entry in payload["warnings"]]
    assert "Run `interlocks presets set progressive` to enable ratcheting defaults." in next_steps
    assert any(step.startswith("Run `interlocks setup --ci=github`") for step in next_steps)
    assert "preset: run `interlocks presets set progressive`" in warnings
    assert "ci workflow: run `interlocks setup --ci=github`" in warnings


def test_doctor_default_mode_blockers_uncapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """failures + blockers print uncapped even when there are more than 3."""
    # Missing pyproject + src + test + project env yields >=3 blockers.
    (tmp_path / "pyproject.toml").write_text(
        "\n".join([
            "[project]",
            'name = "probe"',
            'version = "0.0.0"',
            "",
            "[tool.interlocks]",
            'src_dir = "src"',
            'test_dir = "tests"',
        ]),
        encoding="utf-8",
    )
    out = _run_cmd_doctor_default_mode(tmp_path, monkeypatch, capsys)
    assert out.startswith("doctor: blocked")
    assert "missing source path" in out
    assert "missing test path" in out
    assert "no project environment" in out
    # No blocker is hidden behind an overflow line.
    assert "more, run --verbose" not in out.split("\n", 1)[1] or all(
        b in out for b in ("missing source path", "missing test path")
    )


@_MUTMUT_INCOMPATIBLE
def test_doctor_strict_exits_two_when_blocked(tmp_path: Path) -> None:
    """--strict + a blocked verdict (no pyproject) exits code 2."""
    result = _run_doctor_strict(tmp_path)
    assert result.returncode == 2, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert result.stdout.startswith("doctor: blocked")


@_MUTMUT_INCOMPATIBLE
def test_doctor_strict_exits_zero_when_ready(tmp_path: Path) -> None:
    """--strict on a healthy project stays exit 0 — strict only escalates `blocked`."""
    (tmp_path / "probe").mkdir()
    (tmp_path / "probe" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    stub_project_venv(tmp_path)
    result = _run_doctor_strict(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


@_MUTMUT_INCOMPATIBLE
def test_doctor_without_strict_exits_zero_when_blocked(tmp_path: Path) -> None:
    """Plain doctor stays advisory: a blocked verdict still exits 0."""
    result = _run_doctor(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert result.stdout.startswith("doctor: blocked")


def test_doctor_strict_in_process_raises_system_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """In-process: --strict argv + blocked state raises SystemExit(2)."""
    monkeypatch.chdir(tmp_path)  # no pyproject -> blocked
    monkeypatch.setattr(sys, "argv", ["interlocks", "doctor", "--strict"])

    from interlocks.config import clear_cache
    from interlocks.tasks.doctor import cmd_doctor

    clear_cache()
    try:
        with pytest.raises(SystemExit) as excinfo:
            cmd_doctor()
    finally:
        clear_cache()
    assert excinfo.value.code == 2
    _ = capsys.readouterr()  # drain captured output


@_MUTMUT_INCOMPATIBLE
def test_doctor_strict_unreadable_pyproject_still_exits_one(tmp_path: Path) -> None:
    """failures-path precedence: an unreadable pyproject exits 1 even with --strict."""
    # Invalid TOML -> tomllib.TOMLDecodeError -> failures populated -> sys.exit(1) first.
    (tmp_path / "pyproject.toml").write_text("this is not = valid = toml", encoding="utf-8")
    result = _run_doctor_strict(tmp_path)
    assert result.returncode == 1, f"stdout={result.stdout}\nstderr={result.stderr}"


@_MUTMUT_INCOMPATIBLE
def test_doctor_verbose_omits_uvx_path_warnings(tmp_path: Path) -> None:
    """doctor --verbose no longer warns that uvx-dispatched tools are off PATH."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_INTERLOCK_PARENT}{os.pathsep}{existing}" if existing else _INTERLOCK_PARENT
    )
    result = subprocess.run(
        [sys.executable, "-P", "-m", "interlocks.cli", "doctor", "--verbose"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    # The false uvx-tool PATH warnings are gone...
    assert "tool not found on PATH" not in result.stdout
    # ...and the budgeted-mutation note is documentation, not a doctor warning.
    assert "default check mutation is budgeted by author diff" not in result.stdout


def test_doctor_detects_git_pre_commit_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "pre-commit").write_text(
        "#!/bin/sh\nexec python -m interlocks.cli pre-commit\n", encoding="utf-8"
    )

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    assert "── Setup Checklist" in out
    assert "[git hook]" in out
    assert "installed" in out


def test_doctor_flags_missing_hooks_under_existing_git_or_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path)
    stub_project_venv(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".claude").mkdir()

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    assert "Run `interlocks setup`" in out
    assert "[agent docs]" in out
    assert "[claude skill]" in out


def test_doctor_detects_ci_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "name: ci\njobs:\n  test:\n    steps:\n      - run: interlocks ci\n",
        encoding="utf-8",
    )

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    # CI row flips to `ok`; no Next-Steps bullet about wiring CI.
    assert "Run `interlocks setup --ci=github`" not in out


def test_doctor_warns_on_acceptance_configured_without_scaffold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path, tool_interlock='acceptance_runner = "pytest-bdd"')
    stub_project_venv(tmp_path)

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    assert "Run `interlocks init-acceptance`" in out


def test_doctor_warns_on_missing_properties_scaffold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path)
    stub_project_venv(tmp_path)

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    assert "Run `interlocks init-properties`" in out


def test_doctor_detects_property_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path)
    stub_project_venv(tmp_path)
    properties = tmp_path / "properties"
    properties.mkdir()
    (properties / "test_probe_properties.py").write_text(
        "def test_probe():\n    assert True\n", encoding="utf-8"
    )

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    assert "[properties]" in out
    assert "detected" in out
    assert "Run `interlocks init-properties`" not in out


def test_doctor_warns_when_only_property_scaffold_example_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path)
    stub_project_venv(tmp_path)
    properties = tmp_path / "properties"
    properties.mkdir()
    (properties / "test_example_properties.py").write_bytes(
        defaults_path("properties_test_example.py").read_bytes()
    )

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)

    assert "[properties]" in out
    assert "replace scaffold example" in out
    assert "Replace properties/test_example_properties.py with domain invariants" in out
    assert "Run `interlocks init-properties`" not in out


def test_doctor_json_next_steps_distinguish_scaffold_only_properties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path)
    stub_project_venv(tmp_path)
    properties = tmp_path / "properties"
    properties.mkdir()
    (properties / "test_example_properties.py").write_bytes(
        defaults_path("properties_test_example.py").read_bytes()
    )
    monkeypatch.setattr(sys, "argv", ["interlocks", "doctor", "--json"])

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    payload = json.loads(out)
    next_steps = [entry["message"] for entry in payload["next_steps"]]
    warnings = [entry["message"] for entry in payload["warnings"]]

    assert any(
        step.startswith("Replace properties/test_example_properties.py with domain invariants")
        for step in next_steps
    )
    assert "Run `interlocks init-properties` to scaffold property tests." not in next_steps
    assert "properties: replace scaffold example" in warnings


def test_doctor_blocks_when_no_project_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-uv project, no .venv: doctor blocks — typecheck/test would be false negatives."""
    _write_probe_project(tmp_path)  # no stub_project_venv — cold-start state

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    assert "status                 blocked" in out
    assert "no project environment" in out


def test_doctor_ready_state_when_all_artifacts_wired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path, tool_interlock='preset = "baseline"')
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "pre-commit").write_text(
        "#!/bin/sh\nexec python -m interlocks.cli pre-commit\n", encoding="utf-8"
    )
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {"type": "command", "command": "python -m interlocks.cli post-edit"}
                        ]
                    }
                ]
            }
        }),
        encoding="utf-8",
    )
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        "jobs:\n  x:\n    steps:\n      - run: interlocks ci\n", encoding="utf-8"
    )
    venv_bin = tmp_path / (".venv/Scripts" if os.name == "nt" else ".venv/bin")
    venv_bin.mkdir(parents=True)
    (venv_bin / ("python.exe" if os.name == "nt" else "python")).write_text(
        "#!/bin/sh\n", encoding="utf-8"
    )
    features = tmp_path / "tests" / "features"
    features.mkdir(parents=True)
    (features / "probe.feature").write_text("Feature: probe\n", encoding="utf-8")
    properties = tmp_path / "properties"
    properties.mkdir()
    (properties / "test_probe_properties.py").write_text(
        "def test_probe():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "AGENTS.md").write_text("Use interlocks check.\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("Use interlocks check.\n", encoding="utf-8")

    from interlocks.defaults_path import path as defaults_path

    skill = tmp_path / ".claude" / "skills" / "interlocks" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_bytes(defaults_path("skill/SKILL.md").read_bytes())

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    assert "status                 ready" in out
    assert "Run `interlocks check` locally" in out
