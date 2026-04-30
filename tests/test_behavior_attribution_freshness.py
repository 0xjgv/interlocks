from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from interlocks.acceptance_status import AcceptanceClassification, AcceptanceStatus
from interlocks.config import clear_cache
from interlocks.runner import Task
from interlocks.tasks.behavior_attribution import cmd_behavior_attribution

_ACTIVE_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "interlocks"
    version = "0.0.0"

    [tool.interlocks]
    features_dir = "tests/features"
    acceptance_runner = "pytest-bdd"
    """
)


def test_cmd_refreshes_when_evidence_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    project = _active_registry_project(tmp_path)
    monkeypatch.chdir(project)
    clear_cache()
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.evidence_is_fresh",
        lambda cfg, path: False,
    )
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.task_acceptance_with_attribution",
        lambda cfg: Task("Acceptance", [sys.executable, "-c", "pass"]),
    )
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.run",
        lambda task: calls.append("acceptance"),
    )

    cmd_behavior_attribution(refresh=True)

    assert calls == ["acceptance"]


def test_cmd_does_not_refresh_fresh_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _active_registry_project(tmp_path)
    monkeypatch.chdir(project)
    clear_cache()
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.evidence_is_fresh",
        lambda cfg, path: True,
    )
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.task_acceptance_with_attribution",
        lambda cfg: pytest.fail("should not refresh"),
    )

    cmd_behavior_attribution(refresh=True)


def test_cmd_refresh_false_never_calls_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _active_registry_project(tmp_path)
    monkeypatch.chdir(project)
    clear_cache()
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.evidence_is_fresh",
        lambda cfg, path: False,
    )
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.task_acceptance_with_attribution",
        lambda cfg: pytest.fail("should not refresh"),
    )

    cmd_behavior_attribution(refresh=False)


def test_stale_evidence_with_behave_warn_skips_without_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _active_registry_project(tmp_path)
    monkeypatch.chdir(project)
    clear_cache()
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.evidence_is_fresh",
        lambda cfg, path: False,
    )
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.detect_acceptance_runner",
        lambda cfg: "behave",
    )
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.task_acceptance_with_attribution",
        lambda cfg: pytest.fail("should not refresh behave projects"),
    )

    cmd_behavior_attribution(refresh=True)

    out = capsys.readouterr().out
    assert "runtime attribution supports pytest-bdd only" in out


def test_acceptance_classification_required_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _active_registry_project(tmp_path)
    monkeypatch.chdir(project)
    clear_cache()
    calls: list[str] = []
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.evidence_is_fresh",
        lambda cfg, path: False,
    )
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.classify_acceptance_with_details",
        lambda cfg: AcceptanceClassification(
            AcceptanceStatus.MISSING_FEATURE_FILES,
            project / "tests" / "features",
        ),
    )

    def fake_fail_skip(message: str) -> None:
        calls.append(message)
        raise SystemExit(1)

    monkeypatch.setattr("interlocks.tasks.behavior_attribution.fail_skip", fake_fail_skip)

    with pytest.raises(SystemExit):
        cmd_behavior_attribution(refresh=True)

    assert calls


def _active_registry_project(root: Path) -> Path:
    (root / "pyproject.toml").write_text(_ACTIVE_PYPROJECT, encoding="utf-8")
    features = root / "tests" / "features"
    features.mkdir(parents=True)
    (features / "behavior.feature").write_text(
        "Feature: behavior\n\n  Scenario: covered behavior\n    Given a thing\n",
        encoding="utf-8",
    )
    return root
