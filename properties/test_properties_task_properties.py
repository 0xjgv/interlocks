"""Property tests for property-test task helpers."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.config import InterlockConfig
from interlocks.tasks.properties import (
    _INIT_PROPERTIES_DOMAIN_FILE_LIMIT,
    _init_properties_payload,
    _InitPropertiesResult,
    _properties_skip_payload,
)

_REL_PATH = st.from_regex(
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,20}){0,2}",
    fullmatch=True,
)
_STATUS = st.from_regex(r"[a-z][a-z0-9-]{0,30}", fullmatch=True)
_ACTION = st.sampled_from(["created", "kept"])
_PROFILE = st.sampled_from(["check", "ci", "nightly", "default", "custom"])


@given(
    properties_dir=_REL_PATH,
    status=_STATUS,
    scaffold_files=st.lists(st.tuples(_REL_PATH, _ACTION), max_size=5),
    domain_files=st.lists(_REL_PATH, max_size=30),
    next_actions=st.lists(st.text(max_size=80), max_size=5),
)
def test_init_properties_payload_uses_project_relative_paths(
    properties_dir: str,
    status: str,
    scaffold_files: list[tuple[str, str]],
    domain_files: list[str],
    next_actions: list[str],
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )
        files = tuple({"path": path, "action": action} for path, action in scaffold_files)

        payload = _init_properties_payload(
            cfg,
            root / properties_dir,
            _InitPropertiesResult(
                status=status,
                files=files,
                domain_files=tuple(root / path for path in domain_files),
                next_actions=tuple(next_actions),
            ),
        )

    expected: dict[str, object] = {
        "command": "init-properties",
        "passed": True,
        "status": status,
        "properties_dir": properties_dir,
        "files": list(files),
        "domain_property_test_count": len(domain_files),
        "domain_property_tests": domain_files[:_INIT_PROPERTIES_DOMAIN_FILE_LIMIT],
        "next_actions": next_actions,
    }
    omitted = len(domain_files) - _INIT_PROPERTIES_DOMAIN_FILE_LIMIT
    if omitted > 0:
        expected["omitted_domain_property_tests"] = omitted
    else:
        assert "omitted_domain_property_tests" not in payload
    assert payload == expected


@given(
    profile=_PROFILE,
    reason=st.text(max_size=100),
    next_action=st.text(max_size=100),
    configured=st.booleans(),
)
def test_properties_skip_payload_names_profile_and_properties_dir(
    profile: str,
    reason: str,
    next_action: str,
    configured: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        properties_dir = root / "tests" / "properties" if configured else None
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            properties_dir=properties_dir,
        )

        payload = _properties_skip_payload(cfg, profile, reason, next_action)

    assert payload == {
        "command": "properties",
        "passed": True,
        "status": "skipped",
        "profile": profile,
        "properties_dir": "tests/properties" if configured else "properties",
        "reason": reason,
        "next_actions": [next_action],
    }
