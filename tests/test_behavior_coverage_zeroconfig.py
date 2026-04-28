from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from interlocks.behavior_coverage import (
    BehaviorRegistry,
    behavior_coverage_for_config,
    behavior_registry_for_config,
)
from interlocks.config import load_config
from interlocks.tasks.evaluate import evaluate
from tests.conftest import TmpProjectFactory

_DOWNSTREAM_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "downstream-app"
    version = "0.0.0"
    requires-python = ">=3.13"
    """
)


def _downstream_project(make_tmp_project: TmpProjectFactory) -> Path:
    return make_tmp_project(pyproject=_DOWNSTREAM_PYPROJECT)


def test_non_interlocks_project_returns_empty_registry(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_downstream_project(make_tmp_project))

    registry = behavior_registry_for_config(load_config())

    assert isinstance(registry, BehaviorRegistry)
    assert registry.behaviors == ()
    assert registry.live_ids == ()
    assert registry.duplicates == ()


def test_empty_registry_with_no_features_reports_clean_coverage(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_downstream_project(make_tmp_project))

    result = behavior_coverage_for_config(load_config(), [])

    assert result.is_complete
    assert result.uncovered_behavior_ids == ()
    assert result.duplicate_behavior_ids == ()
    assert result.stale_scenario_behaviors == ()
    assert result.coverage.behaviors == ()
    assert result.coverage.scenario_behaviors == ()


def test_acceptance_scoring_unaffected_when_registry_is_empty(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _downstream_project(make_tmp_project)
    feature = project / "tests" / "features" / "checkout.feature"
    feature.parent.mkdir(parents=True, exist_ok=True)
    feature.write_text(
        textwrap.dedent(
            """\
            Feature: checkout

              @req-checkout-paid
              Scenario: paid order succeeds
                Given buyer has cart
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    cfg = load_config()

    assert behavior_registry_for_config(cfg).behaviors == ()
    report = evaluate(cfg)
    acceptance = next(item for item in report.items if item.category == "acceptance")

    assert acceptance.score == 3
    assert acceptance.next_action is None
