"""Tests for `interlocks version`."""

from __future__ import annotations

import json
import sys

import pytest

from interlocks import __version__
from interlocks.tasks.version import cmd_version


def test_version_human_prints_bare_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "version"])

    cmd_version()

    assert capsys.readouterr().out.strip() == __version__


def test_version_json_reports_cli_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "version", "--json"])

    cmd_version()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "command": "version",
        "passed": True,
        "version": __version__,
    }
