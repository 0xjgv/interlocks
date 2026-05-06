"""Tests for `interlocks doctor` preflight diagnostic."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import interlocks

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


def test_doctor_tmpdir_flags_missing_pyproject(tmp_path: Path) -> None:
    result = _run_doctor(tmp_path)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "pyproject.toml" in result.stdout
    assert "(missing)" in result.stdout
    assert "status                 blocked" in result.stdout
    assert "missing pyproject.toml" in result.stdout
    # Section headers show up so the report is grouped, not a blob.
    assert "command=doctor" in result.stdout
    assert "── Readiness" in result.stdout
    assert "── Detected Configuration" in result.stdout
    assert "── Blockers" in result.stdout
    assert "── Warnings" in result.stdout
    assert "── Next Steps" in result.stdout


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
    monkeypatch.chdir(tmp_path)

    from interlocks.config import clear_cache
    from interlocks.tasks.doctor import cmd_doctor, task_doctor

    clear_cache()
    try:
        cmd_doctor()
    finally:
        clear_cache()

    captured = capsys.readouterr()
    assert "command=doctor" in captured.out
    assert "── Readiness" in captured.out
    assert "── Detected Configuration" in captured.out
    assert "── Setup Checklist" in captured.out
    assert "src_dir" in captured.out
    assert "test_runner" in captured.out
    # Warn-only project is non-blocking; status shows gap count.
    assert "status                 ready" in captured.out
    assert "ready (" in captured.out  # "ready (N gaps)"
    # Derived Next Steps flags the missing preset + CI + venv, not the generic line.
    assert "Run `interlocks presets`" in captured.out
    assert "Wire CI via `interlocks ci`" in captured.out
    assert "Create a venv" in captured.out
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
    assert "Wire CI via `interlocks ci`" not in out


def test_doctor_warns_on_acceptance_configured_without_scaffold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_probe_project(tmp_path, tool_interlock='acceptance_runner = "pytest-bdd"')

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    assert "Run `interlocks init-acceptance`" in out


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
    (tmp_path / "AGENTS.md").write_text("Use interlocks check.\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("Use interlocks check.\n", encoding="utf-8")

    from interlocks.defaults_path import path as defaults_path

    skill = tmp_path / ".claude" / "skills" / "interlocks" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_bytes(defaults_path("skill/SKILL.md").read_bytes())

    out = _run_cmd_doctor(tmp_path, monkeypatch, capsys)
    assert "status                 ready" in out
    assert "Run `interlocks check` locally" in out
