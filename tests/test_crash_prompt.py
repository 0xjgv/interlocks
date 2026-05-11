"""Unit tests for the interactive crash-report prompt."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from interlocks.crash.prompt import prompt_for_report


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class _BrokenTtyStringIO(_TtyStringIO):
    def readline(self, *_args: object, **_kwargs: object) -> str:
        raise OSError("stdin closed")


def test_enter_reports_by_default() -> None:
    stderr = _TtyStringIO()

    decision = prompt_for_report(stdin=_TtyStringIO("\n"), stderr=stderr)

    assert decision == "report"
    assert "Report this crash" in stderr.getvalue()


def test_yes_reports() -> None:
    assert prompt_for_report(stdin=_TtyStringIO("yes\n"), stderr=_TtyStringIO()) == "report"


def test_no_skips() -> None:
    stderr = _TtyStringIO()

    decision = prompt_for_report(stdin=_TtyStringIO("n\n"), stderr=stderr)

    assert decision == "skip"
    assert "Crash report skipped." in stderr.getvalue()


def test_invalid_response_skips() -> None:
    stderr = _TtyStringIO()

    decision = prompt_for_report(stdin=_TtyStringIO("maybe\n"), stderr=stderr)

    assert decision == "skip"
    assert "unrecognized response" in stderr.getvalue()


def test_non_interactive_stdin_is_unavailable() -> None:
    assert prompt_for_report(stdin=StringIO("\n"), stderr=_TtyStringIO()) == "unavailable"


def test_non_interactive_stderr_is_unavailable() -> None:
    assert prompt_for_report(stdin=_TtyStringIO("\n"), stderr=StringIO()) == "unavailable"


def test_prompt_prints_local_path(tmp_path: Path) -> None:
    stderr = _TtyStringIO()
    local_path = tmp_path / "crash.json"

    decision = prompt_for_report(stdin=_TtyStringIO("n\n"), stderr=stderr, local_path=local_path)

    assert decision == "skip"
    assert f"Local crash file: {local_path}" in stderr.getvalue()


def test_read_error_is_unavailable() -> None:
    assert prompt_for_report(stdin=_BrokenTtyStringIO(), stderr=_TtyStringIO()) == "unavailable"


def test_eof_is_unavailable() -> None:
    assert prompt_for_report(stdin=_TtyStringIO(""), stderr=_TtyStringIO()) == "unavailable"
