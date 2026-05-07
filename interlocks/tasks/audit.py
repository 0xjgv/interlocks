"""Dependency audit via pip-audit."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from interlocks.config import find_project_root, load_config
from interlocks.runner import Task, capture, dump_and_exit, fail, ok, python_m, run, warn_skip

# pip-audit emits one of these IDs only when it actually finds a vulnerability;
# absence of all three means the non-zero exit is environmental (network failure,
# ensurepip quirk, missing wheel) — caller can opt to treat as transient.
_VULN_ID_PATTERN = re.compile(r"\b(?:GHSA-[\w-]+|CVE-\d{4}-\d+|PYSEC-\d{4}-\d+)\b")


def task_audit(*, allow_network_skip: bool = False) -> Task:
    if not allow_network_skip:
        return _pip_audit_task()
    return Task(
        "Dep audit",
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, {str(_package_parent())!r}); "
            "from interlocks.tasks.audit import cmd_audit; cmd_audit(allow_network_skip=True)",
        ],
        display="python -m pip_audit",
        label="audit",
    )


def _pip_audit_task() -> Task:
    if not _project_has_dependencies():
        return Task(
            "Dep audit",
            [sys.executable, "-c", "print('No known vulnerabilities found')"],
            display="python -m pip_audit",
            label="audit",
        )
    return Task("Dep audit", python_m("pip_audit", "."), label="audit")


def cmd_audit(*, allow_network_skip: bool = False) -> None:
    """Run pip-audit. Block on findings.

    With ``allow_network_skip``, a non-zero exit *without* a vulnerability ID
    (GHSA / CVE / PYSEC) downgrades to ``warn_skip`` so flaky PyPI, offline
    runners, or pip-audit's own venv setup glitches don't crash the caller.
    Real findings still fail.
    """
    cfg = load_config()
    if cfg.audit_severity_threshold is not None:
        ok(f"Audit severity policy: fail on {cfg.audit_severity_threshold}+ vulnerabilities")
    task = _pip_audit_task()
    if not allow_network_skip:
        run(task)
        return
    result = capture(task.cmd)
    if result.returncode == 0:
        ok("Audit: no known vulnerabilities found")
        return
    output = (result.stdout or "") + (result.stderr or "")
    if not _VULN_ID_PATTERN.search(output):
        warn_skip("audit: pip-audit failed without a vulnerability ID — treating as transient")
        return
    fail("Audit: pip-audit reported known vulnerabilities")
    dump_and_exit(result.returncode, result.stdout, result.stderr)


def _package_parent() -> Path:
    return Path(__file__).resolve().parents[2]


def _project_has_dependencies() -> bool:
    with (find_project_root() / "pyproject.toml").open("rb") as f:
        deps = tomllib.load(f).get("project", {}).get("dependencies", [])
    return isinstance(deps, list) and bool(deps)
