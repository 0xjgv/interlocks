"""Nightly stage: coverage runs before mutation + `--min-score=` injection rules."""

from __future__ import annotations

import sys

import pytest

from harness.config import load_config
from harness.stages import nightly as nightly_mod


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Swap cmd_coverage/cmd_mutation for spies that record call order."""
    calls: list[str] = []
    monkeypatch.setattr(nightly_mod, "cmd_coverage", lambda: calls.append("coverage"))
    monkeypatch.setattr(nightly_mod, "cmd_mutation", lambda: calls.append("mutation"))
    return calls


def test_nightly_runs_coverage_before_mutation(
    monkeypatch: pytest.MonkeyPatch, spies: list[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "nightly"])

    nightly_mod.cmd_nightly()

    assert spies == ["coverage", "mutation"]


def test_nightly_injects_min_score_from_config(
    monkeypatch: pytest.MonkeyPatch, spies: list[str]
) -> None:
    """Default config → `--min-score=<mutation_min_score>` appended to argv."""
    monkeypatch.setattr(sys, "argv", ["harness", "nightly"])

    nightly_mod.cmd_nightly()

    assert sys.argv == ["harness", "nightly", f"--min-score={load_config().mutation_min_score}"]


def test_nightly_preserves_user_supplied_min_score(
    monkeypatch: pytest.MonkeyPatch, spies: list[str]
) -> None:
    """User's `--min-score=` wins: no duplicate injection."""
    monkeypatch.setattr(sys, "argv", ["harness", "nightly", "--min-score=42.5"])

    nightly_mod.cmd_nightly()

    assert sys.argv == ["harness", "nightly", "--min-score=42.5"]
