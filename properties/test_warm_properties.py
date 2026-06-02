"""Generated-input checks for warm JSON helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.defaults.tools import DEFAULTS
from interlocks.tasks.warm import (
    _WARM_OUTPUT_EXCERPT_MAX,
    _WARM_PROGRESS_COMMAND_MAX,
    _default_tool_specs,
    _warm_missing_uv_payload,
    _warm_output_excerpt,
    _warm_payload,
    _warm_probe_cmd,
    _warm_progress_command,
    _WarmOutcome,
)

_TOOL_SPEC = st.from_regex(r"[a-z][a-z0-9-]{0,20}==[0-9][0-9A-Za-z_.-]{0,20}", fullmatch=True)


@given(
    mode=st.sampled_from(["tools.txt", "uvx-probes"]),
    passed=st.booleans(),
    cached_tools=st.lists(_TOOL_SPEC, max_size=8),
    failed_tools=st.lists(_TOOL_SPEC, max_size=8),
    warning=st.text(max_size=80),
    error=st.text(max_size=80),
    output_excerpt=st.text(max_size=80),
)
def test_warm_payload_preserves_outcome_shape(
    mode: str,
    passed: bool,
    cached_tools: list[str],
    failed_tools: list[str],
    warning: str,
    error: str,
    output_excerpt: str,
) -> None:
    payload = _warm_payload(
        _WarmOutcome(
            mode=mode,
            passed=passed,
            cached_tools=tuple(cached_tools),
            failed_tools=tuple(failed_tools),
            warning=warning,
            error=error,
            output_excerpt=output_excerpt,
        )
    )

    assert payload["command"] == "warm"
    assert payload["passed"] is passed
    assert payload["status"] == ("ok" if passed else "failed")
    assert payload["mode"] == mode
    assert payload["tool_count"] == len(DEFAULTS)
    assert payload["tools"] == _default_tool_specs()
    assert payload["cached_tools"] == cached_tools
    assert payload["failed_tools"] == failed_tools
    if warning:
        assert payload["warnings"] == [warning]
    else:
        assert "warnings" not in payload
    if error:
        assert payload["error"] == error
    else:
        assert "error" not in payload
    if output_excerpt:
        assert payload["output_excerpt"] == output_excerpt
    else:
        assert "output_excerpt" not in payload


@given(
    mode=st.sampled_from(["tools.txt", "uvx-probes"]),
    passed=st.booleans(),
)
def test_warm_payload_next_action_tracks_passed_state(mode: str, passed: bool) -> None:
    payload = _warm_payload(
        _WarmOutcome(
            mode=mode,
            passed=passed,
            cached_tools=(),
            failed_tools=(),
        )
    )

    if passed:
        assert payload["next_actions"] == [
            "Run gates with `UV_OFFLINE=1` when you need offline execution."
        ]
    else:
        assert payload["next_actions"] == [
            "Fix the reported tool-cache failure, then rerun `interlocks warm --json`."
        ]


def test_warm_missing_uv_payload_marks_all_tools_failed() -> None:
    payload = _warm_missing_uv_payload()

    assert payload["command"] == "warm"
    assert payload["passed"] is False
    assert payload["status"] == "failed"
    assert payload["mode"] == "preflight"
    assert payload["tool_count"] == len(DEFAULTS)
    assert payload["tools"] == _default_tool_specs()
    assert payload["cached_tools"] == []
    assert payload["failed_tools"] == _default_tool_specs()
    next_actions = payload["next_actions"]
    assert isinstance(next_actions, list)
    assert "Install uv" in next_actions[0]


def test_warm_mutmut_probe_does_not_require_project_config() -> None:
    cmd = _warm_probe_cmd("interlocks-mutmut", "3.5.1")

    assert cmd[-3:] == ["python", "-c", "import mutmut"]


@given(name=st.sampled_from([name for name in DEFAULTS if name != "interlocks-mutmut"]))
def test_warm_non_mutmut_probe_uses_tool_help(name: str) -> None:
    cmd = _warm_probe_cmd(name, DEFAULTS[name])

    assert cmd[-1] == "--help"


@given(chunks=st.lists(st.text(max_size=300), max_size=5))
def test_warm_output_excerpt_is_bounded(chunks: list[str]) -> None:
    excerpt = _warm_output_excerpt(*chunks)

    assert len(excerpt) <= _WARM_OUTPUT_EXCERPT_MAX


@given(command=st.text(max_size=200))
def test_warm_progress_command_is_bounded(command: str) -> None:
    progress_command = _warm_progress_command(command)

    assert len(progress_command) <= _WARM_PROGRESS_COMMAND_MAX
    if len(command) <= _WARM_PROGRESS_COMMAND_MAX:
        assert progress_command == command


@given(command=st.text(min_size=_WARM_PROGRESS_COMMAND_MAX + 1, max_size=200))
def test_warm_progress_command_truncates_long_commands_with_ellipsis(command: str) -> None:
    assert _warm_progress_command(command) == (
        f"{command[: _WARM_PROGRESS_COMMAND_MAX - 1]}\u2026"
    )
