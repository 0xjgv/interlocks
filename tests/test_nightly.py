"""Nightly stage: coverage → audit → mutation; kwarg threading rules."""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest

from interlocks.config import load_config
from interlocks.stages import nightly as nightly_mod


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Swap nightly gates for spies that record call order."""
    calls: list[str] = []
    monkeypatch.setattr(nightly_mod, "cmd_coverage", lambda **_kw: calls.append("coverage"))
    monkeypatch.setattr(nightly_mod, "cmd_properties", lambda **_kw: calls.append("properties"))
    monkeypatch.setattr(nightly_mod, "cmd_audit", lambda **_kw: calls.append("audit"))
    monkeypatch.setattr(nightly_mod, "cmd_mutation", lambda **_kw: calls.append("mutation"))
    return calls


def test_nightly_runs_coverage_then_audit_then_mutation(
    monkeypatch: pytest.MonkeyPatch, spies: list[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "nightly"])

    nightly_mod.cmd_nightly()

    assert spies == ["coverage", "audit", "mutation"]


def test_nightly_json_reports_stage_payload(
    monkeypatch: pytest.MonkeyPatch,
    spies: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "nightly", "--json"])

    nightly_mod.cmd_nightly()

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "nightly"
    assert payload["passed"] is True
    assert payload["gates"] == []
    assert payload["skipped"] == []
    assert spies == ["coverage", "audit", "mutation"]


def test_nightly_passes_allow_network_skip_to_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit runs in network-skip mode so flaky PyPI doesn't fail nightly."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(nightly_mod, "cmd_coverage", lambda **_kw: None)
    monkeypatch.setattr(nightly_mod, "cmd_properties", lambda **_kw: None)
    monkeypatch.setattr(nightly_mod, "cmd_mutation", lambda **_kw: None)

    def fake_audit(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(nightly_mod, "cmd_audit", fake_audit)
    monkeypatch.setattr(sys, "argv", ["interlocks", "nightly"])

    nightly_mod.cmd_nightly()

    assert captured == {"allow_network_skip": True}


def test_nightly_runs_properties_under_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_coverage(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(nightly_mod, "cmd_coverage", fake_coverage)
    monkeypatch.setattr(nightly_mod, "cmd_properties", lambda **_kw: None)
    monkeypatch.setattr(nightly_mod, "cmd_audit", lambda **_kw: None)
    monkeypatch.setattr(nightly_mod, "cmd_mutation", lambda **_kw: None)
    monkeypatch.setattr(sys, "argv", ["interlocks", "nightly"])

    nightly_mod.cmd_nightly()

    assert captured == {"include_properties": True, "property_profile": "nightly"}


def test_nightly_passes_min_score_default_to_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default config → cmd_mutation receives min_score_default=cfg.mutation_min_score."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(nightly_mod, "cmd_coverage", lambda **_kw: None)
    monkeypatch.setattr(nightly_mod, "cmd_properties", lambda **_kw: None)
    monkeypatch.setattr(nightly_mod, "cmd_audit", lambda **_kw: None)

    def fake_mutation(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(nightly_mod, "cmd_mutation", fake_mutation)
    monkeypatch.setattr(sys, "argv", ["interlocks", "nightly"])

    nightly_mod.cmd_nightly()

    assert captured == {"min_score_default": load_config().mutation_min_score}
