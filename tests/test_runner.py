"""Unit tests for harness.runner — Task / run_tasks parallel executor semantics."""

from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path

import pytest

from harness.runner import Task, run_tasks

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_WAIT_FOR_MARKER = (
    "import pathlib, time\n"
    "p = pathlib.Path({path!r})\n"
    "while not p.exists():\n"
    "    time.sleep(0.01)\n"
)
_SIGNAL_MARKER = "import pathlib; pathlib.Path({path!r}).touch()\n"


def _strip(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _python_task(description: str, code: str, *, test_summary: bool = False) -> Task:
    """Task whose cmd is the running interpreter executing ``code``."""
    return Task(description, [sys.executable, "-c", code], test_summary=test_summary)


def test_run_tasks_all_pass_streams_ok_and_no_exit(capsys: pytest.CaptureFixture[str]) -> None:
    run_tasks([
        _python_task("Alpha", "print('a')"),
        _python_task("Bravo", "print('b')"),
    ])
    out = _strip(capsys.readouterr().out)
    assert "✓ Alpha" in out
    assert "✓ Bravo" in out
    assert "✗" not in out


def test_run_tasks_single_failure_exits_with_subprocess_returncode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    tasks = [
        _python_task("Good", "print('ok')"),
        _python_task("Bad", "import sys; sys.stderr.write('boom\\n'); sys.exit(7)"),
    ]
    with pytest.raises(SystemExit) as exc:
        run_tasks(tasks)
    assert exc.value.code == 7
    out = _strip(capsys.readouterr().out)
    assert "✓ Good" in out
    assert "✗ Bad" in out
    assert "Bad output" in out
    assert "boom" in out


def test_run_tasks_multi_failure_uses_first_in_list_returncode(tmp_path: Path) -> None:
    """Deterministic exit code = first-failing-task-in-input-order, not completion order."""
    marker = tmp_path / "second_done"
    first_code = _WAIT_FOR_MARKER.format(path=str(marker)) + "import sys; sys.exit(3)"
    second_code = _SIGNAL_MARKER.format(path=str(marker)) + "import sys; sys.exit(9)"
    tasks = [
        _python_task("First", first_code),
        _python_task("Second", second_code),
    ]
    with pytest.raises(SystemExit) as exc:
        run_tasks(tasks)
    assert exc.value.code == 3


def test_run_tasks_streams_in_completion_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fast task should emit its ✓ line before the slow task's ✓ line."""
    marker = tmp_path / "fast_done"
    slow_code = _WAIT_FOR_MARKER.format(path=str(marker))
    fast_code = _SIGNAL_MARKER.format(path=str(marker))
    tasks = [
        _python_task("Slow", slow_code),
        _python_task("Fast", fast_code),
    ]
    run_tasks(tasks)
    out = _strip(capsys.readouterr().out)
    fast_pos = out.find("✓ Fast")
    slow_pos = out.find("✓ Slow")
    assert fast_pos != -1 and slow_pos != -1
    assert fast_pos < slow_pos, f"expected Fast before Slow:\n{out}"


def test_run_tasks_locks_prevent_interleaved_lines(capsys: pytest.CaptureFixture[str]) -> None:
    """Every status line starts at the line boundary with the expected prefix — no torn writes."""
    tasks = [_python_task(f"Task{i}", "pass") for i in range(8)]
    run_tasks(tasks)
    out = _strip(capsys.readouterr().out)
    for line in out.splitlines():
        if not line.strip():
            continue
        assert line.lstrip().startswith(("✓", "✗")), f"torn or unexpected line: {line!r}"


def test_run_tasks_empty_is_noop(capsys: pytest.CaptureFixture[str]) -> None:
    run_tasks([])
    assert capsys.readouterr().out == ""


def test_run_tasks_test_summary_extracts_count(capsys: pytest.CaptureFixture[str]) -> None:
    # Emulate unittest's "Ran 3 tests in 0.012s" trailer
    code = textwrap.dedent(
        """
        import sys
        sys.stderr.write('Ran 3 tests in 0.012s\\n')
        sys.stderr.write('OK\\n')
        """
    )
    run_tasks([Task("Unit tests", [sys.executable, "-c", code], test_summary=True)])
    out = _strip(capsys.readouterr().out)
    assert "✓ Unit tests (3 tests, 0.012s)" in out


def test_run_tasks_dumps_each_failure_with_title(capsys: pytest.CaptureFixture[str]) -> None:
    tasks = [
        _python_task("TaskA", "import sys; sys.stderr.write('A_ERR\\n'); sys.exit(1)"),
        _python_task("TaskB", "import sys; sys.stderr.write('B_ERR\\n'); sys.exit(1)"),
    ]
    with pytest.raises(SystemExit):
        run_tasks(tasks)
    out = _strip(capsys.readouterr().out)
    assert "--- TaskA output ---" in out
    assert "--- TaskB output ---" in out
    assert "A_ERR" in out
    assert "B_ERR" in out


def test_task_pre_cmds_run_before_main_command(tmp_path: Path) -> None:
    """Pre-commands run first; failure in pre_cmds short-circuits the main cmd."""
    marker = tmp_path / "touched.txt"
    pre = [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('1'); raise SystemExit(5)"]
    main = [sys.executable, "-c", "raise SystemExit(0)"]
    task = Task("Compound", main, pre_cmds=(pre,))
    with pytest.raises(SystemExit) as exc:
        run_tasks([task])
    assert exc.value.code == 5
    assert marker.read_text() == "1"


def test_run_tasks_preserves_output_on_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """Stdout and stderr both surface in the failure dump block."""
    task = _python_task(
        "WithOutput",
        "import sys; sys.stdout.write('OUT\\n'); sys.stderr.write('ERR\\n'); sys.exit(2)",
    )
    with pytest.raises(SystemExit):
        run_tasks([task])
    out = _strip(capsys.readouterr().out)
    assert "OUT" in out
    assert "ERR" in out
