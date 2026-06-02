"""Generated-input checks for CRAP JSON helpers."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from hypothesis import given
from hypothesis import strategies as st

from interlocks.metrics import CrapRow
from interlocks.tasks.crap import (
    _CRAP_JSON_OFFENDER_LIMIT,
    _crap_context,
    _crap_offender_payload,
    _crap_payload,
    _crap_status,
    _CrapContext,
    _CrapPayloadState,
)

if TYPE_CHECKING:
    from interlocks.config import InterlockConfig

_FINITE_FLOAT = st.floats(allow_nan=False, allow_infinity=False, width=32)
_SMALL_FLOAT = st.floats(
    min_value=0.0,
    max_value=1_000.0,
    allow_nan=False,
    allow_infinity=False,
    width=32,
)
_COUNT = st.integers(min_value=0, max_value=10_000)
_ROW = st.builds(
    CrapRow,
    path=st.text(max_size=40),
    name=st.text(max_size=40),
    start=st.integers(min_value=1, max_value=10_000),
    end=st.integers(min_value=1, max_value=10_000),
    ccn=st.integers(min_value=1, max_value=1_000),
    loc=st.integers(min_value=1, max_value=10_000),
    coverage=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    crap=st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
)


@given(
    max_crap=_SMALL_FLOAT,
    enforce_crap=st.booleans(),
    emit_json=st.booleans(),
    json_flag=st.booleans(),
    changed_only=st.booleans(),
)
def test_crap_context_projects_config_and_argv(
    max_crap: float,
    enforce_crap: bool,
    emit_json: bool,
    json_flag: bool,
    changed_only: bool,
) -> None:
    argv = ["interlocks", "gate", "crap", f"--max={max_crap}"]
    if json_flag:
        argv.append("--json")
    if changed_only:
        argv.append("--changed-only")
    cfg = cast(
        "InterlockConfig",
        SimpleNamespace(crap_max=30.0, enforce_crap=enforce_crap),
    )

    original_argv = sys.argv
    try:
        sys.argv = argv
        context = _crap_context(cfg, emit_json=emit_json)
    finally:
        sys.argv = original_argv

    assert context.max_crap == max_crap
    assert context.enforce_crap is enforce_crap
    assert context.changed_only is changed_only
    assert context.json_mode is (json_flag and emit_json)
    assert context.command == f"CRAP --max={max_crap}"


@given(max_crap=_SMALL_FLOAT, enforce_crap=st.booleans(), emit_json=st.booleans())
def test_crap_context_uses_configured_threshold_without_cli_override(
    max_crap: float,
    enforce_crap: bool,
    emit_json: bool,
) -> None:
    cfg = cast(
        "InterlockConfig",
        SimpleNamespace(crap_max=max_crap, enforce_crap=enforce_crap),
    )

    original_argv = sys.argv
    try:
        sys.argv = ["interlocks", "gate", "crap"]
        context = _crap_context(cfg, emit_json=emit_json)
    finally:
        sys.argv = original_argv

    assert context.max_crap == max_crap
    assert context.command == f"CRAP --max={max_crap}"


@given(row=_ROW)
def test_crap_offender_payload_projects_row_fields(row: CrapRow) -> None:
    payload = _crap_offender_payload(row)

    assert payload == {
        "path": row.path,
        "name": row.name,
        "start": row.start,
        "end": row.end,
        "ccn": row.ccn,
        "loc": row.loc,
        "coverage": round(row.coverage, 4),
        "crap": round(row.crap, 3),
    }


@given(offender_count=_COUNT, enforce_crap=st.booleans())
def test_crap_status_matches_offender_count_and_enforcement(
    offender_count: int, enforce_crap: bool
) -> None:
    passed, status = _crap_status(offender_count, enforce_crap)

    if offender_count == 0:
        assert passed is True
        assert status == "ok"
    elif enforce_crap:
        assert passed is False
        assert status == "failed"
    else:
        assert passed is True
        assert status == "warn"


@given(
    offenders=st.lists(_ROW, max_size=_CRAP_JSON_OFFENDER_LIMIT + 10),
    function_count=_COUNT,
    elapsed=_FINITE_FLOAT,
    max_crap=_FINITE_FLOAT,
    enforce_crap=st.booleans(),
    changed_only=st.booleans(),
    reason=st.one_of(st.none(), st.text(max_size=40)),
    next_action=st.one_of(st.none(), st.text(max_size=40)),
)
def test_crap_payload_counts_and_truncates_offenders(
    offenders: list[CrapRow],
    function_count: int,
    elapsed: float,
    max_crap: float,
    enforce_crap: bool,
    changed_only: bool,
    reason: str | None,
    next_action: str | None,
) -> None:
    passed, status = _crap_status(len(offenders), enforce_crap)
    context = _CrapContext(
        max_crap=max_crap,
        enforce_crap=enforce_crap,
        changed_only=changed_only,
        json_mode=True,
        command=f"CRAP --max={max_crap}",
        start=0.0,
    )
    state = _CrapPayloadState(
        passed=passed,
        status=status,
        elapsed=elapsed,
        function_count=function_count,
        offenders=offenders,
        reason=reason,
        next_action=next_action,
    )

    payload = _crap_payload(context, state)

    assert payload["command"] == "crap"
    assert payload["passed"] is passed
    assert payload["status"] == status
    assert payload["elapsed_seconds"] == round(elapsed, 3)
    assert payload["max_crap"] == max_crap
    assert payload["enforce_crap"] is enforce_crap
    assert payload["changed_only"] is changed_only
    assert payload["function_count"] == function_count
    assert payload["offender_count"] == len(offenders)
    payload_offenders = payload["offenders"]
    assert isinstance(payload_offenders, list)
    assert len(payload_offenders) == min(len(offenders), _CRAP_JSON_OFFENDER_LIMIT)
    assert ("truncated_count" in payload) is (len(offenders) > _CRAP_JSON_OFFENDER_LIMIT)
    assert ("reason" in payload) is (reason is not None)
    assert ("next_action" in payload) is (next_action is not None)


@given(
    offenders=st.lists(_ROW, max_size=_CRAP_JSON_OFFENDER_LIMIT + 10),
    function_count=_COUNT,
    elapsed=_FINITE_FLOAT,
    max_crap=_FINITE_FLOAT,
    enforce_crap=st.booleans(),
    changed_only=st.booleans(),
    reason=st.one_of(st.none(), st.text(max_size=40)),
    next_action=st.one_of(st.none(), st.text(max_size=40)),
)
def test_crap_payload_has_stable_machine_keys(
    offenders: list[CrapRow],
    function_count: int,
    elapsed: float,
    max_crap: float,
    enforce_crap: bool,
    changed_only: bool,
    reason: str | None,
    next_action: str | None,
) -> None:
    passed, status = _crap_status(len(offenders), enforce_crap)
    payload = _crap_payload(
        _CrapContext(
            max_crap=max_crap,
            enforce_crap=enforce_crap,
            changed_only=changed_only,
            json_mode=True,
            command=f"CRAP --max={max_crap}",
            start=0.0,
        ),
        _CrapPayloadState(
            passed=passed,
            status=status,
            elapsed=elapsed,
            function_count=function_count,
            offenders=offenders,
            reason=reason,
            next_action=next_action,
        ),
    )

    expected = {
        "command",
        "passed",
        "status",
        "elapsed_seconds",
        "max_crap",
        "enforce_crap",
        "changed_only",
        "function_count",
        "offender_count",
        "offenders",
    }
    if len(offenders) > _CRAP_JSON_OFFENDER_LIMIT:
        expected.add("truncated_count")
    if reason is not None:
        expected.add("reason")
    if next_action is not None:
        expected.add("next_action")
    assert set(payload) == expected
