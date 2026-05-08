"""Integration test for `interlocks audit` (pip-audit on deps)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from interlocks.defaults.tools import default_pin
from interlocks.runner import Task, uvx_tool
from interlocks.tasks import audit as audit_mod

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "audit-probe"
    version = "0.0.1"
    requires-python = ">=3.11"
    dependencies = []

    [build-system]
    requires = ["setuptools>=61"]
    build-backend = "setuptools.build_meta"
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Minimal project with no deps — pip-audit has nothing to scan."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    return tmp_path


@pytest.mark.slow
def test_audit_clean_deps_passes(tmp_project: Path) -> None:
    """pip-audit against a project with no deps should report no vulnerabilities."""
    result = subprocess.run(
        [sys.executable, "-m", "interlocks.cli", "audit"],
        cwd=tmp_project,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    # Either clean exit, or — if the index is unreachable — the known-safe message.
    assert result.returncode == 0 or "No known vulnerabilities" in output, (
        f"audit failed unexpectedly: rc={result.returncode}\n{output}"
    )


def test_audit_invokes_pip_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fast in-process check: cmd_audit builds a uvx-dispatched pip-audit Task and runs it."""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "audit-probe"
            version = "0.0.1"
            dependencies = ["requests"]
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    captured: dict[str, Task] = {}

    def fake_run(task: Task, **_: object) -> None:
        captured["task"] = task

    monkeypatch.setattr(audit_mod, "run", fake_run)
    audit_mod.cmd_audit()

    task = captured["task"]
    assert task.description == "Dep audit"
    assert task.cmd == uvx_tool("pip-audit", ".", version=default_pin("pip-audit"))


def test_audit_prints_configured_severity_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "audit-policy"
            version = "0.0.0"

            [tool.interlocks]
            audit_severity_threshold = "high"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        audit_mod,
        "_pip_audit_task",
        lambda: Task("Dep audit", [sys.executable, "-c", "pass"], label="audit"),
    )
    monkeypatch.setattr(audit_mod, "run", lambda _task: None)

    audit_mod.cmd_audit()

    assert "Audit severity policy: fail on high+ vulnerabilities" in capsys.readouterr().out


# ─────────────── allow_network_skip path (nightly) ─────────────────────


@dataclass
class _StubProc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def test_audit_network_skip_warns_when_pypi_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """allow_network_skip=True → non-zero with no vuln ID classified as transient."""
    monkeypatch.setattr(
        audit_mod,
        "capture",
        lambda _cmd: _StubProc(returncode=1, stderr="Could not fetch the index"),
    )

    audit_mod.cmd_audit(allow_network_skip=True)  # must not SystemExit

    out = capsys.readouterr().out
    assert "transient" in out


def test_audit_network_skip_warns_on_ensurepip_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ensurepip / venv-setup failures look transient — warn_skip rather than fail."""
    monkeypatch.setattr(
        audit_mod,
        "capture",
        lambda _cmd: _StubProc(
            returncode=1, stderr="subprocess.CalledProcessError: ensurepip died with SIGABRT"
        ),
    )

    audit_mod.cmd_audit(allow_network_skip=True)

    assert "transient" in capsys.readouterr().out


@pytest.mark.parametrize(
    "vuln_id",
    ["GHSA-xxxx-yyyy-zzzz", "CVE-2024-12345", "PYSEC-2024-100"],
)
def test_audit_network_skip_passes_through_real_findings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    vuln_id: str,
) -> None:
    """Non-zero with a known vulnerability ID always fails — even with allow_network_skip."""
    monkeypatch.setattr(
        audit_mod,
        "capture",
        lambda _cmd: _StubProc(returncode=1, stdout=f"{vuln_id}: vulnerable"),
    )

    with pytest.raises(SystemExit) as exc:
        audit_mod.cmd_audit(allow_network_skip=True)

    assert exc.value.code == 1
    assert vuln_id in capsys.readouterr().out


def test_audit_network_skip_clean_run_prints_ok(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """rc=0 under allow_network_skip → ok line, no exit."""
    monkeypatch.setattr(audit_mod, "capture", lambda _cmd: _StubProc(returncode=0))

    audit_mod.cmd_audit(allow_network_skip=True)

    assert "no known vulnerabilities" in capsys.readouterr().out.lower()
