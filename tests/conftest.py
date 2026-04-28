"""Shared fixtures: isolate config cache + git env for every test."""

from __future__ import annotations

import itertools
import os
import textwrap
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from interlocks import acceptance_symbols
from interlocks import config as interlock_config

_GIT_ENV_LEAKS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
)

_DEFAULT_PROJECT_NAME = "tmpproj"

_DEFAULT_PYPROJECT = textwrap.dedent(
    f"""\
    [project]
    name = "{_DEFAULT_PROJECT_NAME}"
    version = "0.0.0"
    requires-python = ">=3.13"
    """
)

_DEFAULT_SRC_FILES: Mapping[str, str] = {
    f"src/{_DEFAULT_PROJECT_NAME}/__init__.py": '"""Tmp project."""\n',
}

_DEFAULT_TEST_FILES: Mapping[str, str] = {
    "test_smoke.py": '"""Trivial passing test."""\n\n\ndef test_ok() -> None:\n    assert True\n',
}


@pytest.fixture(autouse=True)
def _isolate_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear config cache and scrub GIT_* leaks.

    Without the GIT_* scrub, tests that shell out to `git` inherit `GIT_DIR`
    from an enclosing `git commit` hook and corrupt the outer repo.
    """
    interlock_config.clear_cache()
    acceptance_symbols._clear_cache()
    for var in _GIT_ENV_LEAKS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def _write_tree(root: Path, files: Mapping[str, str]) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


TmpProjectFactory = Callable[..., Path]


@pytest.fixture
def make_tmp_project(tmp_path: Path) -> TmpProjectFactory:
    """Factory fixture that materialises a throwaway project under ``tmp_path``.

    Returns a callable ``make_tmp_project(*, src_files=None, test_files=None, pyproject=None)``
    that writes a project into a fresh sub-directory and returns its root.

    Parameters
    ----------
    src_files:
        Mapping of project-root-relative paths to file contents. When ``None``,
        a minimal ``src/<name>/__init__.py`` stub is written.
    test_files:
        Mapping of ``tests/``-relative paths to file contents. When ``None``, a
        trivial passing ``tests/test_smoke.py`` is written.
    pyproject:
        Full ``pyproject.toml`` content. When ``None``, a minimal default is used.

    Empty dicts are honoured — pass ``{}`` to skip defaults without writing anything.
    """
    seq = itertools.count(1)

    def factory(
        *,
        src_files: Mapping[str, str] | None = None,
        test_files: Mapping[str, str] | None = None,
        pyproject: str | None = None,
    ) -> Path:
        root = tmp_path / f"proj{next(seq)}"
        root.mkdir()
        (root / "pyproject.toml").write_text(
            _DEFAULT_PYPROJECT if pyproject is None else pyproject, encoding="utf-8"
        )
        _write_tree(root, _DEFAULT_SRC_FILES if src_files is None else src_files)
        tests_to_write = _DEFAULT_TEST_FILES if test_files is None else test_files
        if tests_to_write:
            _write_tree(root / "tests", tests_to_write)
        return root

    return factory
