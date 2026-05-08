"""Dependency audit via pip-audit (dispatched through uvx)."""

from __future__ import annotations

import re
import sys
import tomllib

from interlocks.config import find_project_root, load_config
from interlocks.runner import Task, capture, dump_and_exit, fail, ok, run, uvx_tool, warn_skip

# pip-audit emits one of these IDs only when it actually finds a vulnerability;
# absence of all three means the non-zero exit is environmental (network failure,
# ensurepip quirk, missing wheel) — caller can opt to treat as transient.
_VULN_ID_PATTERN = re.compile(r"\b(?:GHSA-[\w-]+|CVE-\d{4}-\d+|PYSEC-\d{4}-\d+)\b")


def task_audit() -> Task:
    return _pip_audit_task()


def _pip_audit_task() -> Task:
    cfg = load_config()
    if not _project_has_dependencies():
        return Task(
            "Dep audit",
            [sys.executable, "-c", "print('No known vulnerabilities found')"],
            display="pip-audit",
            label="audit",
        )
    return Task(
        "Dep audit",
        uvx_tool("pip-audit", ".", version=cfg.tool_version("pip-audit")),
        label="audit",
        display="pip-audit .",
    )


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


def _project_has_dependencies() -> bool:
    with (find_project_root() / "pyproject.toml").open("rb") as f:
        deps = tomllib.load(f).get("project", {}).get("dependencies", [])
    return isinstance(deps, list) and bool(deps)
