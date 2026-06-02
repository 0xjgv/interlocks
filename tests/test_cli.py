"""Unit tests for interlocks.cli dispatcher."""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import re
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from interlocks.cli import (
    TASK_GROUPS,
    TASK_HANDLERS,
    TASKS,
    _available_preset_payload,
    _current_preset_payload,
    _fail_presets_error,
    _fail_quiet_removed,
    _fail_unknown_command,
    _preset_current_values_payload,
    _presets_error_payload,
    _task_help_payload,
    cmd_help,
    cmd_help_from_argv,
    cmd_presets,
    cmd_task_help,
    main,
)
from interlocks.command_docs import (
    COMMAND_DOCS,
    COMMAND_DOCS_BY_NAME,
    COMMAND_GROUPS,
    CommandDoc,
    FlagSpec,
    _flag_sets_for_task,
    command_doc_payload,
)
from interlocks.config import (
    CONFIG_KEY_GROUP_ORDER,
    CONFIG_KEYS,
    InterlockConfig,
    clear_cache,
    load_config,
    preset_defaults,
    preset_description,
)
from interlocks.tasks.config import _json_value, cmd_config
from interlocks.tasks.explain import cmd_explain

_DEFAULT_HELP_GROUPS = (
    ("Start here", ("doctor", "setup", "check", "ci", "nightly")),
    ("Direct access", ("gate", "fix")),
    ("Project", ("init", "config", "presets", "explain", "clean", "version")),
)


@pytest.fixture
def clean_config_cache() -> Iterator[None]:
    clear_cache()
    try:
        yield
    finally:
        clear_cache()


def _setup_minimal_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "pkg"\nversion = "0.0.0"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return pyproject


def _setup_project_with_interlocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    """Minimal project + ``[tool.interlocks]`` table populated from ``body`` lines."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pkg"\nversion = "0.0.0"\n\n[tool.interlocks]\n' + body + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)


def test_tasks_dict_built_from_groups() -> None:
    expected = {name for _, group in TASK_GROUPS for name in group}
    assert set(TASKS.keys()) == expected
    assert set(TASK_HANDLERS) == set(COMMAND_DOCS_BY_NAME)
    # Each entry is (callable, description).
    for fn, desc in TASKS.values():
        assert callable(fn)
        assert isinstance(desc, str) and desc


def test_cmd_help_prints_usage_and_groups(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_help()
    out = capsys.readouterr().out
    # Help drops the chrome banner; minimal-default emits just usage + groups.
    assert "command=help" not in out
    assert not re.search(r"interlocks v\d", out)
    assert "Usage: interlocks <command>" in out
    assert "── Usage" in out
    assert "── More" in out
    assert "help --advanced" in out
    for group_name, names in _DEFAULT_HELP_GROUPS:
        # Group labels route through the always-print `group_header`, not the
        # verbose-gated `section` — so they render at default verbosity.
        assert f"{group_name}:" in out
        for name in names:
            assert f"[{name}]" in out
    assert "[evaluate]" not in out


def test_cmd_help_advanced_prints_all_groups(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_help(advanced=True)
    out = capsys.readouterr().out
    assert "── Commands" in out
    assert "Full verification: lint, audit, typecheck, tests, coverage, properties, CRAP" in out
    assert "Long-running gates: coverage + properties + audit + mutation" in out
    for group_name, group in TASK_GROUPS:
        assert f"{group_name}:" in out
        for name in group:
            assert f"[{name}]" in out


def test_cmd_help_json_prints_default_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_project_with_interlocks(
        tmp_path,
        monkeypatch,
        'preset = "strict"\ntest_runner = "pytest"',
    )
    monkeypatch.setattr(sys, "argv", ["interlocks", "help", "--json"])

    cmd_help()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "help"
    assert payload["advanced"] is False
    assert payload["detected"] == {
        "pyproject": True,
        "preset": "strict",
        "src": "pkg",
        "tests": "tests",
        "runner": "pytest",
    }
    groups = {group["name"]: group["commands"] for group in payload["groups"]}
    assert "Start here" in groups
    assert any(command["name"] == "check" for command in groups["Start here"])
    assert not any(command["name"] == "evaluate" for command in groups["Start here"])


def test_cmd_help_json_advanced_prints_full_catalog(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "help", "--advanced", "--json"])

    cmd_help(advanced=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["advanced"] is True
    commands = [command["name"] for group in payload["groups"] for command in group["commands"]]
    assert set(commands) == set(TASKS)


def test_cmd_task_help_uses_command_usage_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_task_help("baseline")
    out = capsys.readouterr().out
    assert "Usage: interlocks baseline [show|init|advance|check] [--json] [--auto-pr]" in out

    cmd_task_help("config")
    out = capsys.readouterr().out
    assert "Usage: interlocks config [show <tool> [--bundled-only] [--json]]" in out


def test_cmd_help_command_json_reuses_task_help_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "help", "check", "--json"])

    cmd_help_from_argv()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "check"
    assert payload["usage"] == "usage: interlocks check"
    assert any(flag["name"] == "--json" for flag in payload["flags"])


def test_task_help_payload_falls_back_for_private_task_names() -> None:
    assert _task_help_payload("custom-task") == {
        "command": "custom-task",
        "usage": "usage: interlocks custom-task",
        "flags": [],
    }


def test_cmd_help_prints_active_preset_and_resolved_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_project_with_interlocks(tmp_path, monkeypatch, 'preset = "strict"\ncoverage_min = 91')

    cmd_help()

    out = capsys.readouterr().out

    def _row(key: str, value: str) -> re.Pattern[str]:
        return re.compile(rf"^\s*{re.escape(key)}\s+{re.escape(value)}\s*$", re.MULTILINE)

    assert _row("preset", "strict").search(out), out
    assert _row("coverage_min", "91").search(out), out
    assert _row("run_mutation_in_ci", "True").search(out), out


def test_cmd_help_prints_detected_summary_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    """Default-mode help emits a one-line `Detected:` summary with the key fields."""
    _setup_project_with_interlocks(tmp_path, monkeypatch, 'preset = "strict"')

    cmd_help()

    out = capsys.readouterr().out
    detected = next((line for line in out.splitlines() if line.startswith("Detected:")), None)
    assert detected is not None, out
    assert "preset=strict" in detected
    assert "src=" in detected
    assert "tests=" in detected
    assert "runner=" in detected
    assert "(no pyproject.toml)" not in detected


def test_cmd_help_detected_summary_no_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    """With no pyproject.toml, the Detected line degrades to a clear placeholder."""
    monkeypatch.chdir(tmp_path)

    cmd_help()

    out = capsys.readouterr().out
    assert "Detected: (no pyproject.toml)" in out


def test_cmd_presets_prints_options_and_copyable_config(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd_presets()
    out = capsys.readouterr().out
    # Presets drops the chrome banner.
    assert not re.search(r"interlocks v\d", out)
    assert "command=presets" not in out
    assert "── Current" in out
    assert "── Current Values" in out
    assert "coverage_min" in out
    assert "mutation_ci_mode" in out
    assert "── Available Presets" in out
    assert "baseline" in out
    assert "strict" in out
    assert "legacy" in out
    assert "progressive" in out
    assert "── Next Steps" in out
    assert "Set a project preset with the CLI:" in out
    assert "interlocks presets set progressive" in out
    assert "Or add this to pyproject.toml:" in out
    assert '[tool.interlocks]\n    preset = "progressive"' in out
    assert "manually override any threshold" in out
    assert "pyproject.toml" in out

    # Default mode keeps the one-line footer; the "Next Steps" block is verbose-only.
    monkeypatch.setattr("interlocks.ui.is_verbose", lambda: False)
    cmd_presets()
    default_out = capsys.readouterr().out
    assert "Switch with: interlocks presets set" in default_out
    assert "── Next Steps" not in default_out


def test_cmd_presets_prints_active_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_project_with_interlocks(tmp_path, monkeypatch, 'preset = "strict"')

    cmd_presets()

    out = capsys.readouterr().out
    assert re.search(r"^\s*preset\s+strict\s*$", out, re.MULTILINE), out
    assert re.search(r"^\s*coverage_min\s+90 \(preset-derived\)\s*$", out, re.MULTILINE), out
    assert re.search(r"^\s*run_mutation_in_ci\s+True \(preset-derived\)\s*$", out, re.MULTILINE), (
        out
    )


def test_cmd_presets_json_lists_current_and_available_presets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_project_with_interlocks(tmp_path, monkeypatch, 'preset = "strict"')
    monkeypatch.setattr(sys, "argv", ["interlocks", "presets", "--json"])

    cmd_presets()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "presets"
    assert payload["current"]["preset"] == "strict"
    assert payload["current"]["pyproject"] is True
    assert payload["switch_command"] == (
        "interlocks presets set <baseline|strict|legacy|progressive>"
    )
    values = {entry["key"]: entry for entry in payload["current_values"]}
    assert values["coverage_min"]["value"] == 90
    assert values["coverage_min"]["source"] == "preset-derived"
    presets = {entry["name"]: entry for entry in payload["available_presets"]}
    assert set(presets) == {"baseline", "strict", "legacy", "progressive"}
    assert presets["progressive"]["defaults"]["run_properties_in_check"] is True


def test_preset_payload_helpers_have_exact_json_contract(tmp_path: Path) -> None:
    cfg = InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "src",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
        preset="strict",
    )

    assert _current_preset_payload(None) == {"pyproject": False, "preset": None}
    assert _current_preset_payload(cfg) == {"pyproject": False, "preset": None}
    assert _preset_current_values_payload(cfg) == []

    (tmp_path / "pyproject.toml").write_text("[project]\nname='pkg'\n", encoding="utf-8")

    assert _current_preset_payload(cfg) == {
        "pyproject": True,
        "preset": "strict",
        "pyproject_path": "pyproject.toml",
    }
    current_values = _preset_current_values_payload(cfg)
    coverage = next(entry for entry in current_values if entry["key"] == "coverage_min")
    assert coverage == {"key": "coverage_min", "value": 80, "source": "unknown"}
    assert _available_preset_payload("progressive") == {
        "name": "progressive",
        "description": preset_description("progressive"),
        "defaults": preset_defaults("progressive"),
    }


def test_current_preset_payload_requires_lowercase_pyproject_name() -> None:
    class CaseSensitivePath:
        def __init__(self, name: str) -> None:
            self.name = name

        def is_file(self) -> bool:
            return self.name == "pyproject.toml"

    class CaseSensitiveRoot:
        def __truediv__(self, name: str) -> CaseSensitivePath:
            return CaseSensitivePath(name)

    class CaseSensitiveConfig:
        project_root = CaseSensitiveRoot()
        preset = "strict"

        def relpath(self, path: CaseSensitivePath) -> str:
            return path.name

    assert _current_preset_payload(CaseSensitiveConfig()) == {  # pyright: ignore[reportArgumentType]
        "pyproject": True,
        "preset": "strict",
        "pyproject_path": "pyproject.toml",
    }


def test_presets_error_payload_and_human_branch_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _presets_error_payload("unsupported preset: agent-safe", "expected baseline|strict")

    assert payload == {
        "command": "presets",
        "error": "unsupported preset: agent-safe",
        "detail": "expected baseline|strict",
        "usage": "usage: interlocks presets [<baseline|strict|legacy|progressive>] or "
        "interlocks presets set <baseline|strict|legacy|progressive>",
        "expected_presets": ["baseline", "strict", "legacy", "progressive"],
    }

    calls: list[str | None] = []

    def fake_fail_skip(message: str | None) -> None:
        calls.append(message)
        raise SystemExit(1)

    monkeypatch.setattr(sys, "argv", ["interlocks", "presets", "agent-safe"])
    monkeypatch.setattr("interlocks.cli.fail_skip", fake_fail_skip)

    with pytest.raises(SystemExit) as exc:
        _fail_presets_error("unsupported preset: agent-safe", "expected baseline|strict")

    assert exc.value.code == 1
    assert calls == ["unsupported preset: agent-safe (expected baseline|strict)"]


@pytest.mark.parametrize(
    "argv",
    (
        ["interlocks", "presets", "set", "baseline"],
        ["interlocks", "presets", "baseline"],
    ),
)
def test_cmd_presets_writes_interlock_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
    argv: list[str],
) -> None:
    pyproject = _setup_minimal_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", argv)

    cmd_presets()

    assert '[tool.interlocks]\npreset = "baseline"\n' in pyproject.read_text(encoding="utf-8")
    assert "set [tool.interlocks] preset = 'baseline'" in capsys.readouterr().out


def test_cmd_presets_set_json_writes_and_reports_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    pyproject = _setup_minimal_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["interlocks", "presets", "set", "progressive", "--json"])

    cmd_presets()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "command": "presets",
        "action": "set",
        "preset": "progressive",
        "pyproject_path": "pyproject.toml",
    }
    assert 'preset = "progressive"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "argv",
    (
        ["interlocks", "presets", "set", "strict"],
        ["interlocks", "presets", "strict"],
    ),
)
def test_cmd_presets_replaces_existing_preset_without_thresholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_config_cache: None, argv: list[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "pkg"
            version = "0.0.0"

            [tool.interlocks]
            preset = "baseline"
            coverage_min = 91

            [tool.pytest.ini_options]
            addopts = "-q"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    cmd_presets()

    text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'preset = "strict"' in text
    assert 'preset = "baseline"' not in text
    assert "coverage_min = 91" in text
    assert "[tool.pytest.ini_options]" in text


@pytest.mark.parametrize(
    "argv",
    (
        ["interlocks", "presets", "set", "baseline"],
        ["interlocks", "presets", "baseline"],
    ),
)
def test_cmd_presets_clears_config_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_config_cache: None, argv: list[str]
) -> None:
    _setup_minimal_project(tmp_path, monkeypatch)

    assert load_config().preset is None

    monkeypatch.setattr(sys, "argv", argv)
    cmd_presets()
    cfg = load_config()
    defaults = preset_defaults("baseline")

    assert cfg.preset == "baseline"
    assert cfg.coverage_min == defaults["coverage_min"]
    assert cfg.crap_max == defaults["crap_max"]
    assert cfg.enforce_crap == defaults["enforce_crap"]
    assert cfg.value_sources["coverage_min"] == "preset-derived"


@pytest.mark.parametrize(
    "argv",
    (
        ["interlocks", "presets", "set", "agent-safe"],
        ["interlocks", "presets", "agent-safe"],
    ),
)
def test_cmd_presets_rejects_unknown_preset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
    argv: list[str],
) -> None:
    _setup_minimal_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        cmd_presets()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "unsupported preset: agent-safe" in out
    assert "expected baseline|strict|legacy|progressive" in out


def test_cmd_presets_rejects_unknown_preset_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_minimal_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["interlocks", "presets", "agent-safe", "--json"])

    with pytest.raises(SystemExit) as exc:
        cmd_presets()

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "presets"
    assert payload["error"] == "unsupported preset: agent-safe"
    assert payload["detail"] == "expected baseline|strict|legacy|progressive"
    assert payload["expected_presets"] == ["baseline", "strict", "legacy", "progressive"]


def test_cmd_presets_shorthand_rejects_extra_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_minimal_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["interlocks", "presets", "baseline", "extra"])

    with pytest.raises(SystemExit) as exc:
        cmd_presets()

    assert exc.value.code == 1
    assert "usage: interlocks presets" in capsys.readouterr().out


def test_main_no_args_prints_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks"])
    main()
    out = capsys.readouterr().out
    assert "Usage: interlocks <command>" in out


def test_main_no_command_json_error_is_parseable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "--json"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "interlocks"
    assert payload["error"] == "missing command"
    assert payload["usage"] == "usage: interlocks <command>"
    assert "check" in payload["known_commands"]


def test_main_unknown_command_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "nope"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == "Unknown command: nope\n"
    assert "Usage: interlocks <command>" in captured.out


def test_main_unknown_command_json_error_is_parseable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "nope", "--json"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "nope"
    assert payload["error"] == "unknown command nope"
    assert payload["usage"] == "usage: interlocks <command>"
    assert "check" in payload["known_commands"]


def test_main_dispatches_known_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "help"])
    main()  # cmd_help() is safe to run
    assert "Usage: interlocks <command>" in capsys.readouterr().out


def test_main_command_help_does_not_dispatch_task(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def fake() -> None:
        calls.append("ran")

    monkeypatch.setitem(TASKS, "gate coverage", (fake, "Tests with coverage threshold (--min=N)"))
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage", "--help"])

    main()

    assert calls == []
    out = capsys.readouterr().out
    assert "Usage: interlocks gate coverage" in out
    assert "[gate coverage]" in out


def test_main_command_help_lists_flags(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`<task> --help` renders a Flags section for a flag-bearing task."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage", "--help"])
    main()
    out = capsys.readouterr().out
    assert "Usage: interlocks gate coverage" in out
    assert "[gate coverage]" in out
    assert "--min" in out
    assert "--properties" in out
    assert "coverage fail-under percentage" in out


def test_main_command_help_json_is_parseable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "check", "--help", "--json"])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "check"
    assert payload["usage"] == "usage: interlocks check"
    assert payload["summary"].startswith("Local edit loop")
    assert "--json" in {flag["name"] for flag in payload["flags"]}
    assert any(code["code"] == 0 for code in payload["exit_codes"])


def test_ci_help_mentions_skip_mutation_escape_hatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "help", "ci"])

    main()

    out = capsys.readouterr().out
    assert "--skip=" in out
    assert "mutation" in out


def test_main_help_command_name_lists_task_flags(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`help <task>` is equivalent to `<task> --help` for discoverability."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "help", "property-candidates"])

    main()

    out = capsys.readouterr().out
    assert "Usage: interlocks property-candidates" in out
    assert "--changed=REF" in out
    assert "--changed      optional" in out
    assert "optionalscope" not in out
    assert "--uncovered" in out
    assert "--limit=" in out


def test_check_help_changed_flag_mentions_property_skip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "help", "check"])

    main()

    out = capsys.readouterr().out
    assert "optional acceptance/properties" in out
    assert "--changed" in out
    assert "optional" in out
    assert "optionalscope" not in out
    assert "skips test, acceptance, properties" in out


def test_properties_help_lists_all_supported_profiles(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "help", "gate", "properties"])

    main()

    out = capsys.readouterr().out
    assert "Hypothesis profile: check, ci, nightly, default" in out


def test_main_command_help_lists_json_flag_for_fix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "fix", "--help"])
    main()
    out = capsys.readouterr().out
    assert "Usage: interlocks fix" in out
    assert "Flags" in out
    assert "--json" in out


def test_main_rejects_unknown_skip_label(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "check", "--skip=nope"])

    with pytest.raises(SystemExit) as exc:
        main()

    # Bad `--skip` usage is a usage error → exit 1; exit 2 is missing-pyproject.
    assert exc.value.code == 1
    assert "unknown skip label" in capsys.readouterr().err


def test_main_rejects_unknown_skip_label_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "check", "--json", "--skip=nope"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "check"
    assert "unknown skip label" in payload["error"]
    assert "known_labels" in payload


def test_main_dispatches_alias_to_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake() -> None:
        calls.append("ran")

    monkeypatch.setitem(TASKS, "fix optimize", (fake, "Optimize"))
    monkeypatch.setattr("interlocks.cli.preflight", lambda name: calls.append(f"preflight:{name}"))
    monkeypatch.setattr(sys, "argv", ["interlocks", "fix", "unblock"])

    main()

    assert calls == ["preflight:fix optimize", "ran"]


def test_cmd_help_lists_fix_unblock_alias(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cmd_help(advanced=True)

    out = capsys.readouterr().out
    assert "[fix optimize]" in out
    assert "alias: fix unblock" in out


def test_main_skips_flag_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flags (starting with -) are filtered out before dispatch."""
    calls: list[str] = []

    def fake() -> None:
        calls.append("ran")

    monkeypatch.setitem(TASKS, "help", (fake, "Show help"))
    monkeypatch.setattr(sys, "argv", ["interlocks", "--verbose", "help"])
    main()
    assert calls == ["ran"]


def test_main_unknown_flag_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An undeclared task flag is rejected with exit 1 and named on stderr."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage", "--xyzzy"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "interlocks gate coverage: unknown flag --xyzzy" in capsys.readouterr().err


def test_main_unknown_flag_json_error_is_parseable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "check", "--json", "--xyzzy"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "check"
    assert payload["error"] == "unknown flag --xyzzy"
    assert payload["flag"] == "--xyzzy"
    assert "usage: interlocks check" in payload["usage"]
    assert "--json" in payload["known_flags"]


def test_main_rejects_help_only_advanced_flag_elsewhere(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--advanced is a help flag, not a silently ignored global flag."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "version", "--advanced"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "interlocks version: unknown flag --advanced" in capsys.readouterr().err


def test_main_rejects_boolean_flag_value_form(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pure boolean flags are bare-only, so value forms cannot be silently ignored."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "doctor", "--json=true"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "interlocks doctor: unknown flag --json=true" in capsys.readouterr().err


def test_main_quiet_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The deprecated --quiet exits 1 (was 2 — exit 2 is reserved for no-project)."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "help", "--quiet"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        captured.err == "interlocks: --quiet was removed; minimal output is the default. "
        "Pass --verbose for full output.\n"
    )


def test_main_quiet_json_error_is_parseable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "check", "--json", "--quiet"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "interlocks"
    assert payload["error"] == "--quiet was removed; minimal output is the default"
    assert payload["next_action"] == "Remove `--quiet`; pass `--verbose` for full output."


def test_fail_quiet_removed_writes_exact_human_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "help", "--quiet"])

    with pytest.raises(SystemExit) as exc:
        _fail_quiet_removed()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        captured.err == "interlocks: --quiet was removed; minimal output is the default. "
        "Pass --verbose for full output.\n"
    )


def test_fail_unknown_command_writes_exact_human_error_to_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "bogus"])
    monkeypatch.setattr("interlocks.cli.cmd_help", lambda: None)

    with pytest.raises(SystemExit) as exc:
        _fail_unknown_command("bogus")

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Unknown command: bogus\n"


def test_main_declared_flag_passes_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared task flag is accepted — validation does not reject it."""
    calls: list[str] = []

    def fake() -> None:
        calls.append("ran")

    monkeypatch.setitem(TASKS, "gate coverage", (fake, "Tests with coverage threshold (--min=N)"))
    monkeypatch.setattr("interlocks.cli.preflight", lambda name: None)
    monkeypatch.setattr("interlocks.cli.validate_cli_skip", lambda: None)
    monkeypatch.setattr(sys, "argv", ["interlocks", "gate", "coverage", "--min=80"])
    main()
    assert calls == ["ran"]


def test_main_optional_flag_value_form_passes_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional-value flags such as --changed[=REF] still accept a value form."""
    calls: list[str] = []

    def fake() -> None:
        calls.append("ran")

    monkeypatch.setitem(TASKS, "check", (fake, "Local edit loop"))
    monkeypatch.setattr("interlocks.cli.preflight", lambda name: None)
    monkeypatch.setattr("interlocks.cli.validate_cli_skip", lambda: None)
    monkeypatch.setattr(sys, "argv", ["interlocks", "check", "--changed=HEAD"])
    main()
    assert calls == ["ran"]


def test_main_global_flags_pass_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global/dispatcher-level flags (--verbose, --skip=) pass the task-flag validator."""
    calls: list[str] = []

    def fake() -> None:
        calls.append("ran")

    monkeypatch.setitem(TASKS, "gate coverage", (fake, "Tests with coverage threshold (--min=N)"))
    monkeypatch.setattr("interlocks.cli.preflight", lambda name: None)
    monkeypatch.setattr("interlocks.cli.validate_cli_skip", lambda: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "gate", "coverage", "--verbose", "--skip=test"],
    )
    main()
    assert calls == ["ran"]


# ─────────────── interlocks config ──────────────────────────────────


_INTERNAL_CONFIG_FIELDS: frozenset[str] = frozenset({
    "project_root",
    "value_sources",
    "unsupported_presets",
    # ``tool_versions`` is a sub-table override map ([tool.interlocks.tools]),
    # not a single-key threshold — it isn't surfaced by ``interlocks config``.
    "tool_versions",
})


def test_config_keys_match_dataclass_fields() -> None:
    """``CONFIG_KEYS`` must document every public ``InterlockConfig`` field."""
    documented = {k.name for k in CONFIG_KEYS}
    fields = {f.name for f in dataclasses.fields(InterlockConfig)} - _INTERNAL_CONFIG_FIELDS
    assert documented == fields


def test_cmd_config_lists_all_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_project_with_interlocks(tmp_path, monkeypatch, 'preset = "baseline"')

    cmd_config()

    out = capsys.readouterr().out
    # Config drops the chrome banner.
    assert "command=config" not in out
    assert "── Status" in out
    assert "── Resolved values" in out
    assert "── Config keys" in out
    assert "── Precedence" in out
    assert "── Examples" in out
    assert "── Next steps" in out
    for key in CONFIG_KEYS:
        assert key.name in out
    # Preset-derived value renders for baseline coverage_min == 70.
    assert re.search(r"coverage_min\s+70 \(preset-derived\)", out)
    assert "baseline|strict|legacy|progressive" in out
    assert "interlocks presets set progressive" in out
    assert 'preset = "progressive"' in out

    # Default mode: the grouped "Config keys" table is the single presenter; the
    # flat "Resolved values" block is verbose-only.
    monkeypatch.setattr("interlocks.ui.is_verbose", lambda: False)
    cmd_config()
    default_out = capsys.readouterr().out
    for key in CONFIG_KEYS:
        assert key.name in default_out
    for group in CONFIG_KEY_GROUP_ORDER:
        if any(k.group == group for k in CONFIG_KEYS):
            assert group in default_out
    assert re.search(r"coverage_min\s+int\s+80\s+70\s+preset-derived", default_out)
    assert "── Resolved values" not in default_out
    assert "(preset-derived)" not in default_out


def test_cmd_config_no_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    monkeypatch.chdir(tmp_path)

    cmd_config()

    out = capsys.readouterr().out
    assert "(none — run `interlocks init`)" in out
    assert "Scaffold a project:" in out
    assert "missing-project" in out
    assert re.search(r"coverage_min\s+int\s+80\s+\(not resolved\)\s+missing-project", out)
    assert str(tmp_path) not in out


def test_cmd_config_show_reports_bundled_tool_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_minimal_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["interlocks", "config", "show", "ruff"])

    cmd_config()

    out = capsys.readouterr().out
    assert "command=config show ruff" not in out
    assert re.search(r"source\s+bundled", out)
    assert "Bundled config is used only when the project has no native tool config." in out


def test_cmd_config_show_basedpyright_explains_adoption_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_minimal_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["interlocks", "config", "show", "basedpyright"])

    cmd_config()

    out = capsys.readouterr().out
    assert re.search(r"source\s+bundled", out)
    assert "adoption baseline" in out
    assert "fewer diagnostics than raw basedpyright" in out
    assert "[tool.basedpyright]" in out
    assert "pyrightconfig.json" in out
    assert "pyrightconfig.toml" in out


def test_cmd_config_show_reports_project_tool_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_minimal_project(tmp_path, monkeypatch)
    (tmp_path / "ruff.toml").write_text("line-length = 99\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["interlocks", "config", "show", "ruff"])

    cmd_config()

    out = capsys.readouterr().out
    assert re.search(r"source\s+project: ruff.toml", out)
    assert "Project config replaces the bundled default; it does not extend it." in out


def test_cmd_config_show_json_is_parseable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_minimal_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["interlocks", "config", "show", "coverage", "--json"])

    cmd_config()

    assert json.loads(capsys.readouterr().out)["tool"] == "coverage"


def test_cmd_config_show_json_keys_are_sorted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_minimal_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["interlocks", "config", "show", "coverage", "--json"])

    cmd_config()

    out = capsys.readouterr().out.strip()
    assert out.startswith('{"bundled_path":')
    assert '"tool": "coverage"' in out


def test_cmd_config_show_json_invalid_usage_is_parseable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "config", "show", "bogus", "--json"])

    with pytest.raises(SystemExit) as exc:
        cmd_config()

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "config"
    assert payload["error"] == "invalid usage"
    assert "usage: interlocks config" in payload["usage"]
    assert payload["expected_tools"]


def test_cmd_config_json_is_parseable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    _setup_minimal_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["interlocks", "config", "--json"])

    cmd_config()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "config"
    assert "preset" in payload
    assert "pyproject_path" in payload
    assert isinstance(payload["keys"], list) and payload["keys"]
    for entry in payload["keys"]:
        assert {
            "default",
            "description",
            "group",
            "key",
            "source",
            "type",
            "value",
        } == entry.keys()
    coverage = next(entry for entry in payload["keys"] if entry["key"] == "coverage_min")
    assert coverage["type"] == "int"
    assert coverage["default"] == "80"
    assert coverage["description"] == "coverage.py fail-under"


def test_config_json_value_coerces_raw_values_exactly(tmp_path: Path) -> None:
    cfg = InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "src",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
        properties_dir=tmp_path / "props",
        pytest_args=("--maxfail=1", "-q"),
        skip=frozenset({"mutation", "test"}),
        coverage_min=91,
    )

    assert _json_value(cfg, "skip") == ["mutation", "test"]
    assert _json_value(cfg, "pytest_args") == ["--maxfail=1", "-q"]
    assert _json_value(cfg, "properties_dir") == str(tmp_path / "props")
    assert _json_value(cfg, "coverage_min") == 91


def test_cmd_config_json_falls_back_when_pyproject_malformed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text("not = [valid toml\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "config", "--json"])

    cmd_config()  # must not raise

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "config"
    assert payload["preset"] is None
    assert payload["keys"]
    for entry in payload["keys"]:
        assert entry["value"] is None
        assert entry["source"] == "unreadable"
        assert entry["type"]
        assert entry["default"]
        assert entry["description"]


def test_cmd_config_json_without_pyproject_does_not_resolve_current_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "config", "--json"])

    cmd_config()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "config"
    assert payload["pyproject_path"] is None
    assert payload["preset"] is None
    assert payload["keys"]
    assert {entry["value"] for entry in payload["keys"]} == {None}
    assert {entry["source"] for entry in payload["keys"]} == {"missing-project"}


def test_cmd_config_falls_back_when_pyproject_malformed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    (tmp_path / "pyproject.toml").write_text("not = [valid toml\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cmd_config()  # must not raise

    out = capsys.readouterr().out
    assert "── Config keys" in out
    for key in CONFIG_KEYS:
        assert key.name in out


def test_cmd_help_does_not_mention_user_global(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Drift guard: the user-global config layer is gone — never reference it."""
    cmd_help()
    out = capsys.readouterr().out
    assert "user-global" not in out
    assert "XDG_CONFIG_HOME" not in out
    assert "~/.config/interlocks" not in out


# ─────────────── interlocks explain ─────────────────────────────────


def test_command_docs_cover_every_command() -> None:
    """Drift guard: every command in ``TASKS`` has a ``CommandDoc``, and vice versa."""
    assert set(COMMAND_DOCS_BY_NAME) == set(TASKS)


def test_command_docs_summary_matches_task_description() -> None:
    """``CommandDoc.summary`` is canonical — the bare ``TASKS`` string must match it."""
    for doc in COMMAND_DOCS:
        assert doc.summary == TASKS[doc.name][1], doc.name


def test_command_groups_match_task_groups() -> None:
    """The pure command-doc grouping mirrors the dispatcher grouping."""
    expected = tuple((group, tuple(commands)) for group, commands in TASK_GROUPS)
    assert expected == COMMAND_GROUPS


def test_flag_sets_for_property_candidates_partition_exactly() -> None:
    boolean_names, optional_names, value_prefixes = _flag_sets_for_task("property-candidates")

    assert boolean_names == frozenset({"--json", "--uncovered"})
    assert optional_names == frozenset({"--changed"})
    assert value_prefixes == ("--max-refs=", "--limit=")


def test_flag_sets_treat_value_shaped_flags_as_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = CommandDoc(
        "synthetic",
        "Synthetic command",
        "Exercises value-shaped flag partitioning.",
        mutates=False,
        outputs=(),
        exit_codes=((0, "ok"),),
        flags=(
            FlagSpec("--good", "boolean", "off", "boolean"),
            FlagSpec("--maybe", "optional", "default", "optional"),
            FlagSpec("--misdeclared=", "boolean", "off", "value-shaped boolean"),
            FlagSpec("--value=", "value", "x", "value"),
        ),
    )
    monkeypatch.setitem(COMMAND_DOCS_BY_NAME, "synthetic", doc)

    boolean_names, optional_names, value_prefixes = _flag_sets_for_task("synthetic")

    assert boolean_names == frozenset({"--good"})
    assert optional_names == frozenset({"--maybe"})
    assert value_prefixes == ("--misdeclared=", "--value=")


# Maps each command to the module(s) whose source declares its flag reads.
# A command's flags may be read in a stage helper (e.g. stages/_budgeted.py)
# in addition to its own module, so each entry is a tuple of import paths.
_FLAG_SOURCE_MODULES: dict[str, tuple[str, ...]] = {
    "gate coverage": ("interlocks.tasks.coverage",),
    "gate crap": ("interlocks.tasks.crap",),
    "gate mutation": ("interlocks.tasks.mutation",),
    "gate properties": ("interlocks.tasks.properties",),
    "fix optimize": ("interlocks.tasks.fix_optimize", "interlocks.tasks.fix_cli"),
    "fix rule": ("interlocks.tasks.fix_rule", "interlocks.tasks.fix_cli"),
    "fix plan": ("interlocks.tasks.fix_plan",),
    "fix replay": ("interlocks.tasks.fix_replay",),
    "fix annotate": ("interlocks.tasks.fix_annotate",),
    "baseline": ("interlocks.tasks.baseline_cmd",),
    "trust": ("interlocks.tasks.stats",),
    "property-candidates": ("interlocks.tasks.property_candidates",),
    "setup": ("interlocks.tasks.setup",),
    "init": ("interlocks.tasks.init",),
    "config": ("interlocks.tasks.config",),
    "check": ("interlocks.stages.check", "interlocks.stages._budgeted"),
    "hook pre-commit": ("interlocks.stages._budgeted",),
    "hook post-edit": ("interlocks.stages._budgeted",),
}

# Flag literals that appear in a module's source for unrelated reasons and
# must not be counted as a declared task flag.
_FLAG_SCAN_IGNORE: frozenset[str] = frozenset({"--quiet", "--verbose"})

# `--json` is read centrally via `interlocks.ui.is_json()` (argv-derived, like
# `is_verbose`), not from a per-task module — so it is declared as a FlagSpec for
# dispatcher acceptance and `--help` rendering but never appears as a literal in a
# task's own source. Excluded from both sides of the drift-guard comparison.
_CENTRAL_FLAGS: frozenset[str] = frozenset({"--json", "--skip="})

# arg_value("--x=", ...)  |  arg_flag_value("--x", ...)  |  "--x" in <seq>
#   plus the bare-equality forms: arg == "--check"  /  "--json" == arg
# `<seq>` is `sys.argv` (stats.py) or a local flags list (baseline_cmd.py).
_FLAG_LITERAL_RE = re.compile(
    r'arg_value\(\s*"(--[a-z-]+=)"'  # value flags carry the trailing =
    r'|arg_flag_value\(\s*"(--[a-z-]+)"'  # boolean flags, no =
    r'|"(--[a-z-]+(?:=[a-z]+)?)"\s*(?:in [\w.]+|==)'  # membership / equality (literal left)
    r'|==\s*"(--[a-z-]+(?:=[a-z]+)?)"'  # equality with the literal on the right
)


def _scanned_flag_names(modules: tuple[str, ...]) -> set[str]:
    """Recover the flag-name set a command reads, from its module source.

    Normalizes to ``FlagSpec.name`` form: value flags keep the trailing ``=``,
    boolean flags do not. ``--ci=github`` (a literal-valued membership check in
    ``setup.py``) is normalized to ``--ci=``.
    """
    found: set[str] = set()
    for module_path in modules:
        src = inspect.getsource(importlib.import_module(module_path))
        for value_flag, bool_flag, direct_flag, eq_flag in _FLAG_LITERAL_RE.findall(src):
            flag = value_flag or bool_flag or direct_flag or eq_flag
            if flag in _FLAG_SCAN_IGNORE:
                continue
            # `--ci=github` -> `--ci=` so it matches the declared value flag.
            if "=" in flag and not flag.endswith("="):
                flag = flag.split("=", 1)[0] + "="
            found.add(flag)
    return found


def test_declared_flags_match_task_source() -> None:
    """Drift guard: declared FlagSpec names equal the flag literals each task reads.

    An undeclared-but-read flag would be hard-rejected by the dispatcher before
    the task runs; a declared-but-unread flag is dead doc. Both are bugs.
    """
    for command, modules in _FLAG_SOURCE_MODULES.items():
        declared = {
            spec.name
            for spec in COMMAND_DOCS_BY_NAME[command].flags
            if spec.name not in _CENTRAL_FLAGS
        }
        scanned = _scanned_flag_names(modules) - _CENTRAL_FLAGS
        assert declared == scanned, (
            f"{command}: declared {sorted(declared)} != source-read {sorted(scanned)}"
        )


def test_every_flag_source_module_command_exists() -> None:
    """The drift-guard module map only references real commands."""
    assert set(_FLAG_SOURCE_MODULES) <= set(COMMAND_DOCS_BY_NAME)


def test_command_doc_flags_default_to_empty() -> None:
    """The new ``flags`` field defaults to ``()`` — non-flag-bearing docs unchanged."""
    doc = CommandDoc(
        "demo",
        "Demo command",
        "Demonstrates default command metadata.",
        mutates=False,
        outputs=(),
        exit_codes=((0, "ok"),),
    )
    assert doc.flags == ()
    assert doc.usage == ""
    assert doc.mutates_note == ""


def test_command_doc_payload_reports_exact_machine_contract() -> None:
    doc = CommandDoc(
        "gate behavior-attribution",
        "Show which acceptance behavior each test covers",
        "Use before trusting acceptance coverage automation.",
        mutates=True,
        outputs=("json", "markdown"),
        exit_codes=((0, "trace written"), (1, "trace failed")),
        flags=(
            FlagSpec("--json", "boolean", "off", "emit JSON"),
            FlagSpec("--changed=", "value", "HEAD", "compare ref"),
        ),
        usage="gate behavior-attribution [--json] [--changed=REF]",
        mutates_note="writes .interlocks/behavior-attribution.json",
    )

    assert command_doc_payload(doc) == {
        "command": "gate behavior-attribution",
        "usage": "usage: interlocks gate behavior-attribution [--json] [--changed=REF]",
        "summary": "Show which acceptance behavior each test covers",
        "when_to_use": "Use before trusting acceptance coverage automation.",
        "mutates": True,
        "mutates_note": "writes .interlocks/behavior-attribution.json",
        "outputs": ["json", "markdown"],
        "aliases": [],
        "flags": [
            {
                "name": "--json",
                "kind": "boolean",
                "default": "off",
                "description": "emit JSON",
            },
            {
                "name": "--changed=",
                "kind": "value",
                "default": "HEAD",
                "description": "compare ref",
            },
        ],
        "exit_codes": [
            {"code": 0, "meaning": "trace written"},
            {"code": 1, "meaning": "trace failed"},
        ],
    }


def test_flag_spec_is_frozen() -> None:
    """``FlagSpec`` is a frozen dataclass — declarations are immutable data."""
    spec = FlagSpec("--min=", "value", "cfg.coverage_min", "coverage floor")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "--max="  # type: ignore[misc]


def test_cmd_explain_default_is_index(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No-arg `explain` prints the grouped index — every command, no prose detail."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain"])

    cmd_explain()

    out = capsys.readouterr().out
    for name in TASKS:
        assert f"  [{name}]  " in out
    assert "interlocks explain --all" in out
    # The index is the header line only — the 5-line prose detail is suppressed.
    assert "When to use:" not in out
    assert "Exit codes:" not in out


def test_cmd_explain_all_dumps_every_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`explain --all` reproduces the full per-command prose dump."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "--all"])

    cmd_explain()

    out = capsys.readouterr().out
    for name in TASKS:
        assert f"  [{name}]  " in out
    assert "When to use:" in out
    assert "Mutates:" in out
    assert "Exit codes:" in out


def test_cmd_explain_single_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "gate", "coverage"])

    cmd_explain()

    out = capsys.readouterr().out
    assert "  [gate coverage]  " in out
    assert "Usage:      interlocks gate coverage" in out
    assert "When to use:" in out
    assert "[fix]" not in out


def test_cmd_explain_json_default_is_index(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "--json"])

    cmd_explain()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "explain"
    assert payload["mode"] == "index"
    commands = [command for group in payload["groups"] for command in group["commands"]]
    assert {command["name"] for command in commands} == set(TASKS)
    assert all("when_to_use" not in command for command in commands)


def test_cmd_explain_json_all_includes_full_contracts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "--all", "--json"])

    cmd_explain()

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "all"
    check = next(
        command
        for group in payload["groups"]
        for command in group["commands"]
        if command["command"] == "check"
    )
    assert check["usage"] == "usage: interlocks check"
    assert "when_to_use" in check
    assert any(flag["name"] == "--json" for flag in check["flags"])


def test_cmd_explain_json_single_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["interlocks", "explain", "gate", "coverage", "--json"],
    )

    cmd_explain()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "gate coverage"
    assert payload["usage"] == "usage: interlocks gate coverage"
    assert any(flag["name"] == "--properties" for flag in payload["flags"])


def test_cmd_explain_properties_surfaces_adoption_loop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "gate", "properties"])

    cmd_explain()

    out = capsys.readouterr().out
    assert "init --properties" in out
    assert "--profile=check" in out
    assert "--profile=ci|nightly" in out


def test_cmd_explain_check_mentions_changed_scope_property_skip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "check"])

    cmd_explain()

    out = capsys.readouterr().out
    assert "`--changed` skips broad test/acceptance/property gates" in out
    assert "follow-up next actions" in out


def test_cmd_explain_init_mentions_property_scaffold_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "init"])

    cmd_explain()

    out = capsys.readouterr().out
    assert "--properties" in out
    assert "--acceptance" in out


def test_cmd_explain_property_candidates_surfaces_agent_triage_loop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "property-candidates"])

    cmd_explain()

    out = capsys.readouterr().out
    assert "--changed=REF" in out
    assert "--uncovered" in out
    assert "writes no tests" in out


def test_cmd_explain_baseline_distinguishes_read_and_write_actions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "baseline"])

    cmd_explain()

    out = capsys.readouterr().out
    assert "Usage:      interlocks baseline [show|init|advance|check]" in out
    assert "Mutates:     show/check are read-only; init/advance write baseline.json" in out
    assert "`show`/`check` are read-only" in out
    assert "`init`/`advance` write the floor" in out


def test_cmd_explain_presets_recommends_progressive_copyable_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "presets"])

    cmd_explain()

    out = capsys.readouterr().out
    assert "copyable progressive config" in out
    assert "listing is read-only" in out
    assert "Mutates:     listing is read-only; set writes pyproject.toml" in out


def test_cmd_explain_unknown_command_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "bogus"])

    with pytest.raises(SystemExit) as exc:
        cmd_explain()

    assert exc.value.code == 1
    assert "unknown command: bogus" in capsys.readouterr().out


def test_cmd_explain_rejects_unknown_option(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "--bogus"])

    with pytest.raises(SystemExit) as exc:
        cmd_explain()

    assert exc.value.code == 1
    assert "--bogus" in capsys.readouterr().out


def test_cmd_explain_resolves_alias(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "explain", "fix", "unblock"])

    cmd_explain()

    out = capsys.readouterr().out
    assert "  [fix optimize]  " in out
    assert "(alias: fix unblock)" in out
