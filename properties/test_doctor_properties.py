"""Property tests for doctor readiness and next-step helpers."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks.config import InterlockConfig
from interlocks.tasks.doctor import (
    _INERT_DETAIL,
    CheckRow,
    _acceptance_row,
    _actionable_gap_rows,
    _blocked_next_steps,
    _cfg_rows,
    _crash_report_cache_row,
    _gap_lines,
    _is_fail,
    _is_warn,
    _next_steps,
    _readiness,
)

_STATES = st.sampled_from(["ok", "warn", "fail"])
_LABELS = st.sampled_from([
    "preset",
    "interlocks cfg",
    "git hook",
    "claude hook",
    "agent docs",
    "claude skill",
    "acceptance",
    "properties",
    "ci workflow",
    "venv",
    "other",
])


@st.composite
def rows(draw: st.DrawFn) -> list[CheckRow]:
    values: list[CheckRow] = []
    for index in range(draw(st.integers(min_value=0, max_value=20))):
        label = draw(_LABELS)
        state = draw(_STATES)
        detail = draw(st.text(min_size=1, max_size=40))
        values.append(CheckRow(label, f"target-{index}", detail, state))
    return values


@given(is_blocked=st.booleans(), gap_count=st.integers(min_value=0, max_value=100))
def test_readiness_status_matches_blocked_and_gap_count(
    is_blocked: bool,
    gap_count: int,
) -> None:
    status, summary = _readiness(is_blocked, gap_count)

    if is_blocked:
        assert status == "blocked"
        assert "blockers" in summary
    elif gap_count:
        assert status == f"ready ({gap_count} gap{'s' if gap_count != 1 else ''})"
    else:
        assert status == "ready"


@given(gap_count=st.integers(min_value=0, max_value=100))
def test_readiness_blocked_state_takes_precedence_over_gaps(gap_count: int) -> None:
    blocked_status, blocked_summary = _readiness(True, gap_count)
    ready_status, ready_summary = _readiness(False, gap_count)

    assert blocked_status == "blocked"
    assert blocked_summary
    assert ready_status.startswith("ready")
    assert ready_summary


@given(rows())
def test_gap_lines_match_warn_rows_in_order(values: list[CheckRow]) -> None:
    assert _gap_lines(values) == [
        f"{row.label}: {row.detail}"
        for row in values
        if row.state == "warn" and row.detail != _INERT_DETAIL
    ]


@given(rows())
def test_gap_lines_count_matches_actionable_gap_rows(values: list[CheckRow]) -> None:
    assert len(_gap_lines(values)) == len(_actionable_gap_rows(values))


@given(rows())
def test_gap_lines_do_not_include_targets_or_inert_details(values: list[CheckRow]) -> None:
    lines = _gap_lines(values)

    assert lines == [f"{row.label}: {row.detail}" for row in _actionable_gap_rows(values)]
    for row in values:
        assert all(row.target not in line for line in lines)


@given(rows())
def test_actionable_gap_rows_exclude_inert_placeholders(values: list[CheckRow]) -> None:
    assert _actionable_gap_rows(values) == [
        row for row in values if row.state == "warn" and row.detail != _INERT_DETAIL
    ]


@given(label=_LABELS, target=st.text(max_size=20))
def test_actionable_gap_rows_treat_only_warn_rows_as_gaps(label: str, target: str) -> None:
    rows = [
        CheckRow(label, target, "ok detail", "ok"),
        CheckRow(label, target, "fail detail", "fail"),
        CheckRow(label, target, "warn detail", "warn"),
        CheckRow(label, target, _INERT_DETAIL, "warn"),
    ]

    assert _actionable_gap_rows(rows) == [rows[2]]


@given(values=rows(), label=st.text(max_size=30))
def test_is_fail_matches_fail_row_lookup(values: list[CheckRow], label: str) -> None:
    by_label = {row.label: row for row in values}
    row = by_label.get(label)

    assert _is_fail(by_label, label) is (row is not None and row.state == "fail")


@given(label=st.text(min_size=1, max_size=30), state=_STATES)
def test_is_fail_requires_exact_label_and_fail_state(label: str, state: str) -> None:
    by_label = {
        label: CheckRow(label, "target", "detail", state),
        f"{label}-other": CheckRow(f"{label}-other", "target", "detail", "fail"),
    }

    assert _is_fail(by_label, label) is (state == "fail")
    assert _is_fail(by_label, f"{label}-missing") is False


@given(state=_STATES, inert=st.booleans())
def test_is_warn_requires_actionable_warn_row(state: str, inert: bool) -> None:
    detail = _INERT_DETAIL if inert else "action needed"
    rows_by_label = {"target": CheckRow("target", "target", detail, state)}

    assert _is_warn(rows_by_label, "target") is (state == "warn" and not inert)
    assert _is_warn(rows_by_label, "missing") is False


@given(
    runner=st.one_of(st.none(), st.sampled_from(["off", "pytest-bdd"])),
    has_feature=st.booleans(),
)
def test_acceptance_row_reflects_disabled_scaffolded_or_missing_state(
    runner: str | None,
    has_feature: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        features = root / "tests" / "features"
        features.mkdir(parents=True)
        if has_feature:
            (features / "generated.feature").write_text("Feature: generated\n", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "pkg",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            features_dir=features,
            acceptance_runner=runner,  # type: ignore[arg-type]
        )

        row = _acceptance_row(cfg)

    assert row.label == "acceptance"
    if runner == "off":
        assert row.target == "(disabled)"
        assert row.detail == _INERT_DETAIL
        assert row.state == "warn"
    elif has_feature:
        assert row.detail == "scaffolded"
        assert row.state == "ok"
    elif runner is not None:
        assert row.detail == "run `interlocks init --acceptance`"
        assert row.state == "warn"
    else:
        assert row.detail == "not wired"
        assert row.state == "warn"


@given(
    runner=st.one_of(st.none(), st.sampled_from(["off", "pytest-bdd"])),
    has_feature=st.booleans(),
    configured_features_dir=st.booleans(),
)
def test_acceptance_row_target_uses_configured_or_default_feature_dir(
    runner: str | None,
    has_feature: bool,
    configured_features_dir: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        features = root / "custom" / "features"
        features.mkdir(parents=True)
        if has_feature:
            (features / "generated.feature").write_text("Feature: generated\n", encoding="utf-8")
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "pkg",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            features_dir=features if configured_features_dir else None,
            acceptance_runner=runner,  # type: ignore[arg-type]
        )

        row = _acceptance_row(cfg)

    expected_target = "custom/features" if configured_features_dir else "tests/features/"
    assert row.target == ("(disabled)" if runner == "off" else expected_target)


@given(
    preset=st.one_of(st.none(), st.text(max_size=20)),
    runner=st.sampled_from(["pytest", "unittest"]),
    invoker=st.sampled_from(["python", "uv"]),
)
def test_cfg_rows_include_core_and_derived_configuration(
    preset: str | None,
    runner: str,
    invoker: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "pkg",
            test_dir=root / "tests",
            test_runner=runner,
            test_invoker=invoker,
            preset=preset,
        )

        rows = dict(_cfg_rows(cfg))

    assert rows["preset"] == (preset or "(none)")
    assert rows["src_dir"] == "pkg"
    assert rows["test_dir"] == "tests"
    assert rows["test_runner"] == runner
    assert rows["test_invoker"] == invoker
    assert "coverage_min" in rows
    assert "run_properties_in_check" in rows


@given(
    preset=st.one_of(st.none(), st.text(max_size=20)),
    runner=st.sampled_from(["pytest", "unittest"]),
    invoker=st.sampled_from(["python", "uv"]),
)
def test_cfg_rows_preserve_display_order_and_unique_keys(
    preset: str | None,
    runner: str,
    invoker: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "pkg",
            test_dir=root / "tests",
            test_runner=runner,
            test_invoker=invoker,
            preset=preset,
        )

        rows = _cfg_rows(cfg)

    keys = [key for key, _value in rows]
    assert keys[:8] == [
        "preset",
        "src_dir",
        "test_dir",
        "test_runner",
        "test_invoker",
        "features_dir",
        "properties_dir",
        "acceptance_runner",
    ]
    assert len(keys) == len(set(keys))


@given(count=st.integers(min_value=0, max_value=5))
def test_crash_report_cache_row_reports_cached_json_count(count: int) -> None:
    base_mtime = 1_700_000_000
    old_cache = os.environ.get("XDG_CACHE_HOME")
    with TemporaryDirectory() as raw_root:
        os.environ["XDG_CACHE_HOME"] = raw_root
        cache = Path(raw_root) / "interlocks" / "crashes"
        cache.mkdir(parents=True)
        for index in range(count):
            path = cache / f"{index}.json"
            path.write_text("{}", encoding="utf-8")
            os.utime(path, (base_mtime + index, base_mtime + index))
        try:
            row = _crash_report_cache_row()
        finally:
            if old_cache is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = old_cache

    assert row.label == "crash reports"
    assert row.state == "ok"
    if count == 0:
        assert row.detail == "0 cached"
    else:
        assert row.detail.startswith(f"{count} cached")
        assert "last seen:" in row.detail


@given(error=st.text(min_size=1, max_size=80))
def test_crash_report_cache_row_warns_when_cache_is_unreadable(error: str) -> None:
    with patch("interlocks.tasks.doctor._crash_cache_dir", side_effect=OSError(error)):
        row = _crash_report_cache_row()

    assert row == CheckRow(
        "crash reports",
        "~/.cache/interlocks/crashes/",
        "cache unreadable",
        "warn",
    )


@given(rows())
def test_next_steps_for_blocked_report_is_non_empty_and_unique(
    values: list[CheckRow],
) -> None:
    steps = _next_steps(values, is_blocked=True)

    assert steps
    assert len(steps) == len(set(steps))


def test_blocked_next_steps_name_missing_pyproject_directly() -> None:
    assert _blocked_next_steps(
        [CheckRow("pyproject", "pyproject.toml", "missing", "fail")],
        (),
    ) == ["Run `interlocks init` to scaffold a project, then rerun `interlocks doctor`."]


def test_blocked_next_steps_name_project_env_directly() -> None:
    assert _blocked_next_steps(
        [CheckRow("venv", ".venv/bin/python", "missing — typecheck/test blocked", "fail")],
        (),
    ) == [
        "Create a project environment (`uv sync`, or "
        "`python -m venv .venv && pip install -e .`), then rerun `interlocks doctor`."
    ]


def test_blocked_next_steps_falls_back_when_blocker_is_unknown() -> None:
    assert _blocked_next_steps([], ()) == [
        "Fix blockers in Setup Checklist above, then rerun `interlocks doctor`."
    ]


def test_next_steps_include_property_scaffold_for_properties_gap() -> None:
    assert _next_steps(
        [CheckRow("properties", "properties", "run `interlocks init --properties`", "warn")],
        is_blocked=False,
    ) == ["Run `interlocks init --properties` to scaffold property tests."]


def test_next_steps_replace_scaffold_for_scaffold_only_properties_gap() -> None:
    assert _next_steps(
        [CheckRow("properties", "tests/properties", "replace scaffold example", "warn")],
        is_blocked=False,
    ) == [
        "Replace tests/properties/test_example_properties.py with domain invariants, "
        "then run `interlocks gate properties --profile=check`."
    ]


def test_inert_warning_rows_do_not_trigger_next_steps() -> None:
    assert _next_steps(
        [
            CheckRow("git hook", ".git/hooks/pre-commit", _INERT_DETAIL, "warn"),
            CheckRow("acceptance", "(disabled)", _INERT_DETAIL, "warn"),
        ],
        is_blocked=False,
    ) == ["Run `interlocks check` locally."]


@given(rows())
def test_next_steps_never_repeat_identical_steps(values: list[CheckRow]) -> None:
    steps = _next_steps(values, is_blocked=False)

    assert len(steps) == len(set(steps))
