"""Unit tests for interlocks.cli dispatcher."""

from __future__ import annotations

import dataclasses
import json
import re
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from interlocks.cli import TASK_GROUPS, TASKS, cmd_help, cmd_presets, main
from interlocks.config import (
    CONFIG_KEYS,
    InterlockConfig,
    Preset,
    clear_cache,
    load_config,
    preset_defaults,
)
from interlocks.tasks.config import cmd_config

_DEFAULT_HELP_GROUPS = (
    ("Start here", ("doctor", "check", "ci", "setup")),
    (
        "Common gates",
        (
            "fix",
            "format",
            "lint",
            "typecheck",
            "test",
            "coverage",
            "audit",
            "deps",
            "arch",
            "acceptance",
        ),
    ),
    ("Project", ("init", "config", "presets", "version")),
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
    # Each entry is (callable, description).
    for fn, desc in TASKS.values():
        assert callable(fn)
        assert isinstance(desc, str) and desc


def test_cmd_help_prints_usage_and_groups(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_help()
    out = capsys.readouterr().out
    assert "interlocks v" in out
    assert "command=help" in out
    assert "Usage: interlocks <command>" in out
    assert "── Usage" in out
    assert "── More" in out
    assert "help --advanced" in out
    for group_name, names in _DEFAULT_HELP_GROUPS:
        assert f"── {group_name}" in out
        for name in names:
            assert f"[{name}]" in out
    assert "[evaluate]" not in out


def test_cmd_help_advanced_prints_all_groups(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_help(advanced=True)
    out = capsys.readouterr().out
    assert "── Commands" in out
    for group_name, group in TASK_GROUPS:
        assert f"{group_name}:" in out
        for name in group:
            assert f"[{name}]" in out


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


def test_cmd_presets_prints_options_and_copyable_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cmd_presets()
    out = capsys.readouterr().out
    assert "interlocks v" in out
    assert "command=presets" in out
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
    assert "interlocks presets set baseline" in out
    assert "Or add this to pyproject.toml:" in out
    assert '[tool.interlocks]\n    preset = "baseline"' in out
    assert "manually override any threshold" in out
    assert "pyproject.toml" in out


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


@pytest.mark.parametrize(
    ("preset", "expected_fragment"),
    [
        ("baseline", "advisory CRAP"),
        ("strict", "mature repo"),
        ("legacy", "ratcheting"),
        ("progressive", "autopilot ratchet"),
    ],
)
def test_cmd_presets_all_four_listed_with_descriptions(
    capsys: pytest.CaptureFixture[str],
    preset: str,
    expected_fragment: str,
) -> None:
    """All four presets appear in `interlocks presets` output with their descriptions."""
    cmd_presets()
    out = capsys.readouterr().out
    assert preset in out, f"preset {preset!r} missing from presets output"
    assert expected_fragment in out, (
        f"description fragment {expected_fragment!r} missing for preset {preset!r}"
    )


@pytest.mark.parametrize(
    ("preset", "key", "expected"),
    [
        # baseline: advisory gates, mutation off
        ("baseline", "enforce_crap", False),
        ("baseline", "run_mutation_in_ci", False),
        ("baseline", "mutation_ci_mode", "off"),
        ("baseline", "run_acceptance_in_check", False),
        ("baseline", "coverage_min", 70),
        # strict: all blocking gates on, mutation incremental
        ("strict", "enforce_crap", True),
        ("strict", "enforce_mutation", True),
        ("strict", "run_mutation_in_ci", True),
        ("strict", "mutation_ci_mode", "incremental"),
        ("strict", "run_acceptance_in_check", True),
        ("strict", "require_acceptance", True),
        ("strict", "coverage_min", 90),
        # legacy: very permissive, advisory only
        ("legacy", "enforce_crap", False),
        ("legacy", "run_mutation_in_ci", False),
        ("legacy", "coverage_min", 0),
        ("legacy", "mutation_ci_mode", "off"),
        # progressive: blocking gates on, permissive floors (ratcheted at runtime)
        ("progressive", "enforce_crap", True),
        ("progressive", "enforce_mutation", True),
        ("progressive", "run_mutation_in_ci", True),
        ("progressive", "mutation_ci_mode", "incremental"),
        ("progressive", "run_acceptance_in_check", True),
        ("progressive", "require_acceptance", True),
        ("progressive", "coverage_min", 0),  # floor; ratcheted by baseline.json
    ],
)
def test_preset_defaults_key_values(preset: Preset, key: str, expected: object) -> None:
    """``preset_defaults()`` returns the documented gate values for each preset."""
    defaults = preset_defaults(preset)
    assert defaults[key] == expected, (
        f"preset {preset!r}: expected {key}={expected!r}, got {defaults[key]!r}"
    )


def test_progressive_preset_enables_blocking_gates_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_config_cache: None,
) -> None:
    """``preset = progressive`` wires blocking gates (CRAP, mutation, acceptance)."""
    _setup_project_with_interlocks(tmp_path, monkeypatch, 'preset = "progressive"')

    cmd_presets()

    out = capsys.readouterr().out
    assert re.search(r"^\s*preset\s+progressive\s*$", out, re.MULTILINE), out
    assert re.search(r"^\s*enforce_crap\s+True \(preset-derived\)\s*$", out, re.MULTILINE), out
    assert re.search(r"^\s*enforce_mutation\s+True \(preset-derived\)\s*$", out, re.MULTILINE), out
    assert re.search(r"^\s*run_mutation_in_ci\s+True \(preset-derived\)\s*$", out, re.MULTILINE), (
        out
    )
    assert re.search(r"^\s*require_acceptance\s+True \(preset-derived\)\s*$", out, re.MULTILINE), (
        out
    )


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


def test_main_unknown_command_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "nope"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Unknown command: nope" in captured.err
    assert "Usage: interlocks <command>" in captured.out


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

    monkeypatch.setitem(TASKS, "coverage", (fake, "Tests with coverage threshold (--min=N)"))
    monkeypatch.setattr(sys, "argv", ["interlocks", "coverage", "--help"])

    main()

    assert calls == []
    out = capsys.readouterr().out
    assert "Usage: interlocks coverage" in out
    assert "[coverage]" in out


def test_main_rejects_unknown_skip_label(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "check", "--skip=nope"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    assert "unknown skip label" in capsys.readouterr().err


def test_main_dispatches_alias_to_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake() -> None:
        calls.append("ran")

    monkeypatch.setitem(TASKS, "behavior-attribution", (fake, "Attribution"))
    monkeypatch.setattr("interlocks.cli.preflight", lambda name: calls.append(f"preflight:{name}"))
    monkeypatch.setattr(sys, "argv", ["interlocks", "attribution"])

    main()

    assert calls == ["preflight:behavior-attribution", "ran"]


def test_cmd_help_lists_behavior_attribution_alias(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cmd_help(advanced=True)

    out = capsys.readouterr().out
    assert "[behavior-attribution]" in out
    assert "alias: attribution" in out


def test_main_skips_flag_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flags (starting with -) are filtered out before dispatch."""
    calls: list[str] = []

    def fake() -> None:
        calls.append("ran")

    monkeypatch.setitem(TASKS, "help", (fake, "Show help"))
    monkeypatch.setattr(sys, "argv", ["interlocks", "--verbose", "help"])
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
    assert "command=config" in out
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
    # Defaults still listed.
    assert re.search(r"coverage_min\s+80 \(bundled-default\)", out)


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
    assert "command=config show ruff" in out
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
