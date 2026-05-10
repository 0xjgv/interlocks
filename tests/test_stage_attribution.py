from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from interlocks.behavior_attribution import AttributionResult
from interlocks.behavior_coverage import Behavior
from interlocks.config import InterlockConfig
from interlocks.stages.ci import cmd_ci
from interlocks.tasks.behavior_attribution import cmd_behavior_attribution_cached_advisory

_CFG = InterlockConfig(
    project_root=Path.cwd(),
    src_dir=Path.cwd(),
    test_dir=Path.cwd(),
    test_runner="pytest",
    test_invoker="python",
)


def test_ci_runs_attribution_after_crap_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr("interlocks.stages.ci.load_config", lambda: _CFG)
    monkeypatch.setattr(
        "interlocks.stages.ci.classify_acceptance_with_details",
        lambda cfg: _acceptance_off(),
    )
    monkeypatch.setattr("interlocks.stages.ci.run_tasks", lambda tasks: calls.append("parallel"))
    monkeypatch.setattr("interlocks.stages.ci.cmd_crap", lambda: calls.append("crap"))
    monkeypatch.setattr(
        "interlocks.stages.ci.cmd_behavior_attribution",
        lambda refresh=False: calls.append(f"attribution:{refresh}"),
    )
    monkeypatch.setattr("interlocks.stages.ci.cmd_mutation", lambda **_: calls.append("mutation"))
    monkeypatch.setattr("interlocks.stages.ci._should_run_mutation", lambda *_, **__: True)
    monkeypatch.setattr("interlocks.stages.ci._write_ci_evidence", lambda *_, **__: None)

    cmd_ci()

    assert calls == ["parallel", "crap", "attribution:False", "mutation"]


def test_check_cached_advisory_skips_missing_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("interlocks.tasks.behavior_attribution.load_config", lambda: _CFG)
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.evidence_is_fresh",
        lambda cfg, path: False,
    )

    cmd_behavior_attribution_cached_advisory()

    out = capsys.readouterr().out
    assert "[attribution]" in out
    assert "no fresh evidence" in out


def _stub_incomplete_result(
    monkeypatch: pytest.MonkeyPatch, *, enforced: bool
) -> AttributionResult:
    cfg = replace(_CFG, enforce_behavior_attribution=enforced)
    monkeypatch.setattr("interlocks.tasks.behavior_attribution.load_config", lambda: cfg)
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.evidence_is_fresh",
        lambda cfg, path: True,
    )
    incomplete = AttributionResult(
        unresolved_behaviors=(
            Behavior(
                behavior_id="B-001",
                kind="task",
                summary="some unresolved behavior",
                public_symbol="pkg.symbol",
            ),
        ),
    )
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution._validate_current_project",
        lambda cfg: incomplete,
    )
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.format_attribution_failure",
        lambda result: "<failure-detail>",
    )
    return incomplete


def test_check_cached_advisory_fails_when_enforced_and_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_incomplete_result(monkeypatch, enforced=True)

    with pytest.raises(SystemExit) as excinfo:
        cmd_behavior_attribution_cached_advisory()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "[attribution]" in out
    assert "failed" in out
    assert "<failure-detail>" in out


def test_check_cached_advisory_warns_when_not_enforced(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_incomplete_result(monkeypatch, enforced=False)

    cmd_behavior_attribution_cached_advisory()

    out = capsys.readouterr().out
    assert "[attribution]" in out
    assert "warn" in out
    assert "cached advisory" in out
    assert "<failure-detail>" in out


def _acceptance_off() -> object:
    class AcceptanceOff:
        is_required_failure = False
        status = object()

    return AcceptanceOff()


def test_attribution_min_coverage_blocks_below_floor(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running attribution under a floor of 0.9 with observed 0.7 must exit 1.

    The result is otherwise complete (no unresolved behaviors and no warnings),
    so without the floor check the gate would pass.
    """
    cfg = replace(_CFG, attribution_min_coverage=0.9)
    monkeypatch.setattr("interlocks.tasks.behavior_attribution.load_config", lambda: cfg)
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution.evidence_is_fresh",
        lambda cfg, path: True,
    )
    result = AttributionResult(resolved_count=7, total_count=10)
    assert result.is_complete
    monkeypatch.setattr(
        "interlocks.tasks.behavior_attribution._validate_current_project",
        lambda cfg: result,
    )

    with pytest.raises(SystemExit) as exc:
        cmd_behavior_attribution_cached_advisory()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "below floor" in out
