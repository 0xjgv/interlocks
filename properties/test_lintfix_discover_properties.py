"""Property tests for Ruff diagnostic discovery parsing."""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass, field
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix import discover as discover_mod
from interlocks.lintfix.discover import (
    RuleCandidate,
    _bucket_diagnostic,
    _candidates_from_buckets,
    _RuleBucket,
    discover_fixable_rules,
    parse_diagnostics,
)

_RULE_CODE_RE = re.compile(r"[A-Z][A-Z0-9]*[0-9]")
_JSON_SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-100, max_value=100),
    st.text(max_size=12),
)
_VALID_RULE_CODE = st.text(
    alphabet=string.ascii_uppercase + string.digits,
    min_size=2,
    max_size=8,
).filter(lambda value: value[0].isalpha() and value[-1].isdigit())
_FILENAMES = st.text(max_size=20)


@dataclass
class _ExpectedBucket:
    count: int = 0
    has_safe: bool = False
    has_unsafe: bool = False
    files: set[str] = field(default_factory=set)


@st.composite
def _diagnostic_dicts(draw: st.DrawFn) -> dict[str, object]:
    entry: dict[str, object] = {}
    if draw(st.booleans()):
        entry["code"] = draw(st.one_of(_JSON_SCALAR, _VALID_RULE_CODE))
    if draw(st.booleans()):
        entry["filename"] = draw(_JSON_SCALAR)
    if draw(st.booleans()):
        entry["fix"] = draw(
            st.one_of(
                st.fixed_dictionaries({"applicability": _JSON_SCALAR}),
                _JSON_SCALAR,
                st.lists(_JSON_SCALAR, max_size=3),
            )
        )
    return entry


_PAYLOAD_ENTRIES = st.one_of(
    _diagnostic_dicts(),
    _JSON_SCALAR,
    st.lists(_JSON_SCALAR, max_size=3),
)


def _expected_candidates(payload: list[object]) -> tuple[RuleCandidate, ...]:
    buckets: dict[str, _ExpectedBucket] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        code = _valid_rule_code(item.get("code"))
        fix = item.get("fix")
        if code is None or not isinstance(fix, dict):
            continue
        bucket = buckets.setdefault(code, _ExpectedBucket())
        bucket.count += 1
        filename = item.get("filename")
        if isinstance(filename, str):
            bucket.files.add(filename)
        applicability = fix.get("applicability")
        if applicability == "safe":
            bucket.has_safe = True
        elif applicability == "unsafe":
            bucket.has_unsafe = True
    return tuple(
        RuleCandidate(
            rule=code,
            files=tuple(sorted(bucket.files)),
            has_safe_fix=bucket.has_safe,
            has_unsafe_fix=bucket.has_unsafe,
            diagnostic_count=bucket.count,
        )
        for code, bucket in sorted(buckets.items())
    )


def _valid_rule_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip()
    if _RULE_CODE_RE.fullmatch(code):
        return code
    return None


@given(
    code=_VALID_RULE_CODE,
    filename=st.one_of(_FILENAMES, _JSON_SCALAR),
    applicability=st.one_of(st.sampled_from(["safe", "unsafe"]), _JSON_SCALAR),
)
def test_bucket_diagnostic_records_valid_fixable_entries(
    code: str,
    filename: object,
    applicability: object,
) -> None:
    buckets: dict[str, _RuleBucket] = {}

    _bucket_diagnostic(
        buckets,
        {"code": f" {code} ", "filename": filename, "fix": {"applicability": applicability}},
    )

    bucket = buckets[code]
    assert bucket.count == 1
    assert bucket.files == ({filename} if isinstance(filename, str) else set())
    assert bucket.has_safe is (applicability == "safe")
    assert bucket.has_unsafe is (applicability == "unsafe")


@given(raw=st.one_of(_JSON_SCALAR, st.lists(_JSON_SCALAR, max_size=3)))
def test_bucket_diagnostic_ignores_non_fixable_or_invalid_entries(raw: object) -> None:
    buckets: dict[str, _RuleBucket] = {}

    _bucket_diagnostic(buckets, raw)
    _bucket_diagnostic(buckets, {"code": "not-a-rule", "fix": {"applicability": "safe"}})
    _bucket_diagnostic(buckets, {"code": "I001", "fix": None})

    assert buckets == {}


@given(
    rows=st.dictionaries(
        _VALID_RULE_CODE,
        st.tuples(
            st.integers(min_value=0, max_value=100),
            st.booleans(),
            st.booleans(),
            st.sets(_FILENAMES, max_size=5),
        ),
        max_size=20,
    )
)
def test_candidates_from_buckets_are_sorted_plain_snapshots(
    rows: dict[str, tuple[int, bool, bool, set[str]]],
) -> None:
    buckets = {
        code: _RuleBucket(
            count=count,
            has_safe=has_safe,
            has_unsafe=has_unsafe,
            files=set(files),
        )
        for code, (count, has_safe, has_unsafe, files) in rows.items()
    }

    candidates = _candidates_from_buckets(buckets)

    assert [candidate.rule for candidate in candidates] == sorted(rows)
    assert candidates == tuple(
        RuleCandidate(
            rule=code,
            files=tuple(sorted(files)),
            has_safe_fix=has_safe,
            has_unsafe_fix=has_unsafe,
            diagnostic_count=count,
        )
        for code, (count, has_safe, has_unsafe, files) in sorted(rows.items())
    )


def test_candidates_from_buckets_returns_empty_tuple_for_no_buckets() -> None:
    assert _candidates_from_buckets({}) == ()


@given(st.lists(_PAYLOAD_ENTRIES, max_size=40))
def test_ruff_diagnostic_parser_matches_generated_reference(payload: list[object]) -> None:
    assert parse_diagnostics(json.dumps(payload)) == _expected_candidates(payload)


@given(st.text(max_size=20))
def test_ruff_diagnostic_parser_rejects_invalid_rule_codes(code: str) -> None:
    if _valid_rule_code(code) is not None:
        return

    raw = json.dumps([{"code": code, "filename": "example.py", "fix": {"applicability": "safe"}}])

    assert parse_diagnostics(raw) == ()


@given(
    files=st.lists(_FILENAMES, min_size=1, max_size=5, unique=True).map(tuple),
    payload=st.lists(_PAYLOAD_ENTRIES, max_size=20),
    returncode=st.integers(min_value=0, max_value=4),
    stderr=st.text(max_size=40),
)
def test_discover_fixable_rules_parses_low_ruff_returncodes(
    files: tuple[str, ...],
    payload: list[object],
    returncode: int,
    stderr: str,
) -> None:
    raw = json.dumps(payload)
    calls: list[list[str]] = []

    class FakeConfig:
        def tool_version(self, name: str) -> str:
            assert name == "ruff"
            return "9.9.9"

    def fake_uvx_tool(*args: str, version: str | None = None) -> list[str]:
        assert version == "9.9.9"
        return ["uvx", *args]

    def fake_capture(cmd: list[str]) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(stdout=raw, stderr=stderr, returncode=returncode)

    def fake_load_config() -> FakeConfig:
        return FakeConfig()

    def fake_ruff_config_args() -> list[str]:
        return ["--config", "pyproject.toml"]

    original_load_config = discover_mod.load_config
    original_uvx_tool = discover_mod.uvx_tool
    original_ruff_config_args = discover_mod.ruff_config_args
    original_capture = discover_mod.capture
    discover_mod.load_config = fake_load_config  # type: ignore[assignment]
    discover_mod.uvx_tool = fake_uvx_tool  # type: ignore[assignment]
    discover_mod.ruff_config_args = fake_ruff_config_args  # type: ignore[assignment]
    discover_mod.capture = fake_capture  # type: ignore[assignment]
    try:
        result = discover_fixable_rules(files)
    finally:
        discover_mod.load_config = original_load_config
        discover_mod.uvx_tool = original_uvx_tool
        discover_mod.ruff_config_args = original_ruff_config_args
        discover_mod.capture = original_capture

    assert calls == [
        [
            "uvx",
            "ruff",
            "check",
            "--output-format=json",
            "--force-exclude",
            "--config",
            "pyproject.toml",
            *files,
        ]
    ]
    assert result.returncode == returncode
    assert result.stderr == stderr
    assert result.candidates == (() if returncode >= 2 else parse_diagnostics(raw))
