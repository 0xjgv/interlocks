from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from interlocks.acceptance_status import AcceptanceClassification, AcceptanceStatus
from interlocks.config import clear_cache, load_config
from interlocks.runner import Task, record_result
from interlocks.tasks import behavior_attribution as behavior_mod
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
    capsys: pytest.CaptureFixture[str],
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
    assert "[attribution]" in capsys.readouterr().out


def test_cmd_refresh_false_never_calls_acceptance(
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
        "interlocks.tasks.behavior_attribution.task_acceptance_with_attribution",
        lambda cfg: pytest.fail("should not refresh"),
    )

    cmd_behavior_attribution(refresh=False)
    assert "[attribution]" in capsys.readouterr().out


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


def test_json_refresh_returns_none_when_evidence_is_fresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _active_registry_project(tmp_path)
    monkeypatch.chdir(project)
    clear_cache()
    monkeypatch.setattr(
        behavior_mod,
        "evidence_is_fresh",
        lambda cfg, path: True,
    )

    assert behavior_mod._refresh_evidence_if_needed_json(load_config()) is None


def test_json_refresh_skips_when_acceptance_not_runnable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _active_registry_project(tmp_path)
    monkeypatch.chdir(project)
    clear_cache()
    monkeypatch.setattr(
        behavior_mod,
        "evidence_is_fresh",
        lambda cfg, path: False,
    )
    monkeypatch.setattr(
        behavior_mod,
        "classify_acceptance_with_details",
        lambda cfg: AcceptanceClassification(AcceptanceStatus.DISABLED, project / "tests"),
    )
    monkeypatch.setattr(
        behavior_mod,
        "task_acceptance_with_attribution",
        lambda cfg: pytest.fail("should not build acceptance task"),
    )

    assert behavior_mod._refresh_evidence_if_needed_json(load_config()) is None


def test_json_refresh_success_clears_runner_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _active_registry_project(tmp_path)
    monkeypatch.chdir(project)
    clear_cache()
    monkeypatch.setattr(
        behavior_mod,
        "evidence_is_fresh",
        lambda cfg, path: False,
    )
    monkeypatch.setattr(
        behavior_mod,
        "classify_acceptance_with_details",
        lambda cfg: AcceptanceClassification(AcceptanceStatus.RUNNABLE, project / "tests"),
    )
    monkeypatch.setattr(behavior_mod, "detect_acceptance_runner", lambda cfg: "pytest-bdd")
    monkeypatch.setattr(
        behavior_mod,
        "task_acceptance_with_attribution",
        lambda cfg: Task("Acceptance", [sys.executable, "-c", "pass"], label="acceptance"),
    )

    def fake_run(task: Task, *, no_exit: bool = False) -> None:
        assert no_exit is True
        record_result("acceptance", status="ok", elapsed=0.01, detail=None)

    monkeypatch.setattr(behavior_mod, "run", fake_run)

    assert behavior_mod._refresh_evidence_if_needed_json(load_config()) is None


def test_json_refresh_failure_returns_stage_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = _active_registry_project(tmp_path)
    monkeypatch.chdir(project)
    clear_cache()
    monkeypatch.setattr(
        behavior_mod,
        "evidence_is_fresh",
        lambda cfg, path: False,
    )
    monkeypatch.setattr(
        behavior_mod,
        "classify_acceptance_with_details",
        lambda cfg: AcceptanceClassification(AcceptanceStatus.RUNNABLE, project / "tests"),
    )
    monkeypatch.setattr(behavior_mod, "detect_acceptance_runner", lambda cfg: "pytest-bdd")
    monkeypatch.setattr(
        behavior_mod,
        "task_acceptance_with_attribution",
        lambda cfg: Task("Acceptance", [sys.executable, "-c", "pass"], label="acceptance"),
    )

    def fake_run(task: Task, *, no_exit: bool = False) -> None:
        assert no_exit is True
        record_result("acceptance", status="fail", elapsed=0.01, detail="boom")

    monkeypatch.setattr(behavior_mod, "run", fake_run)

    payload = behavior_mod._refresh_evidence_if_needed_json(load_config())

    assert payload is not None
    assert payload["command"] == "behavior-attribution"
    assert payload["passed"] is False
    assert payload["status"] == "failed"
    assert payload["error"] == "acceptance evidence refresh failed"


def _active_registry_project(root: Path) -> Path:
    (root / "pyproject.toml").write_text(_ACTIVE_PYPROJECT, encoding="utf-8")
    features = root / "tests" / "features"
    features.mkdir(parents=True)
    (features / "behavior.feature").write_text(
        "Feature: behavior\n\n  Scenario: covered behavior\n    Given a thing\n",
        encoding="utf-8",
    )
    return root
