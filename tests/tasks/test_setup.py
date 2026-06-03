"""Tests for unified `interlocks setup` command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from interlocks.tasks import setup as setup_mod

_PYPROJECT_BODY = '[project]\nname = "probe"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n'


def _git_init(project: Path) -> None:
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=project, check=True, capture_output=True
    )


def _write_pyproject_no_git(project: Path) -> None:
    """Materialize a project pyproject without a ``.git/`` — the non-git refusal input."""
    (project / "pyproject.toml").write_text(_PYPROJECT_BODY, encoding="utf-8")


def _write_pyproject(project: Path) -> None:
    _write_pyproject_no_git(project)
    _git_init(project)


def _run_setup(monkeypatch: pytest.MonkeyPatch, project: Path, *args: str) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.setup import cmd_setup

    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "setup", *args])
    clear_cache()
    try:
        cmd_setup()
    finally:
        clear_cache()


def test_setup_recommends_check_before_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path)

    out = capsys.readouterr().out
    assert out.index("Run `interlocks check` after edits.") < out.index("Run `interlocks doctor`")


def test_setup_check_fails_when_artifacts_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--check")

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "missing/stale" in out
    assert "Run `interlocks setup`" in out


def test_setup_check_reports_git_init_before_setup_in_non_git_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject_no_git(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--check")

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "Run `git init`, then `interlocks setup`" in out
    assert "Run `interlocks setup` to install or refresh" not in out


def test_setup_check_default_mode_prints_fix_and_progressive_next_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)
    monkeypatch.setattr("interlocks.ui.is_verbose", lambda: False)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--check")

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "── Next Steps" not in out
    assert "next: Run `interlocks setup`" in out
    assert "next: Run `interlocks presets set progressive`" in out
    assert 'preset = "progressive"' in out


def test_setup_refuses_non_git_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject_no_git(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path)

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "not a git repository" in out
    assert "git init" in out
    assert not (tmp_path / ".git").exists()


def test_setup_default_mode_prints_per_artifact_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path)

    out = capsys.readouterr().out
    from interlocks.setup_state import SETUP_ARTIFACTS

    for artifact in SETUP_ARTIFACTS:
        assert f"[{artifact.label}]" in out, f"missing summary row for {artifact.label}"
    # A fresh install reports every artifact as installed.
    assert "installed" in out
    assert "missing/stale" not in out


def test_setup_json_installs_local_integrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from interlocks.setup_state import SETUP_ARTIFACTS

    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path, "--json")

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "setup"
    assert payload["mode"] == "local"
    assert payload["check"] is False
    assert payload["passed"] is True
    assert payload["status"] == "installed"
    assert [artifact["label"] for artifact in payload["artifacts"]] == [
        artifact.label for artifact in SETUP_ARTIFACTS
    ]
    assert all(artifact["installed"] is True for artifact in payload["artifacts"])
    assert "Run `interlocks check` after edits." in payload["next_actions"]


def test_setup_check_json_reports_missing_integrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--check", "--json")

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert payload["command"] == "setup"
    assert payload["mode"] == "local"
    assert payload["check"] is True
    assert payload["passed"] is False
    assert payload["status"] == "missing/stale"
    assert any(artifact["installed"] is False for artifact in payload["artifacts"])
    assert payload["next_actions"][0] == (
        "Run `interlocks setup` to install or refresh local integrations."
    )


def test_setup_check_json_reports_git_init_before_setup_in_non_git_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject_no_git(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--check", "--json")

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert payload["next_actions"][0] == (
        "Run `git init`, then `interlocks setup` to install local integrations."
    )


def test_setup_json_refuses_non_git_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject_no_git(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--json")

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert payload["command"] == "setup"
    assert payload["status"] == "error"
    assert "not a git repository" in payload["error"]
    assert payload["next_actions"] == [
        "Run `git init`, then `interlocks setup` to install local integrations."
    ]
    assert not (tmp_path / ".git").exists()


def test_fail_setup_error_json_payload_uses_default_help_action(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(setup_mod.ui, "is_json", lambda: True)

    with pytest.raises(SystemExit) as exc:
        setup_mod._fail_setup_error("unsupported option")

    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "command": "setup",
        "passed": False,
        "status": "error",
        "error": "unsupported option",
        "usage": "usage: interlocks setup [--check] [--ci=github] [--hooks|--agents|--skill]",
        "next_actions": ["Run `interlocks help setup` for supported flags."],
    }


def test_setup_check_prints_full_rows_on_mixed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)
    _run_setup(monkeypatch, tmp_path)  # install all artifacts
    capsys.readouterr()  # drop install output

    # Remove one artifact so the check sees a mixed pass/fail state.
    (tmp_path / ".git" / "hooks" / "pre-commit").unlink()

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--check")

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "installed" in out  # an OK row is now visible
    assert "missing/stale" in out  # the removed artifact's row


def test_setup_check_prints_full_rows_when_all_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)
    _run_setup(monkeypatch, tmp_path)
    capsys.readouterr()

    _run_setup(monkeypatch, tmp_path, "--check")  # exits 0, no SystemExit

    out = capsys.readouterr().out
    from interlocks.setup_state import SETUP_ARTIFACTS

    for artifact in SETUP_ARTIFACTS:
        assert f"[{artifact.label}]" in out
    assert "missing/stale" not in out


def test_setup_installs_hooks_agent_docs_and_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path)

    pre_commit = tmp_path / ".git" / "hooks" / "pre-commit"
    assert pre_commit.is_file()
    assert os.access(pre_commit, os.X_OK)
    assert "-m interlocks.cli hook pre-commit" in pre_commit.read_text(encoding="utf-8")

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]["Stop"][0]["hooks"]
    assert any(
        hook["type"] == "command" and hook["command"].endswith("-m interlocks.cli hook post-edit")
        for hook in hooks
    )

    agents_md = (tmp_path / "AGENTS.md").read_text(encoding="utf-8").lower()
    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8").lower()
    assert "interlocks check" in agents_md
    assert "interlocks check" in claude_md
    assert "unblock" in agents_md
    assert "unblock" in claude_md
    assert "optional acceptance/properties" in agents_md
    assert "coverage/properties/audit/mutation" in agents_md

    from interlocks.defaults_path import path as defaults_path

    installed = tmp_path / ".claude" / "skills" / "interlocks" / "SKILL.md"
    assert installed.read_bytes() == defaults_path("skill/SKILL.md").read_bytes()
    installed_text = installed.read_text(encoding="utf-8")
    assert "unblock" in installed_text
    assert "acceptance and properties run in `check`" in installed_text
    assert "agent.required_actions" in installed_text
    assert "il gate properties --profile=check" in installed_text


def test_setup_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path)
    first_agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    first_claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    _run_setup(monkeypatch, tmp_path)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]["Stop"][0]["hooks"]
    post_edit_hooks = [
        hook for hook in hooks if hook["command"].endswith("-m interlocks.cli hook post-edit")
    ]
    assert len(post_edit_hooks) == 1
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == first_agents
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == first_claude


@pytest.mark.parametrize(
    ("arg", "message"),
    [
        ("--ci=gitlab", "unsupported CI setup target: gitlab"),
        ("--bogus", "usage: interlocks setup"),
    ],
)
def test_setup_rejects_unknown_arguments(
    arg: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_pyproject(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, arg)

    assert exc.value.code == 1
    assert message in capsys.readouterr().out


def test_setup_ci_install_rejects_existing_custom_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_pyproject(tmp_path)
    workflow = tmp_path / ".github" / "workflows" / "interlocks.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: custom\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--ci=github")

    assert exc.value.code == 1
    assert "already exists but does not invoke interlocks" in capsys.readouterr().out


def test_setup_ci_check_reports_missing_when_no_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--ci=github", "--check")

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "github ci" in out
    assert "missing/stale" in out


def test_setup_ci_check_json_reports_missing_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--ci=github", "--check", "--json")

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert payload["mode"] == "github-ci"
    assert payload["check"] is True
    assert payload["passed"] is False
    assert payload["artifacts"][0]["label"] == "github ci"
    assert payload["next_actions"][0] == (
        "Run `interlocks setup --ci=github` to install a GitHub Actions workflow."
    )


def test_setup_ci_check_default_mode_prints_fix_and_progressive_next_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)
    monkeypatch.setattr("interlocks.ui.is_verbose", lambda: False)

    with pytest.raises(SystemExit) as exc:
        _run_setup(monkeypatch, tmp_path, "--ci=github", "--check")

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "── Next Steps" not in out
    assert "next: Run `interlocks setup --ci=github`" in out
    assert "next: Run `interlocks presets set progressive`" in out


def test_setup_ci_installs_github_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path, "--ci=github")

    workflow = tmp_path / ".github" / "workflows" / "interlocks.yml"
    body = workflow.read_text(encoding="utf-8")
    assert "uses: 0xjgv/interlocks@v1" in body
    # fix-optimize is self-sufficient: it subsumes fix-plan / fix-annotate / fix-metrics,
    # so the workflow invokes it alone rather than chaining the three.
    assert "interlocks fix optimize" in body
    assert "--annotate --metrics" in body
    assert "interlocks fix plan" not in body
    assert "interlocks fix annotate" not in body
    assert "interlocks fix metrics" not in body
    assert "Installed GitHub Actions workflow" in capsys.readouterr().out

    first = workflow.read_text(encoding="utf-8")
    _run_setup(monkeypatch, tmp_path, "--ci=github")
    assert workflow.read_text(encoding="utf-8") == first

    capsys.readouterr()
    _run_setup(monkeypatch, tmp_path, "--ci=github", "--check")
    assert "missing/stale" not in capsys.readouterr().out


def test_setup_ci_json_installs_github_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path, "--ci=github", "--json")

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "setup"
    assert payload["mode"] == "github-ci"
    assert payload["check"] is False
    assert payload["passed"] is True
    assert payload["artifacts"] == [
        {
            "label": "github ci",
            "target": ".github/workflows/*.yml",
            "installed": True,
            "status": "installed",
        }
    ]
    assert (tmp_path / ".github" / "workflows" / "interlocks.yml").is_file()


def test_setup_plain_check_does_not_require_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)
    _run_setup(monkeypatch, tmp_path)
    capsys.readouterr()

    _run_setup(monkeypatch, tmp_path, "--check")

    assert "missing/stale" not in capsys.readouterr().out


def test_setup_check_succeeds_after_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)

    _run_setup(monkeypatch, tmp_path)
    capsys.readouterr()

    _run_setup(monkeypatch, tmp_path, "--check")

    out = capsys.readouterr().out
    assert "missing/stale" not in out
    assert "Local integrations are installed and current." in out


def test_setup_check_default_mode_recommends_progressive_after_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path)
    monkeypatch.setattr("interlocks.ui.is_verbose", lambda: False)

    _run_setup(monkeypatch, tmp_path)
    capsys.readouterr()

    _run_setup(monkeypatch, tmp_path, "--check")

    out = capsys.readouterr().out
    assert "missing/stale" not in out
    assert "Local integrations are installed and current." not in out
    assert "next: Run `interlocks presets set progressive`" in out
    assert 'preset = "progressive"' in out


def _write_pyproject_with_preset(project: Path, preset: str | None) -> None:
    body = _PYPROJECT_BODY
    if preset is not None:
        body += f'\n[tool.interlocks]\npreset = "{preset}"\n'
    (project / "pyproject.toml").write_text(body, encoding="utf-8")
    _git_init(project)


def test_setup_check_recommends_progressive_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject_with_preset(tmp_path, None)

    with pytest.raises(SystemExit):
        _run_setup(monkeypatch, tmp_path, "--check")

    assert 'preset = "progressive"' in capsys.readouterr().out


def test_setup_check_recommends_progressive_when_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject_with_preset(tmp_path, "baseline")

    with pytest.raises(SystemExit):
        _run_setup(monkeypatch, tmp_path, "--check")

    assert 'preset = "progressive"' in capsys.readouterr().out


def test_setup_check_no_recommendation_when_progressive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject_with_preset(tmp_path, "progressive")
    _run_setup(monkeypatch, tmp_path)
    capsys.readouterr()

    _run_setup(monkeypatch, tmp_path, "--check")

    out = capsys.readouterr().out
    assert 'preset = "progressive"' not in out


def test_setup_ci_installs_advance_workflow_when_progressive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_pyproject_with_preset(tmp_path, "progressive")

    _run_setup(monkeypatch, tmp_path, "--ci=github")

    advance = tmp_path / ".github" / "workflows" / "interlocks-advance.yml"
    assert advance.is_file()
    body = advance.read_text(encoding="utf-8")
    assert "interlocks baseline advance" in body


def test_setup_ci_skips_advance_workflow_when_not_progressive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_pyproject_with_preset(tmp_path, "baseline")

    _run_setup(monkeypatch, tmp_path, "--ci=github")

    advance = tmp_path / ".github" / "workflows" / "interlocks-advance.yml"
    assert not advance.exists()
