"""Property tests for format task construction."""

from __future__ import annotations

from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks.runner import Task
from interlocks.tasks import format as format_task

_SEGMENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,10}", fullmatch=True)
_FILE = st.lists(_SEGMENT, min_size=1, max_size=4).map(lambda parts: "/".join(parts) + ".py")


@given(files=st.one_of(st.none(), st.lists(_FILE, max_size=8, unique=True)))
def test_task_format_delegates_to_shared_ruff_task_factory(files: list[str] | None) -> None:
    sentinel = Task("format", ("ruff", "format"))

    with patch.object(format_task, "make_ruff_task", return_value=sentinel) as make_ruff_task:
        result = format_task.task_format(files)

    assert result is sentinel
    make_ruff_task.assert_called_once_with("format", files)


@given(files=st.one_of(st.none(), st.lists(_FILE, max_size=8, unique=True)))
def test_task_format_uses_format_spec_name(files: list[str] | None) -> None:
    seen: list[tuple[str, list[str] | None]] = []

    def fake_make_ruff_task(name: str, received_files: list[str] | None) -> Task:
        seen.append((name, received_files))
        return Task(name, ["ruff", name], label=name)

    with patch.object(format_task, "make_ruff_task", side_effect=fake_make_ruff_task):
        result = format_task.task_format(files)

    assert seen == [("format", files)]
    assert result.description == "format"
    assert result.label == "format"
