"""Property tests for runner output parsing."""

from __future__ import annotations

import io
import os
import string
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from interlocks import runner as runner_mod
from interlocks.defaults.tools import UV_INDEX_FLAG
from interlocks.runner import (
    RESET,
    RunResult,
    Task,
    _c,
    _clean_display_args,
    _default_display,
    _display_head_and_rest,
    _glyph,
    _has_changed_flag,
    _is_python_module_invocation,
    _json_progress_command,
    _merged_env,
    _parse_test_summary,
    _preflight_error_payload,
    _print_parallel_json_start_statuses,
    _status,
    _truncate_dump,
    arg_flag_value,
    arg_value,
    dump_and_exit,
    record_result,
    record_skip,
    reset_results,
    stage_json,
    subcommand_args,
    uvx_tool,
)


@st.composite
def durations(draw: Any) -> str:
    seconds = draw(st.integers(min_value=0, max_value=10_000))
    if draw(st.booleans()):
        return str(seconds)
    fraction = draw(st.integers(min_value=0, max_value=999))
    return f"{seconds}.{fraction:03d}"


@given(count=st.integers(min_value=0, max_value=1_000_000), duration=durations())
def test_unittest_summary_preserves_count_duration_and_plurality(
    count: int,
    duration: str,
) -> None:
    noun = "test" if count == 1 else "tests"
    output = f"noise\nRan {count} {noun} in {duration}s\nOK\n"

    assert _parse_test_summary(output) == f"{count} {noun} in {duration}s"


@given(
    count=st.integers(min_value=0, max_value=1_000_000),
    warnings=st.integers(min_value=0, max_value=1_000),
    duration=durations(),
)
def test_pytest_summary_preserves_count_and_duration(
    count: int,
    warnings: int,
    duration: str,
) -> None:
    output = f"{count} passed, {warnings} warnings in {duration}s\n"

    assert _parse_test_summary(output) == f"{count} passed in {duration}s"


@given(st.text(max_size=1_000))
def test_test_summary_parser_never_raises(raw: str) -> None:
    summary = _parse_test_summary(raw)

    assert isinstance(summary, str)


@given(
    flag=st.from_regex(r"--[a-z][a-z0-9-]{0,20}", fullmatch=True),
    default=st.text(max_size=20),
    value=st.text(max_size=20),
)
def test_arg_flag_value_uses_first_matching_bare_or_value(
    flag: str,
    default: str,
    value: str,
) -> None:
    old_argv = sys.argv
    try:
        sys.argv = ["interlocks", "positional", flag, f"{flag}={value or 'later'}"]
        assert arg_flag_value(flag, default) == default

        sys.argv = ["interlocks", "positional", f"{flag}={value}", flag]
        assert arg_flag_value(flag, default) == (value or default)
    finally:
        sys.argv = old_argv


_ARGV_TOKEN = st.text(max_size=20)
_CHANGED_ARG = st.one_of(
    st.just("--changed"),
    st.builds(lambda value: f"--changed={value}", st.text(max_size=20)),
)
_NOT_CHANGED_ARG = st.text(max_size=20).filter(
    lambda arg: arg != "--changed" and not arg.startswith("--changed=")
)
_DISPLAY_TOKEN = st.text(
    alphabet=string.ascii_letters + string.digits + "_./:=,- \n\t",
    min_size=1,
    max_size=30,
)
_CONFIG_PATH_FLAGS = ("--config", "--project", "--rcfile")
_INLINE_CONFIG_FLAG_MARKERS = tuple(f"{flag}=" for flag in _CONFIG_PATH_FLAGS)
_BENIGN_DISPLAY_TOKEN = _DISPLAY_TOKEN.filter(
    lambda arg: (
        arg not in _CONFIG_PATH_FLAGS
        and not any(marker in arg for marker in _INLINE_CONFIG_FLAG_MARKERS)
    )
)
_DUMP_LINE = st.text(
    alphabet=st.characters(blacklist_characters="\r\n"),
    max_size=40,
)


@given(
    flag=st.from_regex(r"--[a-z][a-z0-9-]{0,20}", fullmatch=True),
    default=st.text(max_size=20),
    args=st.lists(_ARGV_TOKEN, max_size=12),
)
def test_arg_flag_value_returns_none_when_flag_absent(
    flag: str,
    default: str,
    args: list[str],
) -> None:
    absent_args = [arg for arg in args if arg != flag and not arg.startswith(f"{flag}=")]
    old_argv = sys.argv
    try:
        sys.argv = ["interlocks", *absent_args]
        assert arg_flag_value(flag, default) is None
    finally:
        sys.argv = old_argv


def _captured_dump_and_exit(
    rc: int, stdout: str | None, stderr: str | None
) -> tuple[int | str | None, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            dump_and_exit(rc, stdout, stderr)
        except SystemExit as exc:
            return exc.code, buf.getvalue()
    raise AssertionError("dump_and_exit returned")


@given(
    rc=st.integers(min_value=-5, max_value=300),
    stdout=st.one_of(st.none(), st.text(max_size=40)),
    stderr=st.one_of(st.none(), st.text(max_size=40)),
)
def test_dump_and_exit_prints_exact_combined_output_before_exit(
    rc: int,
    stdout: str | None,
    stderr: str | None,
) -> None:
    output = (stdout or "") + (stderr or "")
    expected = output if not output or output.endswith("\n") else f"{output}\n"

    code, printed = _captured_dump_and_exit(rc, stdout, stderr)

    assert code == rc
    assert printed == expected


@given(lines=st.lists(_DUMP_LINE, max_size=20))
def test_truncate_dump_preserves_short_outputs(lines: list[str]) -> None:
    text = "".join(f"{line}\n" for line in lines)
    old = os.environ.pop("INTERLOCK_DUMP_LINES", None)
    try:
        assert _truncate_dump(text) == text
    finally:
        if old is not None:
            os.environ["INTERLOCK_DUMP_LINES"] = old


@given(line_count=st.integers(min_value=61, max_value=120))
def test_truncate_dump_keeps_head_tail_and_reports_omitted_count(line_count: int) -> None:
    text = "".join(f"line {index}\n" for index in range(line_count))
    old = os.environ.pop("INTERLOCK_DUMP_LINES", None)
    try:
        truncated = _truncate_dump(text)
    finally:
        if old is not None:
            os.environ["INTERLOCK_DUMP_LINES"] = old

    assert "line 0\n" in truncated
    assert f"line {line_count - 1}\n" in truncated
    assert f"{line_count - 60} lines omitted" in truncated
    assert "line 40\n" not in truncated


@given(text=st.text(max_size=2_000))
def test_truncate_dump_all_env_bypasses_truncation(text: str) -> None:
    old = os.environ.get("INTERLOCK_DUMP_LINES")
    os.environ["INTERLOCK_DUMP_LINES"] = "all"
    try:
        assert _truncate_dump(text) == text
    finally:
        if old is None:
            os.environ.pop("INTERLOCK_DUMP_LINES", None)
        else:
            os.environ["INTERLOCK_DUMP_LINES"] = old


@given(
    char=st.text(max_size=5),
    color=st.text(max_size=10),
    use_color=st.booleans(),
)
def test_glyph_and_color_helpers_honor_use_color(
    char: str,
    color: str,
    use_color: bool,
) -> None:
    original = runner_mod.ui.use_color
    runner_mod.ui.use_color = lambda: use_color  # type: ignore[assignment]
    try:
        assert _glyph(char, color) == (f"{color}{char}{RESET}" if use_color else char)
        assert _c(color) == (color if use_color else "")
    finally:
        runner_mod.ui.use_color = original


@given(char=st.text(max_size=5), color=st.text(max_size=10))
def test_glyph_and_color_helpers_strip_color_when_color_disabled(char: str, color: str) -> None:
    original = runner_mod.ui.use_color
    runner_mod.ui.use_color = lambda: False  # type: ignore[assignment]
    try:
        assert _glyph(char, color) == char
        assert not _c(color)
    finally:
        runner_mod.ui.use_color = original


@given(
    flag_name=st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True),
    default=st.text(max_size=20),
    value=st.text(max_size=20),
    prefix=st.lists(_ARGV_TOKEN, max_size=8),
)
def test_arg_value_uses_first_matching_value_flag(
    flag_name: str,
    default: str,
    value: str,
    prefix: list[str],
) -> None:
    flag = f"--{flag_name}="
    prefix = [arg for arg in prefix if not arg.startswith(flag)]
    old_argv = sys.argv
    try:
        sys.argv = ["interlocks", *prefix]
        assert arg_value(flag, default) == default

        sys.argv = ["interlocks", *prefix, f"{flag}{value}", f"{flag}later"]
        assert arg_value(flag, default) == value
    finally:
        sys.argv = old_argv


@given(
    prefix=st.lists(_NOT_CHANGED_ARG, max_size=8),
    changed_arg=_CHANGED_ARG,
    suffix=st.lists(_NOT_CHANGED_ARG, max_size=8),
)
def test_has_changed_flag_detects_declared_flag_anywhere(
    prefix: list[str],
    changed_arg: str,
    suffix: list[str],
) -> None:
    old_argv = sys.argv
    try:
        sys.argv = ["interlocks", *prefix, changed_arg, *suffix]
        assert _has_changed_flag()
    finally:
        sys.argv = old_argv


@given(argv=st.lists(_NOT_CHANGED_ARG, max_size=20))
def test_has_changed_flag_ignores_other_tokens(argv: list[str]) -> None:
    old_argv = sys.argv
    try:
        sys.argv = ["interlocks", *argv]
        assert not _has_changed_flag()
    finally:
        sys.argv = old_argv


@given(
    name=st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True),
    prefix=st.lists(_ARGV_TOKEN, max_size=8),
    suffix=st.lists(_ARGV_TOKEN, max_size=12),
)
def test_subcommand_args_returns_args_after_named_command_without_global_verbosity(
    name: str,
    prefix: list[str],
    suffix: list[str],
) -> None:
    prefix = [arg for arg in prefix if arg != name]
    old_argv = sys.argv
    try:
        sys.argv = ["interlocks", *prefix, name, *suffix]
        assert subcommand_args(name) == [
            arg for arg in suffix if arg not in {"--quiet", "--verbose"}
        ]
    finally:
        sys.argv = old_argv


@given(
    name=st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True),
    argv=st.lists(_ARGV_TOKEN, max_size=20),
)
def test_subcommand_args_returns_empty_when_command_absent(name: str, argv: list[str]) -> None:
    old_argv = sys.argv
    try:
        sys.argv = ["interlocks", *(arg for arg in argv if arg != name)]
        assert subcommand_args(name) == []
    finally:
        sys.argv = old_argv


@given(
    name=st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True),
    tail=st.lists(_ARGV_TOKEN, max_size=8),
)
def test_subcommand_args_uses_first_named_command(name: str, tail: list[str]) -> None:
    old_argv = sys.argv
    try:
        sys.argv = ["interlocks", name, "--quiet", name, *tail]
        assert subcommand_args(name) == [name, *tail]
    finally:
        sys.argv = old_argv


@given(
    command=st.text(min_size=1, max_size=20),
    passed=st.booleans(),
    elapsed=st.floats(min_value=0, max_value=10_000, allow_nan=False),
    label=st.text(min_size=1, max_size=20),
    status=st.sampled_from(["ok", "warn", "fail"]),
    detail=st.one_of(st.none(), st.text(max_size=30)),
    skip_reason=st.text(min_size=1, max_size=30),
    skip_action=st.one_of(st.none(), st.text(min_size=1, max_size=30)),
    evidence_path=st.one_of(st.none(), st.text(max_size=30)),
)
def test_stage_json_uses_plain_json_shapes(
    command: str,
    passed: bool,
    elapsed: float,
    label: str,
    status: str,
    detail: str | None,
    skip_reason: str,
    skip_action: str | None,
    evidence_path: str | None,
) -> None:
    reset_results()
    try:
        record_result(label, status=status, elapsed=elapsed, detail=detail)  # type: ignore[arg-type]
        record_skip("skipped-gate", skip_reason, next_action=skip_action)

        payload = stage_json(command, passed=passed, elapsed=elapsed, evidence_path=evidence_path)
    finally:
        reset_results()

    expected_gate = {
        "name": label,
        "status": status,
        "elapsed_seconds": round(elapsed, 3),
    }
    if detail is not None:
        expected_gate["detail"] = detail
    expected_skip = {"name": "skipped-gate", "reason": skip_reason}
    if skip_action is not None:
        expected_skip["next_action"] = skip_action
    assert payload["command"] == command
    assert payload["passed"] is passed
    assert payload["elapsed_seconds"] == round(elapsed, 3)
    assert payload["gates"] == [expected_gate]
    assert payload["skipped"] == [expected_skip]
    assert ("evidence_path" in payload) is (evidence_path is not None)


@given(command=st.text(max_size=30), passed=st.booleans(), elapsed=st.floats(allow_nan=False))
def test_stage_json_handles_empty_gate_accumulators(
    command: str,
    passed: bool,
    elapsed: float,
) -> None:
    reset_results()

    payload = stage_json(command, passed=passed, elapsed=elapsed)

    assert payload == {
        "command": command,
        "passed": passed,
        "elapsed_seconds": round(elapsed, 3),
        "gates": [],
        "skipped": [],
    }


@given(
    command=st.text(max_size=30),
    passed=st.booleans(),
    elapsed=st.floats(allow_nan=False),
)
def test_stage_json_omits_evidence_path_only_for_none(
    command: str,
    passed: bool,
    elapsed: float,
) -> None:
    reset_results()

    without_evidence = stage_json(command, passed=passed, elapsed=elapsed)
    with_empty_evidence = stage_json(command, passed=passed, elapsed=elapsed, evidence_path="")

    assert "evidence_path" not in without_evidence
    assert not with_empty_evidence["evidence_path"]


@given(command=st.text(min_size=1, max_size=30), error=st.text(min_size=1, max_size=120))
def test_preflight_error_payload_keeps_json_error_contract(command: str, error: str) -> None:
    payload = _preflight_error_payload(command, error)

    assert payload["command"] == command
    assert payload["passed"] is False
    assert payload["error"] == error
    assert (
        payload["next_action"]
        == "Run `interlocks init` for a new project, or invoke from a Python project root."
    )


@given(head=_DISPLAY_TOKEN, rest=st.lists(_DISPLAY_TOKEN, max_size=8))
def test_default_display_is_single_line_and_hides_config_paths(head: str, rest: list[str]) -> None:
    cmd = [
        head,
        "--config=/workspace/interlocks.toml",
        "--project=/workspace/project",
        "--rcfile=/workspace/ruff.toml",
        "--config",
        "/workspace/split-interlocks.toml",
        "--project",
        "/workspace/split-project",
        "--rcfile",
        "/workspace/split-ruff.toml",
        *rest,
    ]

    display = _default_display(cmd)

    assert "\n" not in display
    assert "\t" not in display
    assert "--config=" not in display
    assert "--project=" not in display
    assert "--rcfile=" not in display
    assert "/workspace/interlocks.toml" not in display
    assert "/workspace/project" not in display
    assert "/workspace/ruff.toml" not in display
    assert "/workspace/split-interlocks.toml" not in display
    assert "/workspace/split-project" not in display
    assert "/workspace/split-ruff.toml" not in display


def test_default_display_returns_empty_string_for_empty_command() -> None:
    assert not _default_display([])


@given(
    prefix=st.lists(_DISPLAY_TOKEN, max_size=8),
    flag=st.sampled_from(_CONFIG_PATH_FLAGS),
    suffix=st.lists(_DISPLAY_TOKEN, max_size=8),
)
def test_clean_display_args_removes_config_path_flags(
    prefix: list[str],
    flag: str,
    suffix: list[str],
) -> None:
    split_path = "__CONFIG_PATH_SENTINEL_LONGER_THAN_DISPLAY_TOKEN__"
    inline_path = "__INLINE_CONFIG_PATH_SENTINEL_LONGER_THAN_DISPLAY_TOKEN__"

    cleaned = _clean_display_args([
        *prefix,
        flag,
        split_path,
        f"{flag}={inline_path}",
        *suffix,
    ])

    assert flag not in cleaned
    assert split_path not in cleaned
    assert inline_path not in " ".join(cleaned)
    assert not any(marker in arg for marker in _INLINE_CONFIG_FLAG_MARKERS for arg in cleaned)


@given(args=st.lists(_BENIGN_DISPLAY_TOKEN, max_size=16))
def test_clean_display_args_preserves_benign_args(args: list[str]) -> None:
    assert _clean_display_args(args) == args


@given(
    prefix=st.lists(_BENIGN_DISPLAY_TOKEN, max_size=8), flag=st.sampled_from(_CONFIG_PATH_FLAGS)
)
def test_clean_display_args_removes_dangling_config_path_flag(
    prefix: list[str],
    flag: str,
) -> None:
    assert _clean_display_args([*prefix, flag]) == prefix


@given(
    module=st.from_regex(r"[A-Za-z_][A-Za-z0-9_.]{0,30}", fullmatch=True),
    tail=st.lists(_DISPLAY_TOKEN, max_size=8),
)
def test_display_head_collapses_python_module_invocations(module: str, tail: list[str]) -> None:
    cmd = [sys.executable, "-m", module, *tail]

    assert _is_python_module_invocation(Path(sys.executable).name, cmd)
    assert _display_head_and_rest(cmd) == (f"python -m {module}", tail)


@given(head=_DISPLAY_TOKEN, cmd=st.lists(_DISPLAY_TOKEN, max_size=2))
def test_is_python_module_invocation_requires_python_m_and_module(
    head: str,
    cmd: list[str],
) -> None:
    assert _is_python_module_invocation(head, cmd) is False


@given(
    head=st.text(
        alphabet=string.ascii_letters + string.digits + "_.-",
        min_size=1,
        max_size=20,
    ).filter(lambda value: value not in {"python", "python3", Path(sys.executable).name, "."}),
    tail=st.lists(_DISPLAY_TOKEN, max_size=8),
)
def test_display_head_uses_basename_for_non_python_commands(head: str, tail: list[str]) -> None:
    cmd = [f"/workspace/tools/{head}", *tail]

    assert _display_head_and_rest(cmd) == (head, tail)


@given(
    head=st.text(
        alphabet=string.ascii_letters + string.digits + "_.-",
        min_size=1,
        max_size=20,
    ).filter(lambda value: value not in {"python", "python3", Path(sys.executable).name, "."})
)
def test_display_head_handles_single_non_python_command(head: str) -> None:
    assert _display_head_and_rest([f"/workspace/tools/{head}"]) == (head, [])


@given(
    package=st.text(min_size=1, max_size=20),
    version=st.text(min_size=1, max_size=20),
    args=st.lists(_ARGV_TOKEN, max_size=8),
    entrypoint=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
)
def test_uvx_tool_builds_isolated_tool_invocation(
    package: str,
    version: str,
    args: list[str],
    entrypoint: str | None,
) -> None:
    cmd = uvx_tool(package, *args, version=version, entrypoint=entrypoint)
    script_index = 3 + len(UV_INDEX_FLAG)

    assert cmd[:3] == ["uvx", "--from", f"{package}=={version}"]
    assert tuple(cmd[3:script_index]) == UV_INDEX_FLAG
    assert cmd[script_index] == (entrypoint or package)
    assert cmd[script_index + 1 :] == args


@given(package=st.text(min_size=1, max_size=20), version=st.text(min_size=1, max_size=20))
def test_uvx_tool_uses_package_as_default_entrypoint(package: str, version: str) -> None:
    cmd = uvx_tool(package, version=version)
    script_index = 3 + len(UV_INDEX_FLAG)

    assert cmd[script_index] == package


@given(
    env=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=12).filter(lambda key: "=" not in key),
            st.text(max_size=20),
        ),
        max_size=20,
    )
)
def test_merged_env_preserves_process_env_and_last_override_wins(
    env: list[tuple[str, str]],
) -> None:
    merged = _merged_env(tuple(env))

    if not env:
        assert merged is None
        return

    assert merged is not None
    for key, value in os.environ.items():
        if key not in dict(env):
            assert merged[key] == value
    for key, value in dict(env).items():
        assert merged[key] == value


@given(key=st.text(min_size=1, max_size=12).filter(lambda value: "=" not in value))
def test_merged_env_single_override_does_not_mutate_process_env(key: str) -> None:
    before = dict(os.environ)

    merged = _merged_env(((key, "generated"),))

    assert os.environ == before
    assert merged is not None
    assert merged[key] == "generated"


def test_merged_env_empty_env_avoids_process_env_copy() -> None:
    assert _merged_env(()) is None


@given(
    returncode=st.integers(min_value=0, max_value=5),
    elapsed=st.floats(min_value=0, max_value=100, allow_nan=False),
)
def test_status_marks_disallowed_return_codes_as_fail(returncode: int, elapsed: float) -> None:
    result = RunResult(
        Task("Sample", ["sample"], allowed_rcs=(0, 2)),
        returncode,
        "",
        "",
        elapsed,
    )

    status, detail, state = _status(result, elapsed_suffix=True)

    if returncode in (0, 2):
        assert status == "ok"
        assert detail == f"{elapsed:.1f}s"
        assert state == "ok"
    else:
        assert status == "failed"
        assert detail is None
        assert state == "fail"


@given(count=st.integers(min_value=0, max_value=1000), duration=durations())
def test_status_prefers_test_summary_over_elapsed_detail(count: int, duration: str) -> None:
    noun = "test" if count == 1 else "tests"
    output = f"Ran {count} {noun} in {duration}s\n"
    result = RunResult(
        Task("Tests", ["pytest"], test_summary=True),
        0,
        output,
        "",
        12.3,
    )

    assert _status(result, elapsed_suffix=True) == (
        f"{count} {noun} in {duration}s",
        None,
        "ok",
    )


@given(returncode=st.sampled_from([0, 2]))
def test_status_without_elapsed_suffix_has_no_detail(returncode: int) -> None:
    result = RunResult(
        Task("Sample", ["sample"], allowed_rcs=(0, 2)),
        returncode,
        "",
        "",
        12.3,
    )

    assert _status(result, elapsed_suffix=False) == ("ok", None, "ok")


@given(st.lists(st.booleans(), max_size=8))
def test_parallel_json_start_statuses_emit_only_declared_running_tasks(
    start_flags: list[bool],
) -> None:
    tasks = [
        Task(
            f"Task {index}",
            ["noop"],
            label=f"task{index}",
            display=f"cmd{index}",
            start_status="running" if enabled else None,
        )
        for index, enabled in enumerate(start_flags)
    ]
    original = sys.argv
    err = io.StringIO()
    sys.argv = ["interlocks", "ci", "--json"]
    try:
        with redirect_stderr(err):
            _print_parallel_json_start_statuses(tasks)
    finally:
        sys.argv = original

    assert err.getvalue().splitlines() == [
        f"interlocks: [task{index}] cmd{index} running"
        for index, enabled in enumerate(start_flags)
        if enabled
    ]


@given(
    tasks=st.lists(
        st.builds(lambda label: Task(label, ["noop"], label=label), _DISPLAY_TOKEN), max_size=5
    )
)
def test_parallel_json_start_statuses_are_silent_outside_json_mode(tasks: list[Task]) -> None:
    original = sys.argv
    err = io.StringIO()
    sys.argv = ["interlocks", "ci"]
    try:
        with redirect_stderr(err):
            _print_parallel_json_start_statuses(tasks)
    finally:
        sys.argv = original

    assert not err.getvalue()


@given(st.text(max_size=300))
def test_json_progress_command_is_bounded(command: str) -> None:
    progress = _json_progress_command(command)

    assert len(progress) <= 96
    if len(command) <= 96:
        assert progress == command
    else:
        assert progress.endswith("…")


def test_json_progress_command_truncates_at_exact_display_boundary() -> None:
    command = "x" * 97

    assert _json_progress_command(command) == ("x" * 95) + "…"
