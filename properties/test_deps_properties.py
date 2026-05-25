"""Property tests for dependency-hygiene command helpers."""

from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.config import InterlockConfig
from interlocks.tasks.deps import _property_exclude_args

_SEGMENT = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_-"),
    min_size=1,
    max_size=12,
).filter(lambda value: value not in {".", ".."})


@given(segments=st.lists(_SEGMENT, min_size=1, max_size=3))
def test_property_exclude_args_escape_configured_property_dir(segments: list[str]) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        relpath = Path(*segments)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="uv",
            properties_dir=root / relpath,
        )

        assert _property_exclude_args(cfg) == ["--extend-exclude", re.escape(str(relpath))]


def test_property_exclude_args_ignore_project_root() -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root,
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="uv",
            properties_dir=root,
        )

        assert _property_exclude_args(cfg) == []


def test_property_exclude_args_ignore_property_dir_outside_scan_root() -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "pkg",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="uv",
            properties_dir=root / "properties",
        )

        assert _property_exclude_args(cfg) == []
