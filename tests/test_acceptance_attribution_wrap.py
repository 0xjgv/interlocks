from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from interlocks.behavior_attribution_trace import (
    EVENTS_ENV,
    PAYLOAD_ENV,
    PLUGIN_NAME,
    SCENARIO_ENV,
)
from interlocks.behavior_coverage import Behavior, BehaviorRegistry
from interlocks.config import InterlockConfig
from interlocks.runner import Task
from interlocks.tasks.acceptance import (
    _behave_task,
    _inject_pytest_plugin,
    _maybe_attribution_task,
    with_attribution_capture,
)


def _cfg(tmp_path: Path) -> InterlockConfig:
    return InterlockConfig(
        project_root=tmp_path,
        src_dir=tmp_path / "pkg",
        test_dir=tmp_path / "tests",
        test_runner="pytest",
        test_invoker="python",
    )


def test_attribution_wrap_injects_pytest_plugin_and_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    task = Task("Acceptance", [sys.executable, "-m", "pytest", "tests", "-q"])
    monkeypatch.setattr(
        "interlocks.tasks.acceptance.behavior_registry_for_config",
        lambda _cfg: BehaviorRegistry((Behavior("b", "task", "B", "pkg.mod:foo"),)),
    )

    wrapped = with_attribution_capture(cfg, task)

    assert "-p" in wrapped.cmd
    assert PLUGIN_NAME in wrapped.cmd
    env = dict(wrapped.env)
    payload = json.loads(env[PAYLOAD_ENV])
    assert payload["evidence_path"] == str(tmp_path / ".interlocks" / "behavior-attribution.json")
    assert payload["public_symbols"] == ["pkg.mod:foo"]


def test_maybe_attribution_task_env_var_off_leaves_task_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("INTERLOCKS_BEHAVIOR_ATTRIBUTION", raising=False)
    task = Task("Acceptance", [sys.executable, "-m", "pytest", "tests", "-q"])

    assert _maybe_attribution_task(_cfg(tmp_path), task) == task


def test_attribution_wrap_leaves_task_unchanged_without_public_symbols(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    task = Task("Acceptance", [sys.executable, "-m", "pytest", "tests", "-q"])
    monkeypatch.setattr(
        "interlocks.tasks.acceptance.behavior_registry_for_config",
        lambda _cfg: BehaviorRegistry((Behavior("b", "task", "B", None),)),
    )

    assert with_attribution_capture(cfg, task) == task


def test_attribution_wrap_does_not_wrap_behave_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    task = _behave_task(cfg, "features")
    monkeypatch.setattr(
        "interlocks.tasks.acceptance.behavior_registry_for_config",
        lambda _cfg: BehaviorRegistry((Behavior("b", "task", "B", "pkg.mod:foo"),)),
    )

    assert with_attribution_capture(cfg, task) == task


def test_pytest_plugin_injection_is_idempotent() -> None:
    cmd = [sys.executable, "-m", "pytest", "-p", PLUGIN_NAME, "tests", "-q"]

    assert _inject_pytest_plugin(cmd) == cmd


def test_attribution_wrap_uses_task_env_without_global_probe_vars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    task = Task("Acceptance", [sys.executable, "-m", "pytest", "tests", "-q"])
    monkeypatch.setattr(
        "interlocks.tasks.acceptance.behavior_registry_for_config",
        lambda _cfg: BehaviorRegistry((Behavior("b", "task", "B", "pkg.mod:foo"),)),
    )

    wrapped = with_attribution_capture(cfg, task)

    env = dict(wrapped.env)
    assert PAYLOAD_ENV in env
    assert SCENARIO_ENV not in env
    assert EVENTS_ENV not in env
