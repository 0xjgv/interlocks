"""Property tests for fix task construction."""

from __future__ import annotations

from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks.runner import Task
from interlocks.tasks import fix as fix_task

_SEGMENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,10}", fullmatch=True)
_FILE = st.lists(_SEGMENT, min_size=1, max_size=4).map(lambda parts: "/".join(parts) + ".py")


@given(files=st.one_of(st.none(), st.lists(_FILE, max_size=8, unique=True)))
def test_task_fix_delegates_to_shared_ruff_task_factory(files: list[str] | None) -> None:
    sentinel = Task("fix", ["ruff", "check", "--fix"])

    with patch.object(fix_task, "make_ruff_task", return_value=sentinel) as make_ruff_task:
        result = fix_task.task_fix(files)

    assert result is sentinel
    make_ruff_task.assert_called_once_with("fix", files)
