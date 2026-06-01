"""Generated-input checks for standalone lint JSON helpers."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.lint import (
    _progressive_lint_payload,
    _progressive_lint_summary,
    _ProgressiveLintSummary,
)


@given(
    count=st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000)),
    cap=st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000)),
    status=st.sampled_from(["ok", "failed", "skipped"]),
    passed=st.booleans(),
    reason=st.one_of(st.none(), st.text()),
    examples=st.lists(st.text(), max_size=20),
    omitted=st.integers(min_value=0, max_value=1_000_000),
)
def test_progressive_lint_payload_fields_are_stable(
    count: int | None,
    cap: int | None,
    status: str,
    passed: bool,
    reason: str | None,
    examples: list[str],
    omitted: int,
) -> None:
    summary = _ProgressiveLintSummary(
        count=count,
        cap=cap,
        status=status,
        passed=passed,
        reason=reason,
        examples=tuple(examples),
        omitted=omitted,
    )
    payload = _progressive_lint_payload(summary)

    assert payload["command"] == "lint"
    assert payload["passed"] is passed
    assert payload["mode"] == "progressive"
    assert payload["status"] == status
    assert payload["violations"] == count
    assert payload["limit"] == cap
    assert ("reason" in payload) is (reason is not None)
    assert ("examples" in payload) is bool(examples)
    assert ("omitted" in payload) is (omitted > 0)
    assert ("next_actions" in payload) is (not passed)


@given(
    returncode=st.integers(),
    stdout=st.text(),
    cap=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
)
def test_progressive_lint_summary_derives_verdict_from_ruff_result(
    returncode: int,
    stdout: str,
    cap: int | None,
) -> None:
    summary = _progressive_lint_summary(returncode, stdout, cap)

    if returncode not in (0, 1):
        assert summary.count is None
        assert summary.cap == cap
        assert summary.status == "skipped"
        assert summary.passed is True
        assert summary.reason == f"ruff rc={returncode}"
        assert summary.examples == ()
        assert summary.omitted == 0
        return

    lines = tuple(line for line in stdout.splitlines() if line.strip())
    passed = cap is None or len(lines) <= cap
    assert summary.count == len(lines)
    assert summary.cap == cap
    assert summary.status == ("ok" if passed else "failed")
    assert summary.passed is passed
    assert summary.reason is None
    assert summary.examples == (lines[:10] if not passed else ())
    assert summary.omitted == (max(0, len(lines) - 10) if not passed else 0)


_NONBLANK_LINE = st.text(
    alphabet=st.characters(blacklist_characters="\r\n", blacklist_categories=("Cc", "Cs")),
    min_size=1,
    max_size=80,
).filter(lambda line: bool(line.strip()))


@given(lines=st.lists(_NONBLANK_LINE, min_size=11, max_size=40))
def test_progressive_lint_summary_caps_failure_examples(lines: list[str]) -> None:
    stdout = "\n".join(lines)

    summary = _progressive_lint_summary(1, stdout, cap=0)

    assert summary.status == "failed"
    assert summary.examples == tuple(lines[:10])
    assert summary.omitted == len(lines) - 10
