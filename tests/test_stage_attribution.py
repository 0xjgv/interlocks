from __future__ import annotations

from pathlib import Path

import pytest

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


def _acceptance_off() -> object:
    class AcceptanceOff:
        is_required_failure = False
        status = object()

    return AcceptanceOff()
