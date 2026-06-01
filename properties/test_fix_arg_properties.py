"""Property tests for lintfix command argument resolution."""

from __future__ import annotations

import shlex
import sys
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks import fix_cli, fix_optimize, fix_rule

_WORDS = st.from_regex(r"[A-Za-z0-9_./:-]{1,20}", fullmatch=True)
_VERIFY_CMDS = st.lists(_WORDS, min_size=1, max_size=5).map(tuple)


def _argv(command: str, *args: str) -> list[str]:
    return ["interlocks", command, *args]


@given(rule=_WORDS, base=_WORDS, budget=_WORDS, apply=st.booleans(), verify_cmd=_VERIFY_CMDS)
def test_fix_rule_explicit_args_override_argv(
    rule: str,
    base: str,
    budget: str,
    apply: bool,
    verify_cmd: tuple[str, ...],
) -> None:
    with patch.object(
        sys,
        "argv",
        _argv("fix-rule", "--rule=ARGV", "--apply", "--base=argv", "--budget=argv"),
    ):
        resolved = fix_rule._resolve_args(rule, apply, base, budget, verify_cmd)

    assert resolved == fix_rule._FixRuleArgs(rule, apply, base, budget, verify_cmd)


@given(apply=st.booleans())
def test_fix_rule_explicit_falsey_values_still_override_argv(apply: bool) -> None:
    with patch.object(
        sys,
        "argv",
        _argv("fix-rule", "--rule=ARGV", "--apply", "--base=argv", "--budget=argv"),
    ):
        resolved = fix_rule._resolve_args("", apply, "", "", ())

    assert resolved == fix_rule._FixRuleArgs("", apply, "", "", ())


@given(verify_cmd=_VERIFY_CMDS)
def test_fix_rule_verify_cmd_splits_shell_words(verify_cmd: tuple[str, ...]) -> None:
    raw = " ".join(shlex.quote(word) for word in verify_cmd)

    with patch.object(sys, "argv", _argv("fix-rule", f"--verify-cmd={raw}")):
        assert fix_cli.verify_cmd_from_argv("fix-rule") == verify_cmd


@given(raw=st.text(max_size=80))
def test_fix_rule_verify_cmd_rejects_or_resolves_without_traceback(raw: str) -> None:
    with (
        redirect_stderr(StringIO()),
        patch.object(sys, "argv", _argv("fix-rule", f"--verify-cmd={raw}")),
    ):
        try:
            resolved = fix_cli.verify_cmd_from_argv("fix-rule")
        except SystemExit as exc:
            assert exc.code == 2
        else:
            assert isinstance(resolved, tuple)


@given(
    base=_WORDS,
    budget=_WORDS,
    apply=st.booleans(),
    stats_path=st.text(max_size=30),
    verify_cmd=_VERIFY_CMDS,
)
def test_fix_optimize_explicit_options_override_argv(
    base: str,
    budget: str,
    apply: bool,
    stats_path: str,
    verify_cmd: tuple[str, ...],
) -> None:
    with patch.object(
        sys,
        "argv",
        _argv(
            "fix-optimize",
            "--base=argv",
            "--budget=argv",
            "--apply",
            "--annotate",
            "--metrics",
        ),
    ):
        resolved = fix_optimize._resolve_options(base, budget, apply, stats_path, verify_cmd)

    assert resolved.base == base
    assert resolved.budget_name == budget
    assert resolved.apply is apply
    assert resolved.stats_path == stats_path
    assert resolved.verify_cmd == verify_cmd
    assert resolved.annotate is True
    assert resolved.metrics is True


@given(apply=st.booleans())
def test_fix_optimize_explicit_falsey_options_still_override_argv(apply: bool) -> None:
    with patch.object(
        sys,
        "argv",
        _argv(
            "fix-optimize",
            "--base=argv",
            "--budget=argv",
            "--apply",
            "--stats=argv",
        ),
    ):
        resolved = fix_optimize._resolve_options("", "", apply, "", ())

    assert resolved.base == ""
    assert resolved.budget_name == ""
    assert resolved.apply is apply
    assert resolved.stats_path == ""
    assert resolved.verify_cmd == ()


@given(verify_cmd=_VERIFY_CMDS)
def test_fix_optimize_verify_cmd_splits_shell_words(verify_cmd: tuple[str, ...]) -> None:
    raw = " ".join(shlex.quote(word) for word in verify_cmd)

    with patch.object(sys, "argv", _argv("fix-optimize", f"--verify-cmd={raw}")):
        assert fix_cli.verify_cmd_from_argv("fix-optimize") == verify_cmd


@given(raw=st.text(max_size=80))
def test_fix_optimize_verify_cmd_rejects_or_resolves_without_traceback(raw: str) -> None:
    with (
        redirect_stderr(StringIO()),
        patch.object(sys, "argv", _argv("fix-optimize", f"--verify-cmd={raw}")),
    ):
        try:
            resolved = fix_cli.verify_cmd_from_argv("fix-optimize")
        except SystemExit as exc:
            assert exc.code == 2
        else:
            assert isinstance(resolved, tuple)
