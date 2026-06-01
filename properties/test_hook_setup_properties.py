"""Property tests for local hook setup normalization."""

from __future__ import annotations

from copy import deepcopy

from hypothesis import given
from hypothesis import strategies as st

from interlocks.hook_setup import _ensure_stop_hook, _keep_existing_hook, _reset_invalid_container
from interlocks.setup_state import is_post_edit_command

_TEXT = st.text(max_size=40)
_KEY = st.text(min_size=1, max_size=20)
_SCALAR = st.one_of(st.none(), st.booleans(), st.integers(), _TEXT)
_POST_EDIT_COMMANDS = st.sampled_from((
    "uv run interlocks post-edit",
    "python -m interlocks.cli post-edit",
    "/example/.venv/bin/python -m interlocks.cli post-edit",
))
_COMMAND = st.one_of(_TEXT, _POST_EDIT_COMMANDS)
_HOOK = st.one_of(
    st.none(),
    st.integers(),
    st.fixed_dictionaries({"type": st.just("command"), "command": _COMMAND}),
    st.fixed_dictionaries({
        "type": _TEXT.filter(lambda value: value != "command"),
        "command": _TEXT,
    }),
    st.dictionaries(_TEXT, _TEXT, max_size=4),
)


@given(
    key=_KEY,
    existing=st.one_of(
        _SCALAR, st.dictionaries(_TEXT, _SCALAR, max_size=3), st.lists(_SCALAR, max_size=3)
    ),
    empty_kind=st.sampled_from(("dict", "list")),
)
def test_reset_invalid_container_preserves_matching_type_and_replaces_other_values(
    key: str,
    existing: object,
    empty_kind: str,
) -> None:
    parent: dict[str, object] = {key: existing}
    empty: dict[str, object] | list[object] = {} if empty_kind == "dict" else []

    result = _reset_invalid_container(parent, key, empty)

    if isinstance(existing, type(empty)):
        assert result is existing
        assert parent[key] is existing
    else:
        assert result is empty
        assert parent[key] is empty


_STOP_ENTRY = st.one_of(
    st.none(),
    st.integers(),
    st.fixed_dictionaries({"hooks": st.lists(_HOOK, max_size=8)}),
    st.dictionaries(_TEXT, _TEXT, max_size=4),
)
_SETTINGS = st.fixed_dictionaries(
    {},
    optional={
        "theme": _TEXT,
        "hooks": st.one_of(
            st.none(),
            st.lists(_STOP_ENTRY, max_size=5),
            st.fixed_dictionaries({"Stop": st.lists(_STOP_ENTRY, max_size=5)}),
            st.dictionaries(_TEXT, _TEXT, max_size=4),
        ),
    },
)


@given(hook=_HOOK, new_command=_COMMAND)
def test_keep_existing_hook_drops_only_duplicate_or_post_edit_commands(
    hook: object, new_command: str
) -> None:
    keep = _keep_existing_hook(hook, new_command)

    if not isinstance(hook, dict) or hook.get("type") != "command":
        assert keep is True
    elif hook.get("command") == new_command or is_post_edit_command(hook.get("command")):
        assert keep is False
    else:
        assert keep is True


@given(new_command=_TEXT)
def test_keep_existing_hook_drops_exact_duplicate_command(new_command: str) -> None:
    assert _keep_existing_hook({"type": "command", "command": new_command}, new_command) is False


@given(settings=_SETTINGS, command=_COMMAND)
def test_ensure_stop_hook_normalizes_to_one_stop_command(
    settings: dict[str, object], command: str
) -> None:
    original = deepcopy(settings)

    result = _ensure_stop_hook(settings, command)
    second = deepcopy(result)
    _ensure_stop_hook(settings, command)

    assert result is settings
    assert settings == second
    if "theme" in original:
        assert settings["theme"] == original["theme"]

    hooks = settings["hooks"]
    assert isinstance(hooks, dict)
    assert "Stop" in hooks
    stop = hooks["Stop"]
    assert isinstance(stop, list)
    assert len(stop) == 1
    entry = stop[0]
    assert isinstance(entry, dict)
    merged = entry["hooks"]
    assert isinstance(merged, list)

    command_hooks = [
        hook for hook in merged if isinstance(hook, dict) and hook.get("type") == "command"
    ]
    assert sum(1 for hook in command_hooks if hook.get("command") == command) == 1
    assert not any(
        hook.get("command") != command and is_post_edit_command(hook.get("command"))
        for hook in command_hooks
    )
