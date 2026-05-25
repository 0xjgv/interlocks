"""Generated-input checks for setup-hooks JSON helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.setup_state import SETUP_ARTIFACTS, SetupArtifactStatus
from interlocks.stages.setup_hooks import _setup_hooks_payload

_HOOK_ARTIFACTS = SETUP_ARTIFACTS[:2]


def _statuses(values: tuple[bool, bool]) -> list[SetupArtifactStatus]:
    return [
        SetupArtifactStatus(artifact, installed)
        for artifact, installed in zip(_HOOK_ARTIFACTS, values, strict=True)
    ]


@given(
    before=st.tuples(st.booleans(), st.booleans()),
    after=st.tuples(st.booleans(), st.booleans()),
)
def test_setup_hooks_payload_summarizes_detector_state(
    before: tuple[bool, bool],
    after: tuple[bool, bool],
) -> None:
    payload = _setup_hooks_payload(_statuses(before), _statuses(after))

    installed = all(after)
    assert payload["command"] == "setup-hooks"
    assert payload["passed"] is installed
    assert payload["status"] == ("installed" if installed else "missing/stale")
    assert payload["installed"] is installed
    assert payload["next_actions"] == [
        "Run `interlocks setup --check` to verify all local integrations."
    ]

    hooks = payload["hooks"]
    assert isinstance(hooks, list)
    assert len(hooks) == len(_HOOK_ARTIFACTS)
    for index, hook in enumerate(hooks):
        assert hook == {
            "label": _HOOK_ARTIFACTS[index].label,
            "target": _HOOK_ARTIFACTS[index].target,
            "action": "refreshed" if before[index] else "installed",
            "installed": after[index],
        }
