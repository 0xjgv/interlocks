"""Generated-input checks for setup JSON helpers."""

from __future__ import annotations

import sys

from hypothesis import given
from hypothesis import strategies as st

from interlocks.setup_state import SETUP_ARTIFACTS, SetupArtifactStatus
from interlocks.tasks.setup import _check_payload, _parse_args, _setup_payload

_ARTIFACTS = SETUP_ARTIFACTS[:4]


def _statuses(values: tuple[bool, bool, bool, bool]) -> list[SetupArtifactStatus]:
    return [
        SetupArtifactStatus(artifact, installed)
        for artifact, installed in zip(_ARTIFACTS, values, strict=True)
    ]


@given(installed=st.tuples(st.booleans(), st.booleans(), st.booleans(), st.booleans()))
def test_setup_payload_projects_artifact_statuses(
    installed: tuple[bool, bool, bool, bool],
) -> None:
    statuses = _statuses(installed)
    payload = _setup_payload(
        mode="local",
        check_only=False,
        statuses=statuses,
        next_actions=["next"],
    )

    passed = all(installed)
    assert payload["command"] == "setup"
    assert payload["mode"] == "local"
    assert payload["check"] is False
    assert payload["passed"] is passed
    assert payload["status"] == ("installed" if passed else "missing/stale")
    assert payload["next_actions"] == ["next"]
    assert payload["artifacts"] == [
        {
            "label": artifact.label,
            "target": artifact.target,
            "installed": value,
            "status": "installed" if value else "missing/stale",
        }
        for artifact, value in zip(_ARTIFACTS, installed, strict=True)
    ]


@given(installed=st.tuples(st.booleans(), st.booleans(), st.booleans(), st.booleans()))
def test_check_payload_includes_fix_action_only_when_missing(
    installed: tuple[bool, bool, bool, bool],
) -> None:
    payload = _check_payload(
        mode="local",
        statuses=_statuses(installed),
        fix_message="fix it",
        extra_lines=["consider progressive"],
    )

    if all(installed):
        assert payload["next_actions"] == ["consider progressive"]
    else:
        assert payload["next_actions"] == ["fix it", "consider progressive"]


@given(check=st.booleans(), ci=st.booleans(), json_mode=st.booleans(), verbose=st.booleans())
def test_parse_args_accepts_supported_setup_flags(
    check: bool,
    ci: bool,
    json_mode: bool,
    verbose: bool,
) -> None:
    original = sys.argv
    flags = [
        *(["--check"] if check else []),
        *(["--ci=github"] if ci else []),
        *(["--json"] if json_mode else []),
        *(["--verbose"] if verbose else []),
    ]
    sys.argv = ["interlocks", "setup", *flags]
    try:
        args = _parse_args()
    finally:
        sys.argv = original

    assert args.check_only is check
    assert args.ci == ("github" if ci else None)
