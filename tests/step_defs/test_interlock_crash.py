"""Step defs for tests/features/interlock_crash.feature.

Drives the CLI via subprocess so the real ``CrashBoundary`` runs and stderr is
observed end-to-end. Mirrors the pattern in ``test_interlock_cli.py``.
"""

from __future__ import annotations

import errno
import os
import pty
import select
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import interlocks

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_crash.feature"))

# Force the in-tree package onto PYTHONPATH so subprocess probes always exercise
# the current source, not a stale editable install. Mirrors test_preflight.py.
_INTERLOCK_PKG_ROOT = str(Path(interlocks.__file__).resolve().parent.parent)


@dataclass
class CrashRun:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class CrashSession:
    """Mutable per-scenario context: project root, cache root, and last run."""

    project_root: Path
    cache_root: Path
    last_run: CrashRun | None = None
    first_url: str | None = None


@pytest.fixture
def crash_session(tmp_path: Path) -> CrashSession:
    project = tmp_path / "project"
    project.mkdir()
    cache = tmp_path / "cache"
    return CrashSession(project_root=project, cache_root=cache)


def _base_env(session: CrashSession) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_INTERLOCK_PKG_ROOT}{os.pathsep}{existing}" if existing else _INTERLOCK_PKG_ROOT
    )
    env["XDG_CACHE_HOME"] = str(session.cache_root)
    env.pop("INTERLOCKS_CRASH_INJECT", None)
    # Suppress browser-open side effects in headless CI; transport prints stderr regardless.
    env.setdefault("BROWSER", "echo")
    return env


def _invoke(session: CrashSession, args: list[str], env: dict[str, str]) -> CrashRun:
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", *args],
        cwd=session.project_root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    run = CrashRun(result.returncode, result.stdout, result.stderr)
    session.last_run = run
    return run


def _read_pty(master_fd: int, proc: subprocess.Popen[bytes]) -> str:
    chunks: list[bytes] = []
    while True:
        ready, _, _ = select.select([master_fd], [], [], 0.1)
        if master_fd in ready:
            try:
                data = os.read(master_fd, 4096)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            if not data:
                break
            chunks.append(data)
        if proc.poll() is not None:
            while True:
                ready, _, _ = select.select([master_fd], [], [], 0)
                if master_fd not in ready:
                    break
                try:
                    data = os.read(master_fd, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not data:
                    break
                chunks.append(data)
            break
    return b"".join(chunks).decode(errors="replace")


def _invoke_interactive(
    session: CrashSession,
    args: list[str],
    env: dict[str, str],
    *,
    response: str,
) -> CrashRun:
    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "interlocks.cli", *args],
            cwd=session.project_root,
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=slave_fd,
            env=env,
        )
        os.close(slave_fd)
        slave_fd = -1
        os.write(master_fd, response.encode())
        stderr = _read_pty(master_fd, proc)
        stdout_bytes = proc.stdout.read() if proc.stdout is not None else b""
        returncode = proc.wait()
    finally:
        if slave_fd != -1:
            os.close(slave_fd)
        os.close(master_fd)
    run = CrashRun(returncode, stdout_bytes.decode(errors="replace"), stderr)
    session.last_run = run
    return run


def _write_minimal_project(root: Path) -> None:
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "crash-fixture"
            version = "0.0.0"

            [tool.interlocks]
            src_dir = "pkg"
            test_dir = "tests"
            """
        ),
        encoding="utf-8",
    )


def _write_no_pyproject_project(root: Path) -> None:
    """No pyproject.toml — preflight raises InterlockUserError (the user-error path)."""
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)


def _write_lint_failure_project(root: Path) -> None:
    """Project with a Python file that ruff will flag — drives a real gate failure."""
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    # Unused import + bare 'except' — ruff E/F codes will fail without auto-fix.
    (root / "pkg" / "broken.py").write_text(
        "import os\nimport sys\n\nx = 1\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "crash-fixture"
            version = "0.0.0"

            [tool.interlocks]
            src_dir = "pkg"
            test_dir = "tests"
            """
        ),
        encoding="utf-8",
    )


# ---------- Given steps ----------


@given(
    parsers.parse('I run "interlocks {subcmd}" with INTERLOCKS_CRASH_INJECT={target}'),
    target_fixture="crash_run",
)
def _run_with_inject(subcmd: str, target: str, crash_session: CrashSession) -> CrashRun:
    _write_minimal_project(crash_session.project_root)
    env = _base_env(crash_session)
    env["INTERLOCKS_CRASH_INJECT"] = target
    return _invoke(crash_session, subcmd.split(), env)


@given(
    parsers.parse(
        'I run "interlocks {subcmd}" with INTERLOCKS_CRASH_INJECT={target} '
        "and answer {answer} to the crash report prompt"
    ),
    target_fixture="crash_run",
)
def _run_with_inject_and_prompt_answer(
    subcmd: str, target: str, answer: str, crash_session: CrashSession
) -> CrashRun:
    _write_minimal_project(crash_session.project_root)
    env = _base_env(crash_session)
    env["INTERLOCKS_CRASH_INJECT"] = target
    response = "\n" if answer == "yes" else "n\n"
    return _invoke_interactive(crash_session, subcmd.split(), env, response=response)


@given("a project without a pyproject.toml")
def _no_pyproject(crash_session: CrashSession) -> None:
    _write_no_pyproject_project(crash_session.project_root)


@given("a project whose lint gate will fail")
def _lint_failure_project(crash_session: CrashSession) -> None:
    _write_lint_failure_project(crash_session.project_root)


@given("the first run printed a GitHub issue URL")
def _first_run_printed_url(crash_run: CrashRun, crash_session: CrashSession) -> None:
    assert "github.com/0xjgv/interlocks/issues/new" in crash_run.stderr, (
        f"first run should have printed URL; stderr was:\n{crash_run.stderr}"
    )
    crash_session.first_url = crash_run.stderr


# ---------- When steps ----------


@when(parsers.parse('I run "interlocks {subcmd}"'))
def _when_run(subcmd: str, crash_session: CrashSession) -> None:
    env = _base_env(crash_session)
    _invoke(crash_session, subcmd.split(), env)


@when(
    parsers.parse(
        'I run "interlocks {subcmd}" again with INTERLOCKS_CRASH_INJECT={target} '
        "and the same cache directory"
    )
)
def _when_repeat_inject(subcmd: str, target: str, crash_session: CrashSession) -> None:
    env = _base_env(crash_session)
    env["INTERLOCKS_CRASH_INJECT"] = target
    _invoke(crash_session, subcmd.split(), env)


# ---------- Then steps ----------


def _last(crash_session: CrashSession, crash_run: CrashRun | None = None) -> CrashRun:
    if crash_run is not None:
        return crash_run
    assert crash_session.last_run is not None, "no run recorded"
    return crash_session.last_run


@then(parsers.parse("the exit code is {code:d}"))
def _exit_code(crash_session: CrashSession, code: int, crash_run: CrashRun | None = None) -> None:
    run = _last(crash_session, crash_run)
    assert run.returncode == code, (
        f"expected exit {code}, got {run.returncode}\nstdout={run.stdout}\nstderr={run.stderr}"
    )


@then("the exit code is not 0")
def _exit_code_nonzero(crash_session: CrashSession, crash_run: CrashRun | None = None) -> None:
    run = _last(crash_session, crash_run)
    assert run.returncode != 0, (
        f"expected non-zero exit; got 0\nstdout={run.stdout}\nstderr={run.stderr}"
    )


@then(parsers.parse('stderr contains "{needle}"'))
def _stderr_contains(
    crash_session: CrashSession, needle: str, crash_run: CrashRun | None = None
) -> None:
    run = _last(crash_session, crash_run)
    assert needle in run.stderr, f"expected {needle!r} in stderr; got:\n{run.stderr}"


@then(parsers.parse('stderr does not contain "{needle}"'))
def _stderr_excludes(
    crash_session: CrashSession, needle: str, crash_run: CrashRun | None = None
) -> None:
    run = _last(crash_session, crash_run)
    assert needle not in run.stderr, f"unexpected {needle!r} in stderr; got:\n{run.stderr}"


@then("a crash file exists in the cache directory")
def _crash_file_exists(crash_session: CrashSession) -> None:
    crashes = crash_session.cache_root / "interlocks" / "crashes"
    files = list(crashes.glob("*.json")) if crashes.exists() else []
    assert files, f"expected a crash JSON file under {crashes}; found none"


@then("no crash file exists in the cache directory")
def _no_crash_file(crash_session: CrashSession) -> None:
    crashes = crash_session.cache_root / "interlocks" / "crashes"
    files = list(crashes.glob("*.json")) if crashes.exists() else []
    assert not files, f"expected no crash files; found: {files}"
