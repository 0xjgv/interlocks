"""Generated-input checks for shared scaffold helpers."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.scaffold import (
    created_paths,
    ensure_bytes_file,
    ensure_text_file,
    next_actions_without_declared_dependency,
    scaffold_file,
    scaffold_status,
)


@given(actions=st.lists(st.sampled_from(("created", "kept")), max_size=8))
def test_scaffold_status_distinguishes_all_created(actions: list[str]) -> None:
    files = [scaffold_file(f"path-{index}", action) for index, action in enumerate(actions)]

    status = scaffold_status(files)

    assert status == ("created" if files and set(actions) == {"created"} else "scaffold-present")


@given(actions=st.lists(st.sampled_from(("created", "kept")), max_size=8))
def test_created_paths_returns_only_created_entries(actions: list[str]) -> None:
    files = [scaffold_file(f"path-{index}", action) for index, action in enumerate(actions)]

    assert created_paths(files) == [
        f"path-{index}" for index, action in enumerate(actions) if action == "created"
    ]


@given(actions=st.lists(st.text(max_size=20).filter(lambda value: value != "created"), max_size=8))
def test_created_paths_is_empty_without_created_actions(actions: list[str]) -> None:
    files = [scaffold_file(f"path-{index}", action) for index, action in enumerate(actions)]

    assert created_paths(files) == []


@given(declared=st.booleans())
def test_next_actions_without_declared_dependency_omits_declared_dependency(
    declared: bool,
) -> None:
    action = "Add `pytest-bdd>=8` to test/dev dependencies if it is missing."
    actions = (action, "Run `interlocks gate acceptance`.")
    pyproject = {"dependency-groups": {"dev": ["pytest_bdd>=8"]}} if declared else {}

    next_actions = next_actions_without_declared_dependency(
        pyproject,
        dependency="pytest-bdd",
        dependency_action=action,
        actions=actions,
    )

    assert next_actions == (("Run `interlocks gate acceptance`.",) if declared else actions)


@given(actions=st.lists(st.text(max_size=30), max_size=8).map(tuple))
def test_next_actions_without_declared_dependency_preserves_actions_when_missing(
    actions: tuple[str, ...],
) -> None:
    result = next_actions_without_declared_dependency(
        {},
        dependency="pytest-bdd",
        dependency_action="Add pytest-bdd.",
        actions=actions,
    )

    assert result is actions


@given(extra_actions=st.lists(st.text(max_size=30), max_size=8))
def test_next_actions_without_declared_dependency_removes_all_dependency_actions(
    extra_actions: list[str],
) -> None:
    action = "Add pytest-bdd."
    actions = (action, *extra_actions, action)

    result = next_actions_without_declared_dependency(
        {"dependency-groups": {"dev": ["pytest-bdd>=8"]}},
        dependency="pytest-bdd",
        dependency_action=action,
        actions=actions,
    )

    assert result == tuple(item for item in actions if item != action)


@given(
    existing=st.booleans(),
    text=st.text(
        alphabet=st.characters(blacklist_characters="\r\n", blacklist_categories=("Cs",)),
        max_size=80,
    ),
)
def test_ensure_text_file_preserves_existing_content(existing: bool, text: str) -> None:
    with TemporaryDirectory() as raw_root:
        target = Path(raw_root) / "nested" / "file.txt"
        if existing:
            target.parent.mkdir(parents=True)
            target.write_text("original", encoding="utf-8")

        action = ensure_text_file(target, text)

        assert action == ("kept" if existing else "created")
        assert target.read_text(encoding="utf-8") == ("original" if existing else text)


@given(existing=st.booleans(), content=st.binary(max_size=80))
def test_ensure_bytes_file_preserves_existing_content(existing: bool, content: bytes) -> None:
    with TemporaryDirectory() as raw_root:
        target = Path(raw_root) / "nested" / "file.bin"
        if existing:
            target.parent.mkdir(parents=True)
            target.write_bytes(b"original")

        action = ensure_bytes_file(target, content)

        assert action == ("kept" if existing else "created")
        assert target.read_bytes() == (b"original" if existing else content)
