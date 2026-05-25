"""Generated-input checks for agent-doc JSON helpers."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.agents import (
    AgentDocResult,
    _agent_doc_entry,
    _project_relative,
)

_REL_PATH = st.from_regex(
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}){0,2}",
    fullmatch=True,
)
_ACTION = st.sampled_from(["created", "appended", "kept"])


@given(relpath=_REL_PATH)
def test_project_relative_prefers_paths_under_root(relpath: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        path = root / relpath

        assert _project_relative(root, path) == relpath


@given(relpath=_REL_PATH, action=_ACTION, registered=st.booleans())
def test_agent_doc_entry_uses_project_relative_path(
    relpath: str,
    action: str,
    registered: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        result = AgentDocResult(path=root / relpath, action=action, registered=registered)

        payload = _agent_doc_entry(root, result)

    assert payload == {
        "path": relpath,
        "action": action,
        "registered": registered,
    }
