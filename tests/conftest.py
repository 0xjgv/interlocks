"""Shared fixtures: isolate config cache + git env for every test."""

from __future__ import annotations

import os

import pytest

from harness import config as harness_config

_GIT_ENV_LEAKS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
)


@pytest.fixture(autouse=True)
def _isolate_test_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Clear config cache, scrub GIT_* leaks, and pin XDG_CONFIG_HOME at an empty dir.

    Without the GIT_* scrub, tests that shell out to `git` inherit `GIT_DIR`
    from an enclosing `git commit` hook and corrupt the outer repo.
    """
    harness_config.clear_cache()
    empty = tmp_path_factory.mktemp("empty_xdg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(empty))
    for var in _GIT_ENV_LEAKS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
