"""Property tests for coverage task command construction."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hypothesis import assume, given
from hypothesis import strategies as st

from interlocks.config import InterlockConfig
from interlocks.tasks.coverage import (
    _coverage_options,
    _coverage_progress_label,
    _coverage_progress_steps,
    _coverage_skip_payload,
    _property_coverage_pre_cmds,
)


@given(
    configured_min=st.integers(min_value=0, max_value=100),
    explicit_min=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
    cli_min=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
    include_properties=st.booleans(),
    default_profile=st.sampled_from(["check", "ci", "nightly", "default"]),
    cli_properties=st.one_of(
        st.none(),
        st.sampled_from(["<bare>", "", "check", "ci", "nightly", "default", "custom"]),
    ),
)
def test_coverage_options_resolve_cli_properties_and_threshold(
    configured_min: int,
    explicit_min: int | None,
    cli_min: int | None,
    include_properties: bool,
    default_profile: str,
    cli_properties: str | None,
) -> None:
    argv = ["interlocks", "coverage"]
    if cli_min is not None:
        argv.append(f"--min={cli_min}")
    if cli_properties == "<bare>":
        argv.append("--properties")
    elif cli_properties is not None:
        argv.append(f"--properties={cli_properties}")
    cfg = InterlockConfig(
        project_root=Path(),
        src_dir=Path("pkg"),
        test_dir=Path("tests"),
        test_runner="pytest",
        test_invoker="python",
        coverage_min=configured_min,
    )

    with patch.object(sys, "argv", argv):
        resolved_min, resolved_include, resolved_profile = _coverage_options(
            cfg,
            min_pct=explicit_min,
            include_properties=include_properties,
            property_profile=default_profile,
        )

    expected_min = explicit_min if explicit_min is not None else cli_min
    if expected_min is None:
        expected_min = configured_min
    expected_include = include_properties if cli_properties is None else True
    expected_profile = default_profile
    if cli_properties is not None:
        expected_profile = default_profile if cli_properties in {"<bare>", ""} else cli_properties

    assert resolved_min == expected_min
    assert resolved_include is expected_include
    assert resolved_profile == expected_profile


@given(
    profile=st.sampled_from(["check", "ci", "nightly", "default"]),
    coverage_args=st.lists(
        st.sampled_from(["--branch", "--timid", "--rcfile=coverage.ini"]),
        max_size=3,
        unique=True,
    ),
    has_property_file=st.booleans(),
)
def test_property_coverage_pre_cmds_exist_only_when_property_files_exist(
    profile: str, coverage_args: list[str], has_property_file: bool
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        properties = root / "properties"
        properties.mkdir()
        if has_property_file:
            (properties / "test_generated_properties.py").write_text(
                "def test_generated() -> None:\n    assert True\n", encoding="utf-8"
            )
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "pkg",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            properties_dir=properties,
        )

        cmds = _property_coverage_pre_cmds(
            cfg, coverage_args=tuple(coverage_args), profile=profile
        )

    if not has_property_file:
        assert cmds == ()
        return

    assert len(cmds) == 3
    property_run = cmds[-1]
    assert "coverage" in property_run
    assert "run" in property_run
    assert "--append" in property_run
    assert all(arg in property_run for arg in coverage_args)
    assert "properties" in property_run
    assert f"--hypothesis-profile={profile}" in property_run


@given(
    prefix=st.lists(st.text(min_size=1, max_size=10), max_size=3),
    suffix=st.lists(st.text(min_size=1, max_size=10), max_size=3),
    phase=st.sampled_from([
        ("Coverage.py is not importable", "coverage import preflight"),
        ("find_spec('hypothesis')", "hypothesis import preflight"),
        ("property_coverage_runner.py write_text", "write property coverage runner"),
    ]),
)
def test_coverage_progress_label_classifies_python_preflight_phases(
    prefix: list[str],
    suffix: list[str],
    phase: tuple[str, str],
) -> None:
    marker, expected = phase

    assert _coverage_progress_label([*prefix, marker, *suffix]) == expected


@given(
    pre_cmds=st.lists(
        st.lists(st.text(min_size=1, max_size=12), min_size=1, max_size=5),
        max_size=8,
    ).map(tuple)
)
def test_coverage_progress_steps_map_precommands_and_append_report(
    pre_cmds: tuple[list[str], ...],
) -> None:
    steps = _coverage_progress_steps(pre_cmds)

    assert steps[:-1] == tuple(_coverage_progress_label(cmd) for cmd in pre_cmds)
    assert steps[-1] == "coverage report"


@given(cmd=st.lists(st.text(min_size=1, max_size=12), min_size=1, max_size=8))
def test_coverage_progress_label_classifies_coverage_run_and_json(cmd: list[str]) -> None:
    joined = " ".join(cmd)
    assume("Coverage.py is not importable" not in joined)
    assume("find_spec('hypothesis')" not in joined)
    assume("property_coverage_runner.py" not in joined)
    if "--append" in cmd:
        assert _coverage_progress_label(cmd) == "property tests under coverage"
    elif "json" in cmd:
        assert _coverage_progress_label(cmd) == "coverage JSON"


@given(
    min_pct=st.integers(min_value=0, max_value=100),
    include_properties=st.booleans(),
    profile=st.sampled_from(["check", "ci", "nightly", "default"]),
    reason=st.text(max_size=100),
    next_action=st.text(max_size=100),
)
def test_coverage_skip_payload_names_threshold_and_property_profile(
    min_pct: int,
    include_properties: bool,
    profile: str,
    reason: str,
    next_action: str,
) -> None:
    payload = _coverage_skip_payload(
        min_pct=min_pct,
        include_properties=include_properties,
        property_profile=profile,
        reason=reason,
        next_action=next_action,
    )

    assert payload == {
        "command": "coverage",
        "passed": True,
        "status": "skipped",
        "min_pct": min_pct,
        "include_properties": include_properties,
        "property_profile": profile if include_properties else None,
        "reason": reason,
        "next_actions": [next_action],
    }
