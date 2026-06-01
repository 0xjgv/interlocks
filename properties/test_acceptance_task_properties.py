"""Property tests for acceptance task command construction."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.acceptance_status import AcceptanceStatus
from interlocks.behavior_attribution_trace import PLUGIN_NAME
from interlocks.tasks.acceptance import (
    _acceptance_failure_payload,
    _acceptance_skip_payload,
    _inject_pytest_plugin,
    _loads_pytest_plugin,
)

_ARG = st.from_regex(r"[A-Za-z0-9_./:=,-]{1,30}", fullmatch=True).filter(
    lambda value: (
        value
        not in {
            "pytest",
            "-p",
            PLUGIN_NAME,
            f"-p{PLUGIN_NAME}",
        }
    )
)
_ARGS = st.lists(_ARG, max_size=8)
_PLUGIN_ARG = st.one_of(
    _ARG,
    st.sampled_from(["-p", PLUGIN_NAME, f"-p{PLUGIN_NAME}", f"-p{PLUGIN_NAME}.extra"]),
)
_ACCEPTANCE_STATUS = st.sampled_from(list(AcceptanceStatus))


@given(prefix=_ARGS, suffix=_ARGS)
def test_inject_pytest_plugin_inserts_after_pytest(prefix: list[str], suffix: list[str]) -> None:
    cmd = [*prefix, "pytest", *suffix]

    injected = _inject_pytest_plugin(cmd)

    assert injected == [*prefix, "pytest", "-p", PLUGIN_NAME, *suffix]


@given(prefix=_ARGS, suffix=_ARGS)
def test_inject_pytest_plugin_is_idempotent_for_split_plugin_arg(
    prefix: list[str], suffix: list[str]
) -> None:
    cmd = [*prefix, "pytest", "-p", PLUGIN_NAME, *suffix]

    assert _inject_pytest_plugin(cmd) == cmd


@given(prefix=_ARGS, suffix=_ARGS)
def test_inject_pytest_plugin_is_idempotent_for_compact_plugin_arg(
    prefix: list[str], suffix: list[str]
) -> None:
    cmd = [*prefix, "pytest", f"-p{PLUGIN_NAME}", *suffix]

    assert _inject_pytest_plugin(cmd) == cmd


@given(args=st.lists(_PLUGIN_ARG, max_size=12))
def test_loads_pytest_plugin_accepts_only_real_pytest_plugin_loads(args: list[str]) -> None:
    expected = False
    for index, arg in enumerate(args):
        expected = expected or arg == f"-p{PLUGIN_NAME}"
        expected = expected or (
            arg == "-p" and index + 1 < len(args) and args[index + 1] == PLUGIN_NAME
        )

    assert _loads_pytest_plugin(args) is expected


@given(suffix=_ARGS)
def test_loads_pytest_plugin_rejects_dangling_plugin_flag(suffix: list[str]) -> None:
    assert _loads_pytest_plugin([*suffix, "-p"]) is False


@given(prefix=_ARGS, suffix=_ARGS)
def test_plugin_name_as_plain_pytest_arg_does_not_block_injection(
    prefix: list[str], suffix: list[str]
) -> None:
    cmd = [*prefix, "pytest", *suffix, PLUGIN_NAME]

    injected = _inject_pytest_plugin(cmd)

    assert injected == [*prefix, "pytest", "-p", PLUGIN_NAME, *suffix, PLUGIN_NAME]


@given(cmd=_ARGS)
def test_non_pytest_command_is_unchanged(cmd: list[str]) -> None:
    assert _inject_pytest_plugin(cmd) == cmd


@given(
    status=_ACCEPTANCE_STATUS,
    reason=st.text(max_size=100),
    next_actions=st.lists(st.text(max_size=100), max_size=4),
)
def test_acceptance_skip_payload_preserves_status_reason_and_actions(
    status: AcceptanceStatus,
    reason: str,
    next_actions: list[str],
) -> None:
    payload = _acceptance_skip_payload(status, reason=reason, next_actions=next_actions)

    assert payload == {
        "command": "acceptance",
        "passed": True,
        "status": "skipped",
        "acceptance_status": status.value,
        "reason": reason,
        "next_actions": next_actions,
    }


@given(
    status=st.sampled_from([
        AcceptanceStatus.MISSING_FEATURES_DIR,
        AcceptanceStatus.MISSING_FEATURE_FILES,
        AcceptanceStatus.MISSING_SCENARIOS,
        AcceptanceStatus.MISSING_BEHAVIOR_COVERAGE,
    ]),
    message=st.text(max_size=100),
)
def test_acceptance_failure_payload_is_actionable(status: AcceptanceStatus, message: str) -> None:
    payload = _acceptance_failure_payload(status, message)

    assert payload["command"] == "acceptance"
    assert payload["passed"] is False
    assert payload["acceptance_status"] == status.value
    assert payload["error"] == message
    assert isinstance(payload["next_actions"], list)
    assert payload["next_actions"]
