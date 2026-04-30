from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path

import pytest

from interlocks.config import clear_cache
from interlocks.tasks.behavior_attribution import (
    cmd_behavior_attribution,
    cmd_behavior_attribution_cached_advisory,
)
from tests.conftest import TmpProjectFactory

_ACTIVE_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "interlocks"
    version = "0.0.0"

    [tool.interlocks]
    features_dir = "tests/features"
    enforce_behavior_attribution = true
    """
)


def test_cmd_behavior_attribution_warn_skips_empty_registry(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = make_tmp_project()
    monkeypatch.chdir(project)

    cmd_behavior_attribution(refresh=False)

    out = capsys.readouterr().out
    assert "[attribution]" in out
    assert "no public symbols declared" in out


def test_cmd_behavior_attribution_ok_with_matching_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _active_registry_project(tmp_path, behavior_id="task-coverage")
    monkeypatch.chdir(project)
    _write_evidence(
        project,
        reached_symbols=["interlocks.tasks.coverage:cmd_coverage"],
    )
    clear_cache()

    cmd_behavior_attribution(refresh=False)

    out = capsys.readouterr().out
    assert "[attribution]" in out
    assert "ok" in out


def test_cmd_behavior_attribution_warns_for_incomplete_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _active_registry_project(tmp_path, behavior_id="task-coverage")
    monkeypatch.chdir(project)
    _write_evidence(project, reached_symbols=[])
    clear_cache()

    with pytest.raises(SystemExit) as exc:
        cmd_behavior_attribution(refresh=False)

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "[attribution]" in out
    assert "mis-attributed" in out
    assert "unresolved behavior symbols" in out


def test_cmd_behavior_attribution_warns_when_not_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _active_registry_project(
        tmp_path,
        behavior_id="task-coverage",
        enforce_behavior_attribution=False,
    )
    monkeypatch.chdir(project)
    _write_evidence(project, reached_symbols=[])
    clear_cache()

    cmd_behavior_attribution(refresh=False)

    out = capsys.readouterr().out
    assert "[attribution]" in out
    assert "mis-attributed" in out


def test_cmd_behavior_attribution_shows_aggregate_trace_as_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _active_registry_project(tmp_path, behavior_id="task-coverage")
    monkeypatch.chdir(project)
    _write_acceptance_trace(project, "interlocks.tasks.coverage:cmd_coverage")
    clear_cache()

    with pytest.raises(SystemExit) as exc:
        cmd_behavior_attribution(refresh=False)

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "aggregate trace fallback" in out
    assert "diagnostic only" in out


def test_cached_advisory_skips_when_evidence_is_not_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _active_registry_project(tmp_path, behavior_id="task-coverage")
    monkeypatch.chdir(project)
    clear_cache()

    cmd_behavior_attribution_cached_advisory()

    out = capsys.readouterr().out
    assert "[attribution]" in out
    assert "no fresh evidence" in out


def _active_registry_project(
    root: Path,
    *,
    behavior_id: str,
    enforce_behavior_attribution: bool = True,
) -> Path:
    (root / "pyproject.toml").write_text(
        _ACTIVE_PYPROJECT.replace(
            "enforce_behavior_attribution = true",
            f"enforce_behavior_attribution = {str(enforce_behavior_attribution).lower()}",
        ),
        encoding="utf-8",
    )
    (root / "tests" / "features").mkdir(parents=True)
    feature_text = (
        f"Feature: behavior\n\n  # req: {behavior_id}\n"
        "  Scenario: covered behavior\n    Given a thing\n"
    )
    (root / "tests" / "features" / "behavior.feature").write_text(
        feature_text,
        encoding="utf-8",
    )
    return root


def _write_evidence(root: Path, *, reached_symbols: list[str]) -> None:
    feature = root / "tests" / "features" / "behavior.feature"
    path = root / ".interlocks" / "behavior-attribution.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps({
            "created_at": time.time(),
            "failure": None,
            "scenarios": [
                {
                    "feature_path": str(feature.resolve()),
                    "scenario_line": 4,
                    "reached_symbols": reached_symbols,
                }
            ],
        })
        + "\n",
        encoding="utf-8",
    )


def _write_acceptance_trace(root: Path, symbol: str) -> None:
    path = root / ".interlocks" / "acceptance-trace.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps({"failure": None, "symbols": [{"symbol": symbol, "reached": True}]}) + "\n",
        encoding="utf-8",
    )
