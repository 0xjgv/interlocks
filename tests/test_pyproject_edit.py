"""Tests for `harness.pyproject_edit.patched_mutmut_paths`."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from harness.pyproject_edit import _rewrite, patched_mutmut_paths

_BASELINE = textwrap.dedent(
    """\
    [project]
    name = "demo"
    version = "0.0.0"

    [tool.ruff]
    line-length = 99

    [tool.mutmut]
    paths_to_mutate = ["harness/"]
    tests_dir = ["tests/"]

    [tool.coverage.run]
    source = ["harness"]
    """
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ─────────────── _rewrite (pure string transform) ─────────────────────


def test_rewrite_replaces_single_line_array() -> None:
    out = _rewrite(_BASELINE, ["harness/foo.py", "harness/bar.py"])
    assert 'paths_to_mutate = ["harness/foo.py", "harness/bar.py"]' in out
    # Unrelated tables + ordering preserved.
    assert out.index("[tool.ruff]") < out.index("[tool.mutmut]") < out.index("[tool.coverage.run]")
    assert 'tests_dir = ["tests/"]' in out
    assert "line-length = 99" in out


def test_rewrite_appends_block_when_missing() -> None:
    src = textwrap.dedent(
        """\
        [project]
        name = "demo"

        [tool.ruff]
        line-length = 99
        """
    )
    out = _rewrite(src, ["harness/x.py"])
    assert out.startswith(src.rstrip("\n"))
    assert out.rstrip().endswith('paths_to_mutate = ["harness/x.py"]')
    assert "[tool.mutmut]" in out


def test_rewrite_inserts_key_when_section_present_but_key_missing() -> None:
    src = textwrap.dedent(
        """\
        [tool.mutmut]
        tests_dir = ["tests/"]

        [tool.coverage.run]
        source = ["harness"]
        """
    )
    out = _rewrite(src, ["harness/"])
    # Inserted inside the mutmut block, before the next header.
    mutmut_idx = out.index("[tool.mutmut]")
    next_header = out.index("[tool.coverage.run]")
    body = out[mutmut_idx:next_header]
    assert 'paths_to_mutate = ["harness/"]' in body
    assert 'tests_dir = ["tests/"]' in body


def test_rewrite_rejects_multiline_array() -> None:
    src = textwrap.dedent(
        """\
        [tool.mutmut]
        paths_to_mutate = [
            "harness/",
        ]
        """
    )
    with pytest.raises(ValueError, match="multi-line"):
        _rewrite(src, ["harness/x.py"])


def test_rewrite_preserves_comments_in_other_tables() -> None:
    src = textwrap.dedent(
        """\
        [tool.ruff]
        # keep me
        line-length = 99

        [tool.mutmut]
        paths_to_mutate = ["harness/"]  # inline comment on original
        tests_dir = ["tests/"]
        """
    )
    out = _rewrite(src, ["harness/x.py"])
    assert "# keep me" in out
    # The paths line is fully replaced (inline comment on that line is acceptable loss).
    assert 'paths_to_mutate = ["harness/x.py"]' in out
    assert 'tests_dir = ["tests/"]' in out


# ─────────────── context-manager behaviour ────────────────────────────


def test_normal_exit_restores_byte_for_byte(tmp_path: Path) -> None:
    target = _write(tmp_path / "pyproject.toml", _BASELINE)
    before = target.read_bytes()
    with patched_mutmut_paths(target, ["harness/changed.py"]):
        inside = target.read_text(encoding="utf-8")
        assert 'paths_to_mutate = ["harness/changed.py"]' in inside
    assert target.read_bytes() == before


def test_exception_inside_with_restores(tmp_path: Path) -> None:
    target = _write(tmp_path / "pyproject.toml", _BASELINE)
    before = target.read_bytes()

    class Boom(Exception):
        pass

    with pytest.raises(Boom), patched_mutmut_paths(target, ["harness/a.py"]):
        assert 'paths_to_mutate = ["harness/a.py"]' in target.read_text(encoding="utf-8")
        raise Boom

    assert target.read_bytes() == before


def test_missing_block_appended_then_removed_cleanly(tmp_path: Path) -> None:
    src = textwrap.dedent(
        """\
        [project]
        name = "demo"
        """
    )
    target = _write(tmp_path / "pyproject.toml", src)
    before = target.read_bytes()
    with patched_mutmut_paths(target, ["harness/x.py"]):
        inside = target.read_text(encoding="utf-8")
        assert "[tool.mutmut]" in inside
        assert 'paths_to_mutate = ["harness/x.py"]' in inside
    # Original had no [tool.mutmut] — restored bytes must not contain it.
    assert target.read_bytes() == before
    assert "[tool.mutmut]" not in target.read_text(encoding="utf-8")


def test_signal_handlers_restored_on_exit(tmp_path: Path) -> None:
    target = _write(tmp_path / "pyproject.toml", _BASELINE)
    before_term = signal.getsignal(signal.SIGTERM)
    before_int = signal.getsignal(signal.SIGINT)
    with patched_mutmut_paths(target, ["harness/x.py"]):
        assert signal.getsignal(signal.SIGTERM) is not before_term
    assert signal.getsignal(signal.SIGTERM) == before_term
    assert signal.getsignal(signal.SIGINT) == before_int


# ─────────────── SIGTERM subprocess test ──────────────────────────────


_CHILD_SCRIPT = textwrap.dedent(
    """\
    import os
    import sys
    import time
    from pathlib import Path

    sys.path.insert(0, {repo_root!r})
    from harness.pyproject_edit import patched_mutmut_paths

    target = Path({target!r})
    ready = Path({ready!r})
    with patched_mutmut_paths(target, ["harness/patched.py"]):
        ready.write_text("ok", encoding="utf-8")
        # Wait for SIGTERM; if it never comes, exit naturally after a bounded wait.
        for _ in range(300):
            time.sleep(0.1)
    """
)


def test_sigterm_mid_with_restores(tmp_path: Path) -> None:
    target = _write(tmp_path / "pyproject.toml", _BASELINE)
    before = target.read_bytes()
    ready = tmp_path / "ready"
    repo_root = Path(__file__).resolve().parents[1]
    script = _CHILD_SCRIPT.format(
        repo_root=str(repo_root),
        target=str(target),
        ready=str(ready),
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10.0
        while not ready.exists() and time.monotonic() < deadline:
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                pytest.fail(f"child exited early: {stdout!r} / {stderr!r}")
            time.sleep(0.05)
        assert ready.exists(), "child never signalled ready"
        # Sanity: while the child holds the with-block, the file is patched.
        assert b'"harness/patched.py"' in target.read_bytes()
        os.kill(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("child did not exit after SIGTERM")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    assert target.read_bytes() == before
