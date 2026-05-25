"""Generated-input checks for setup-skill JSON helpers."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.setup_skill import (
    SkillInstallResult,
    _project_relative,
    _setup_skill_payload,
)

_REL_PATH = st.from_regex(
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}){0,2}",
    fullmatch=True,
)
_ACTION = st.sampled_from(["installed", "updated", "kept"])


@given(relpath=_REL_PATH)
def test_project_relative_prefers_paths_under_root(relpath: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        path = root / relpath

        assert _project_relative(root, path) == relpath


@given(relpath=_REL_PATH, action=_ACTION)
def test_setup_skill_payload_marks_stale_when_detector_fails(
    relpath: str,
    action: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        result = SkillInstallResult(path=root / relpath, action=action, installed=True)

        payload = _setup_skill_payload(root, result)

    assert payload["command"] == "setup-skill"
    assert payload["passed"] is True
    assert payload["status"] == "missing/stale"
    assert payload["installed"] is False
    assert payload["path"] == relpath
    assert payload["action"] == action
    next_actions = payload["next_actions"]
    assert isinstance(next_actions, list)
    assert next_actions
