"""Tests for shared budgeted-mutation stage glue."""

from __future__ import annotations

import sys

import pytest

from interlocks.skip import SkipPolicy
from interlocks.stages import _budgeted as budgeted_mod


def test_budgeted_mutation_uses_current_interpreter_for_noop_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_cmd_fix_optimize(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(budgeted_mod, "arg_flag_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(budgeted_mod, "arg_value", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(budgeted_mod, "cmd_fix_optimize", fake_cmd_fix_optimize)

    budgeted_mod.run_budgeted_mutation(
        base="HEAD",
        emit_legacy_rows=False,
        skip_policy=SkipPolicy(frozenset(), "cli"),
    )

    assert captured["verify_cmd"] == (sys.executable, "-c", "pass")
