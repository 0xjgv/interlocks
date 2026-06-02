"""Property tests for acceptance readiness classification."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from interlocks.acceptance_status import (
    AcceptanceStatus,
    classify_acceptance,
    classify_acceptance_with_details,
    count_scenarios,
)
from interlocks.config import InterlockConfig

_TITLES = st.text(
    alphabet=st.characters(blacklist_characters="\r\n", blacklist_categories=("Cc", "Cs")),
    min_size=1,
    max_size=30,
).filter(lambda value: bool(value.strip()))
_NON_SCENARIO_LINES = st.sampled_from([
    "Feature: generated",
    "  Given a precondition",
    "  When an action occurs",
    "  Then an outcome is visible",
    "  # Scenario: commented out",
    "",
])


@st.composite
def feature_bodies(draw: Any) -> tuple[str, int]:
    lines: list[str] = ["Feature: generated"]
    expected = 0
    for _ in range(draw(st.integers(min_value=0, max_value=20))):
        if draw(st.booleans()):
            kind = draw(st.sampled_from(["Scenario", "Scenario Outline"]))
            lines.append(f"  {kind}: {draw(_TITLES)}")
            expected += 1
        else:
            lines.append(draw(_NON_SCENARIO_LINES))
    return "\n".join(lines) + "\n", expected


def _cfg(root: Path, features_dir: Path | None, *, require_acceptance: bool) -> InterlockConfig:
    return InterlockConfig(
        project_root=root,
        src_dir=root,
        test_dir=root / "tests",
        test_runner="pytest",
        test_invoker="python",
        acceptance_runner="pytest-bdd",
        features_dir=features_dir,
        require_acceptance=require_acceptance,
    )


@given(feature_bodies())
def test_optional_acceptance_is_runnable_iff_feature_has_scenarios(
    body_and_count: tuple[str, int],
) -> None:
    body, expected_count = body_and_count
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        features_dir = root / "tests" / "features"
        features_dir.mkdir(parents=True)
        feature = features_dir / "generated.feature"
        feature.write_text(body, encoding="utf-8")

        assert count_scenarios([feature]) == expected_count

        status = classify_acceptance(_cfg(root, features_dir, require_acceptance=False))
        expected_status = (
            AcceptanceStatus.RUNNABLE if expected_count > 0 else AcceptanceStatus.OPTIONAL_MISSING
        )
        assert status is expected_status


@given(require_acceptance=st.booleans())
def test_acceptance_runner_off_always_disables(require_acceptance: bool) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        status = classify_acceptance(
            InterlockConfig(
                project_root=root,
                src_dir=root,
                test_dir=root / "tests",
                test_runner="pytest",
                test_invoker="python",
                acceptance_runner="off",
                features_dir=None,
                require_acceptance=require_acceptance,
            )
        )

    assert status is AcceptanceStatus.DISABLED


@given(require_acceptance=st.booleans())
def test_acceptance_runner_off_preserves_configured_feature_dir_detail(
    require_acceptance: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        features_dir = root / "tests" / "features"
        classified = classify_acceptance_with_details(
            InterlockConfig(
                project_root=root,
                src_dir=root,
                test_dir=root / "tests",
                test_runner="pytest",
                test_invoker="python",
                acceptance_runner="off",
                features_dir=features_dir,
                require_acceptance=require_acceptance,
            )
        )

    assert classified.status is AcceptanceStatus.DISABLED
    assert classified.features_dir == features_dir


@given(
    state=st.sampled_from(["none", "missing-dir", "empty-dir", "no-scenarios", "scenario"]),
    require_acceptance=st.booleans(),
)
def test_classify_acceptance_with_details_reports_required_and_optional_states(
    state: str,
    require_acceptance: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        features_dir = None if state == "none" else root / "tests" / "features"
        if state in {"empty-dir", "no-scenarios", "scenario"}:
            assert features_dir is not None
            features_dir.mkdir(parents=True)
        if state == "no-scenarios":
            assert features_dir is not None
            (features_dir / "generated.feature").write_text(
                "Feature: generated\n",
                encoding="utf-8",
            )
        if state == "scenario":
            assert features_dir is not None
            (features_dir / "generated.feature").write_text(
                "Feature: generated\n  Scenario: works\n",
                encoding="utf-8",
            )
        cfg = _cfg(root, features_dir, require_acceptance=require_acceptance)

        classified = classify_acceptance_with_details(cfg)

    if state == "scenario":
        assert classified.status is AcceptanceStatus.RUNNABLE
    elif not require_acceptance:
        assert classified.status is AcceptanceStatus.OPTIONAL_MISSING
    elif state in {"none", "missing-dir"}:
        assert classified.status is AcceptanceStatus.MISSING_FEATURES_DIR
    elif state == "empty-dir":
        assert classified.status is AcceptanceStatus.MISSING_FEATURE_FILES
    else:
        assert classified.status is AcceptanceStatus.MISSING_SCENARIOS
    assert classified.features_dir == features_dir


@given(
    state=st.sampled_from(["none", "missing-dir", "empty-dir", "no-scenarios"]),
    require_acceptance=st.booleans(),
)
def test_classify_acceptance_required_failure_flag_matches_status(
    state: str,
    require_acceptance: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        features_dir = None if state == "none" else root / "tests" / "features"
        if state in {"empty-dir", "no-scenarios"}:
            assert features_dir is not None
            features_dir.mkdir(parents=True)
        if state == "no-scenarios":
            assert features_dir is not None
            (features_dir / "generated.feature").write_text(
                "Feature: generated\n",
                encoding="utf-8",
            )

        classified = classify_acceptance_with_details(
            _cfg(root, features_dir, require_acceptance=require_acceptance)
        )

    assert classified.is_required_failure is (
        require_acceptance and classified.status is not AcceptanceStatus.OPTIONAL_MISSING
    )
