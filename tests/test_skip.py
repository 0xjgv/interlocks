from __future__ import annotations

import sys

from interlocks.config import SKIP_LABELS
from interlocks.skip import _command_from_argv, _known_labels, _skip_usage_payload


def test_known_labels_uses_comma_delimited_sorted_domain() -> None:
    assert _known_labels() == ",".join(sorted(SKIP_LABELS))


def test_skip_usage_payload_has_exact_json_contract() -> None:
    payload = _skip_usage_payload("bad skip", command=None)

    assert payload == {
        "command": "interlocks",
        "error": "bad skip",
        "usage": "usage: --skip=<label>[,<label>...]",
        "known_labels": sorted(SKIP_LABELS),
    }


def test_skip_usage_payload_preserves_detected_command() -> None:
    payload = _skip_usage_payload("bad skip", command="check")

    assert payload["command"] == "check"


def test_command_from_argv_ignores_flags_before_command(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "--json", "--verbose", "check", "--skip=nope"])

    assert _command_from_argv() == "check"


def test_command_from_argv_returns_none_for_flag_only_argv(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["interlocks", "--json", "--skip=nope"])

    assert _command_from_argv() is None
