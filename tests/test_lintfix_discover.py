"""Unit tests for ``interlocks.lintfix.discover``."""

from __future__ import annotations

import json

from interlocks.lintfix import discover


def test_parse_groups_diagnostics_by_rule() -> None:
    raw = json.dumps([
        {
            "code": "I001",
            "filename": "/abs/a.py",
            "fix": {"applicability": "safe", "edits": []},
        },
        {
            "code": "I001",
            "filename": "/abs/b.py",
            "fix": {"applicability": "safe", "edits": []},
        },
        {
            "code": "F401",
            "filename": "/abs/a.py",
            "fix": {"applicability": "safe", "edits": []},
        },
    ])
    out = discover.parse_diagnostics(raw)
    rules = {c.rule: c for c in out}
    assert set(rules) == {"I001", "F401"}
    assert rules["I001"].files == ("/abs/a.py", "/abs/b.py")
    assert rules["I001"].diagnostic_count == 2
    assert rules["I001"].has_safe_fix
    assert not rules["I001"].has_unsafe_fix


def test_parse_skips_diagnostics_without_fix() -> None:
    raw = json.dumps([
        {"code": "E501", "filename": "/abs/a.py", "fix": None},
        {"code": "I001", "filename": "/abs/a.py", "fix": {"applicability": "safe"}},
    ])
    out = discover.parse_diagnostics(raw)
    assert {c.rule for c in out} == {"I001"}


def test_parse_tags_unsafe_applicability() -> None:
    raw = json.dumps([
        {"code": "T201", "filename": "/abs/a.py", "fix": {"applicability": "unsafe"}},
        {"code": "T201", "filename": "/abs/b.py", "fix": {"applicability": "unsafe"}},
    ])
    out = discover.parse_diagnostics(raw)
    [c] = out
    assert c.rule == "T201"
    assert c.has_unsafe_fix
    assert not c.has_safe_fix


def test_parse_handles_mixed_safe_and_unsafe() -> None:
    raw = json.dumps([
        {"code": "UP007", "filename": "/abs/a.py", "fix": {"applicability": "safe"}},
        {"code": "UP007", "filename": "/abs/b.py", "fix": {"applicability": "unsafe"}},
    ])
    out = discover.parse_diagnostics(raw)
    [c] = out
    assert c.has_safe_fix and c.has_unsafe_fix


def test_parse_empty_returns_empty_tuple() -> None:
    assert discover.parse_diagnostics("") == ()
    assert discover.parse_diagnostics("   \n") == ()


def test_parse_malformed_json_returns_empty_tuple() -> None:
    assert discover.parse_diagnostics("not json") == ()


def test_parse_non_list_payload_returns_empty_tuple() -> None:
    assert discover.parse_diagnostics(json.dumps({"oops": "object"})) == ()


def test_discover_returns_empty_when_no_files() -> None:
    result = discover.discover_fixable_rules(())
    assert result.candidates == ()
    assert result.returncode == 0


def test_parse_results_are_sorted_by_rule_code() -> None:
    raw = json.dumps([
        {"code": "W292", "filename": "/x.py", "fix": {"applicability": "safe"}},
        {"code": "I001", "filename": "/x.py", "fix": {"applicability": "safe"}},
        {"code": "F401", "filename": "/x.py", "fix": {"applicability": "safe"}},
    ])
    out = discover.parse_diagnostics(raw)
    assert [c.rule for c in out] == ["F401", "I001", "W292"]
