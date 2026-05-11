from __future__ import annotations

import pytest

from interlocks import __version__
from interlocks.tasks.version import cmd_version, task_version


def test_task_version_has_no_gate_task() -> None:
    assert task_version() is None


def test_cmd_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    cmd_version()

    assert capsys.readouterr().out == f"{__version__}\n"
