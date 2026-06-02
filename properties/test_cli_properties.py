"""Property tests for CLI display helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks import cli as cli_mod
from interlocks import ui
from interlocks.cli import (
    _HELP_GROUPS,
    TASK_GROUPS,
    TASKS,
    _available_preset_payload,
    _current_preset_payload,
    _detected_payload,
    _detected_summary_line,
    _help_command_payload,
    _help_groups_payload,
    _maybe_handle_presets_set,
    _missing_command_payload,
    _presets_error_payload,
    _presets_payload,
    _quiet_removed_payload,
    _resolve_task_name,
    _task_help_payload,
    _unknown_command_payload,
    _unknown_flag_payload,
    _validate_task_flags,
)
from interlocks.config import (
    InterlockConfig,
    Preset,
    TestRunner,
    preset_defaults,
    preset_description,
    supported_presets,
)

_REL_PATH = st.from_regex(
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}){0,2}",
    fullmatch=True,
)
_PRESET = st.one_of(
    st.none(),
    st.sampled_from(["baseline", "strict", "legacy", "progressive"]),
)
_KNOWN_PRESET = st.sampled_from(supported_presets())
_RUNNER = st.sampled_from(["pytest", "unittest"])
_FLAG = st.from_regex(r"--[a-z][a-z0-9-]{0,20}", fullmatch=True)
_COMMAND = st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True)
_KNOWN_COMMAND = st.sampled_from([
    ("check", "check"),
    ("unblock", "fix-optimize"),
    ("attribution", "behavior-attribution"),
])
_KNOWN_CHECK_FLAG_VALUES = (
    "--changed",
    "--changed=HEAD",
    "--json",
    "--mutation-budget=quick",
    "--renovate",
    "--skip=mutation",
)
_KNOWN_CHECK_FLAG = st.sampled_from(_KNOWN_CHECK_FLAG_VALUES)
_TASK_NAME = st.sampled_from(tuple(sorted(TASKS)))
_DOC_TASK_NAME = st.sampled_from(tuple(sorted(cli_mod.COMMAND_DOCS_BY_NAME)))
_UNKNOWN_DOC_COMMAND = _COMMAND.filter(lambda name: name not in cli_mod.COMMAND_DOCS_BY_NAME)
_PRESET_ARGS = st.lists(
    st.from_regex(r"[a-z][a-z0-9-]{0,12}", fullmatch=True),
    max_size=3,
)


def _run_maybe_handle_presets_set(args: list[str]) -> tuple[bool | str, list[list[str]]]:
    calls: list[list[str]] = []

    def fake_set(set_args: list[str]) -> None:
        calls.append(set_args)

    def fake_error(_error: str, _detail: str) -> None:
        raise RuntimeError("invalid presets usage")

    old_argv = sys.argv
    old_set = cli_mod._cmd_presets_set
    old_error = cli_mod._fail_presets_error
    sys.argv = ["interlocks", "presets", *args, "--json"]
    cli_mod._cmd_presets_set = fake_set  # type: ignore[assignment]
    cli_mod._fail_presets_error = fake_error  # type: ignore[assignment]
    try:
        outcome = _call_maybe_handle_presets_set()
    finally:
        cli_mod._cmd_presets_set = old_set  # type: ignore[assignment]
        cli_mod._fail_presets_error = old_error  # type: ignore[assignment]
        sys.argv = old_argv
    return outcome, calls


def _call_maybe_handle_presets_set() -> bool | str:
    try:
        return _maybe_handle_presets_set()
    except RuntimeError:
        return "invalid"


@given(preset=_PRESET, src=_REL_PATH, tests=_REL_PATH, runner=_RUNNER)
def test_detected_summary_line_uses_resolved_config_labels(
    preset: str | None,
    src: str,
    tests: str,
    runner: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / src,
            test_dir=root / tests,
            test_runner=cast("TestRunner", runner),
            test_invoker="python",
            preset=cast("Preset | None", preset),
        )

        line = _detected_summary_line(cfg)

    assert line == (
        f"Detected: preset={preset or '(none)'}, src={src}, tests={tests}, runner={runner}"
    )


@given(src=_REL_PATH, tests=_REL_PATH, runner=_RUNNER)
def test_detected_summary_line_renders_missing_preset_as_none_label(
    src: str,
    tests: str,
    runner: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / src,
            test_dir=root / tests,
            test_runner=cast("TestRunner", runner),
            test_invoker="python",
            preset=None,
        )

        line = _detected_summary_line(cfg)

    assert line.startswith("Detected: preset=(none), ")


@given(preset=_PRESET, src=_REL_PATH, tests=_REL_PATH, runner=_RUNNER)
def test_detected_payload_projects_resolved_config_when_pyproject_exists(
    preset: str | None,
    src: str,
    tests: str,
    runner: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        (root / "pyproject.toml").write_text("[project]\nname='pkg'\n", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / src,
            test_dir=root / tests,
            test_runner=cast("TestRunner", runner),
            test_invoker="python",
            preset=cast("Preset | None", preset),
        )

        payload = _detected_payload(cfg)

    assert payload == {
        "pyproject": True,
        "preset": preset,
        "src": src,
        "tests": tests,
        "runner": runner,
    }


def test_detected_payload_marks_missing_pyproject() -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )

        payload = _detected_payload(cfg)

    assert payload == {"pyproject": False}
    assert _detected_payload(None) == {"pyproject": False}


@given(preset=_PRESET)
def test_current_preset_payload_tracks_pyproject_presence(preset: str | None) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            preset=cast("Preset | None", preset),
        )

        missing = _current_preset_payload(cfg)
        (root / "pyproject.toml").write_text("[project]\nname='pkg'\n", encoding="utf-8")
        present = _current_preset_payload(cfg)

    assert missing == {"pyproject": False, "preset": None}
    assert present == {
        "pyproject": True,
        "preset": preset,
        "pyproject_path": "pyproject.toml",
    }
    assert _current_preset_payload(None) == {"pyproject": False, "preset": None}


@given(preset=_KNOWN_PRESET)
def test_available_preset_payload_projects_defaults_and_description(preset: Preset) -> None:
    payload = _available_preset_payload(preset)

    assert payload == {
        "name": preset,
        "description": preset_description(preset),
        "defaults": preset_defaults(preset),
    }


@given(preset=_PRESET)
def test_presets_payload_lists_supported_presets_and_current_values(preset: str | None) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        (root / "pyproject.toml").write_text("[project]\nname='pkg'\n", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            preset=cast("Preset | None", preset),
            value_sources={"coverage_min": "preset-derived"},
        )

        payload = _presets_payload(cfg)

    assert payload["command"] == "presets"
    assert payload["current"] == {
        "pyproject": True,
        "preset": preset,
        "pyproject_path": "pyproject.toml",
    }
    available = payload["available_presets"]
    current_values = payload["current_values"]
    assert isinstance(available, list)
    assert isinstance(current_values, list)
    assert [entry["name"] for entry in available] == list(supported_presets())
    coverage = next(entry for entry in current_values if entry["key"] == "coverage_min")
    assert coverage["source"] == "preset-derived"
    assert payload["switch_command"] == (
        "interlocks presets set <baseline|strict|legacy|progressive>"
    )


@given(error=st.text(max_size=100), detail=st.text(max_size=100))
def test_presets_error_payload_lists_supported_presets(error: str, detail: str) -> None:
    payload = _presets_error_payload(error, detail)

    assert payload["command"] == "presets"
    assert payload["error"] == error
    assert payload["detail"] == detail
    assert "usage: interlocks presets" in str(payload["usage"])
    assert payload["expected_presets"] == list(supported_presets())


@given(args=_PRESET_ARGS)
def test_maybe_handle_presets_set_delegates_only_when_positionals_follow_command(
    args: list[str],
) -> None:
    outcome, calls = _run_maybe_handle_presets_set(args)

    if len(args) > 1 and args[0] != "set":
        assert outcome == "invalid"
        assert calls == []
        return

    if not args:
        assert outcome is False
        assert calls == []
    elif args[0] == "set":
        assert outcome is True
        assert calls == [args[1:]]
    else:
        assert outcome is True
        assert calls == [args]


def test_maybe_handle_presets_set_ignores_flag_only_invocation() -> None:
    outcome, calls = _run_maybe_handle_presets_set(["--json", "--verbose"])

    assert outcome is False
    assert calls == []


def test_maybe_handle_presets_set_returns_false_for_direct_flag_only_argv() -> None:
    old_argv = sys.argv
    sys.argv = ["interlocks", "presets", "--json", "--verbose"]
    try:
        assert _maybe_handle_presets_set() is False
    finally:
        sys.argv = old_argv


@given(advanced=st.booleans())
def test_help_groups_payload_lists_known_commands_without_duplicates(advanced: bool) -> None:
    payload = _help_groups_payload(advanced=advanced)
    names: list[str] = []
    for group in payload:
        commands = group["commands"]
        assert isinstance(commands, list)
        for command in commands:
            assert isinstance(command, dict)
            name = command["name"]
            assert isinstance(name, str)
            names.append(name)

    assert len(names) == len(set(names))
    assert set(names) <= set(TASKS)
    if advanced:
        assert set(names) == set(TASKS)
    else:
        expected = {name for _group, names in _HELP_GROUPS for name in names}
        assert set(names) == expected


@given(advanced=st.booleans())
def test_help_groups_payload_preserves_declared_group_order(advanced: bool) -> None:
    payload = _help_groups_payload(advanced=advanced)
    expected_groups = TASK_GROUPS if advanced else _HELP_GROUPS

    assert [group["name"] for group in payload] == [
        group_name for group_name, _names in expected_groups
    ]
    assert [
        [command["name"] for command in group["commands"]]
        for group in payload
    ] == [list(names) for _group_name, names in expected_groups]


@given(task_name=_TASK_NAME)
def test_help_command_payload_projects_registered_command_row(task_name: str) -> None:
    payload = _help_command_payload(task_name)

    assert payload["name"] == task_name
    assert payload["summary"] == TASKS[task_name][1]
    assert isinstance(payload["aliases"], list)


@given(task_name=_DOC_TASK_NAME)
def test_help_command_payload_reuses_command_doc_index_payload(task_name: str) -> None:
    doc = cli_mod.COMMAND_DOCS_BY_NAME[task_name]

    assert _help_command_payload(task_name) == cli_mod.command_index_payload(doc)


@given(
    command_pair=_KNOWN_COMMAND,
    leading_flags=st.lists(_KNOWN_CHECK_FLAG, max_size=3),
    trailing_args=st.lists(st.text(max_size=10), max_size=3),
)
def test_resolve_task_name_uses_first_positional_and_aliases(
    command_pair: tuple[str, str],
    leading_flags: list[str],
    trailing_args: list[str],
) -> None:
    requested, expected = command_pair
    raw_args = [*leading_flags, requested, *trailing_args]

    assert _resolve_task_name(raw_args) == expected


@given(flags=st.lists(_KNOWN_CHECK_FLAG, max_size=6))
def test_resolve_task_name_returns_none_when_only_flags(flags: list[str]) -> None:
    with (
        patch.object(ui, "is_json", return_value=False),
        patch("interlocks.cli.cmd_help_from_argv"),
    ):
        assert _resolve_task_name(flags) is None


@given(flags=st.lists(_KNOWN_CHECK_FLAG, max_size=6))
def test_validate_task_flags_accepts_declared_and_global_flags(flags: list[str]) -> None:
    _validate_task_flags("check", ["check", *flags])


@given(flag=_FLAG.filter(lambda value: value not in _KNOWN_CHECK_FLAG_VALUES))
def test_validate_task_flags_reports_first_unknown_flag(flag: str) -> None:
    calls: list[tuple[str, str]] = []
    old_fail = cli_mod._fail_unknown_flag

    def fake_fail(task_name: str, bad_flag: str) -> None:
        calls.append((task_name, bad_flag))
        raise RuntimeError("unknown flag")

    cli_mod._fail_unknown_flag = fake_fail  # type: ignore[assignment]
    try:
        try:
            _validate_task_flags("check", ["check", flag, "--also-bad"])
        except RuntimeError:
            pass
        else:  # pragma: no cover - guarded by the assertion above
            raise AssertionError("_validate_task_flags should reject unknown flags")
    finally:
        cli_mod._fail_unknown_flag = old_fail  # type: ignore[assignment]

    assert calls == [("check", flag)]


@given(flag=_FLAG)
def test_unknown_flag_payload_includes_command_usage_and_declared_flags(flag: str) -> None:
    payload = _unknown_flag_payload("check", flag)

    assert payload["command"] == "check"
    assert payload["error"] == f"unknown flag {flag}"
    assert payload["flag"] == flag
    assert "usage: interlocks check" in str(payload["usage"])
    known_flags = payload["known_flags"]
    assert isinstance(known_flags, list)
    assert "--json" in known_flags


@given(task_name=_COMMAND, flag=_FLAG)
def test_unknown_flag_payload_omits_usage_for_unknown_commands(
    task_name: str,
    flag: str,
) -> None:
    payload = _unknown_flag_payload(task_name, flag)

    assert payload["command"] == task_name
    assert payload["error"] == f"unknown flag {flag}"
    assert payload["flag"] == flag
    if task_name not in cli_mod.COMMAND_DOCS_BY_NAME:
        assert "usage" not in payload
        assert "known_flags" not in payload


@given(command=_COMMAND)
def test_unknown_command_payload_lists_known_command_domain(command: str) -> None:
    payload = _unknown_command_payload(command)

    assert payload["command"] == command
    assert payload["error"] == f"unknown command {command}"
    assert payload["usage"] == "usage: interlocks <command>"
    known_commands = payload["known_commands"]
    assert isinstance(known_commands, list)
    assert known_commands == sorted(known_commands)
    assert "check" in known_commands


def test_missing_command_payload_lists_known_command_domain() -> None:
    payload = _missing_command_payload()

    assert payload["command"] == "interlocks"
    assert payload["error"] == "missing command"
    assert payload["usage"] == "usage: interlocks <command>"
    known_commands = payload["known_commands"]
    assert isinstance(known_commands, list)
    assert known_commands == sorted(known_commands)
    assert "check" in known_commands


def test_task_help_payload_projects_command_doc_metadata() -> None:
    payload = _task_help_payload("check")

    assert payload["command"] == "check"
    assert payload["usage"] == "usage: interlocks check"
    assert isinstance(payload["flags"], list)
    assert any(flag["name"] == "--json" for flag in payload["flags"])
    assert isinstance(payload["exit_codes"], list)
    assert any(entry["code"] == 0 for entry in payload["exit_codes"])


@given(task_name=_UNKNOWN_DOC_COMMAND)
def test_task_help_payload_falls_back_for_private_task_names(task_name: str) -> None:
    assert _task_help_payload(task_name) == {
        "command": task_name,
        "usage": f"usage: interlocks {task_name}",
        "flags": [],
    }


def test_quiet_removed_payload_points_to_current_output_modes() -> None:
    payload = _quiet_removed_payload()

    assert payload["command"] == "interlocks"
    assert payload["error"] == "--quiet was removed; minimal output is the default"
    assert payload["next_action"] == "Remove `--quiet`; pass `--verbose` for full output."
