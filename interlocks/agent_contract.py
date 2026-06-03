"""Machine-readable guidance for agents consuming interlocks JSON.

The CLI already reports what happened. This module adds the missing action
contract: what to run next, what evidence was written, and which policy changes
need human approval.
"""

from __future__ import annotations

import re

SCHEMA_VERSION = 1

_COMMAND_RE = re.compile(r"`([^`]+)`")

_GATE_COMMANDS: dict[str, str] = {
    "acceptance": "interlocks gate acceptance --json",
    "arch": "interlocks gate arch --json",
    "attribution": "interlocks gate behavior-attribution --json",
    "audit": "interlocks gate audit --json",
    "behavior-attribution": "interlocks gate behavior-attribution --json",
    "complexity": "interlocks gate complexity --json",
    "coverage": "interlocks gate coverage --json",
    "crap": "interlocks gate crap --json",
    "deps": "interlocks gate deps --json",
    "deps-freshness": "interlocks gate deps-freshness --json",
    "fix": "interlocks fix --json",
    "fix optimize": "interlocks fix optimize --json",
    "format": "interlocks gate format --json",
    "format-check": "interlocks gate format-check --json",
    "lint": "interlocks gate lint --json",
    "mutation": "interlocks gate mutation --json",
    "properties": "interlocks gate properties --json",
    "test": "interlocks gate test --json",
    "typecheck": "interlocks gate typecheck --json",
}

_FAILURE_CATEGORIES: dict[str, str] = {
    "acceptance": "behavior_failure",
    "arch": "architecture_policy",
    "attribution": "behavior_attribution_policy",
    "audit": "dependency_security_policy",
    "behavior-attribution": "behavior_attribution_policy",
    "complexity": "complexity_policy",
    "coverage": "coverage_policy",
    "crap": "complexity_coverage_policy",
    "deps": "dependency_policy",
    "deps-freshness": "dependency_freshness_policy",
    "fix": "style_policy",
    "fix optimize": "style_policy",
    "format": "format_policy",
    "format-check": "format_policy",
    "lint": "lint_policy",
    "mutation": "test_strength_policy",
    "properties": "property_test_failure",
    "test": "test_failure",
    "typecheck": "typecheck_failure",
}

_POLICY_BOUNDARIES: tuple[dict[str, object], ...] = (
    {
        "kind": "lower-threshold",
        "approval_required": True,
        "reason": "Changing a quality threshold weakens repository policy.",
    },
    {
        "kind": "disable-enforcement",
        "approval_required": True,
        "reason": "Disabling a blocking gate changes the quality contract.",
    },
    {
        "kind": "add-global-skip",
        "approval_required": True,
        "reason": "Global skips hide gates from every interlocks stage.",
    },
    {
        "kind": "downgrade-preset",
        "approval_required": True,
        "reason": "Preset downgrades weaken multiple defaults at once.",
    },
    {
        "kind": "bypass-hook",
        "approval_required": True,
        "reason": "Bypassing hooks avoids the configured local feedback loop.",
    },
)


def failure_category(gate_name: str) -> str:
    """Return a stable category for a failed gate."""
    return _FAILURE_CATEGORIES.get(gate_name, "gate_failure")


def stage_agent_contract(
    command: str,
    *,
    passed: bool,
    gates: list[dict[str, object]],
    skipped: list[dict[str, str]],
    artifacts: list[dict[str, str]],
) -> dict[str, object]:
    """Build the `agent` block for stage-like JSON payloads."""
    failed = [gate for gate in gates if gate.get("status") != "ok"]
    required = [_failed_gate_action(command, gate) for gate in failed]
    recommended = [_skipped_gate_action(entry) for entry in skipped if entry.get("next_action")]
    recommended = [action for action in recommended if action is not None]
    return {
        "state": _stage_state(passed, required, recommended),
        "summary": _stage_summary(passed, required, recommended),
        "required_actions": required,
        "recommended_actions": recommended,
        "artifacts": artifacts,
        "policy_boundaries": policy_boundaries(),
    }


def doctor_agent_contract(
    *,
    status: str,
    is_blocked: bool,
    next_steps: list[str],
) -> dict[str, object]:
    """Build the `agent` block for `doctor --json`."""
    actions = [
        action_from_message("doctor-next-step", step, reason=step)
        for step in next_steps
    ]
    if is_blocked:
        required = actions
        recommended: list[dict[str, object]] = []
    else:
        required = []
        recommended = actions
    return {
        "state": "blocked" if is_blocked else "attention",
        "summary": status,
        "required_actions": required,
        "recommended_actions": recommended,
        "artifacts": [],
        "policy_boundaries": policy_boundaries(),
    }


def preflight_agent_contract(command: str, error: str, next_action: str) -> dict[str, object]:
    """Build the `agent` block for preflight failures."""
    return {
        "state": "blocked",
        "summary": error,
        "required_actions": [
            action_from_message(
                "preflight-fix",
                next_action,
                reason=f"{command} cannot run until preflight passes",
            )
        ],
        "recommended_actions": [],
        "artifacts": [],
        "policy_boundaries": policy_boundaries(),
    }


def policy_boundaries() -> list[dict[str, object]]:
    """Return policy changes agents must not make without owner approval."""
    return [dict(item) for item in _POLICY_BOUNDARIES]


def action_from_message(kind: str, message: str, *, reason: str) -> dict[str, object]:
    """Turn a prose next-step line into a structured action when possible."""
    command = _extract_command(message)
    action: dict[str, object] = {
        "kind": kind,
        "reason": reason,
        "message": message,
        "mutates": _command_mutates(command),
        "approval_required": False,
    }
    if command is not None:
        action["command"] = _with_json_flag(command)
    return action


def _failed_gate_action(command: str, gate: dict[str, object]) -> dict[str, object]:
    name = str(gate.get("name", ""))
    rerun = _rerun_command(command, name)
    action: dict[str, object] = {
        "kind": "rerun-failing-gate",
        "gate": name,
        "reason": f"{name} failed",
        "mutates": _command_mutates(rerun),
        "approval_required": False,
        "failure_category": failure_category(name),
    }
    if rerun is not None:
        action["command"] = rerun
    return action


def _skipped_gate_action(entry: dict[str, str]) -> dict[str, object] | None:
    message = entry.get("next_action")
    if not message:
        return None
    action = action_from_message(
        "run-skipped-gate",
        message,
        reason=entry.get("reason", "gate was skipped"),
    )
    action["gate"] = entry.get("name", "")
    return action


def _rerun_command(stage_command: str, gate_name: str) -> str | None:
    if gate_name == "properties":
        if stage_command == "ci":
            return "interlocks gate properties --profile=ci --json"
        if stage_command == "nightly":
            return "interlocks gate properties --profile=nightly --json"
        if stage_command == "check":
            return "interlocks gate properties --profile=check --json"
    return _GATE_COMMANDS.get(gate_name)


def _stage_state(
    passed: bool,
    required: list[dict[str, object]],
    recommended: list[dict[str, object]],
) -> str:
    if required or not passed:
        return "blocked"
    if recommended:
        return "attention"
    return "passed"


def _stage_summary(
    passed: bool,
    required: list[dict[str, object]],
    recommended: list[dict[str, object]],
) -> str:
    if required:
        labels = ", ".join(str(action.get("gate")) for action in required)
        return f"{len(required)} gate(s) failed: {labels}"
    if not passed:
        return "command failed before a gate result was recorded"
    if recommended:
        return f"passed with {len(recommended)} skipped follow-up(s)"
    return "all recorded gates passed"


def _extract_command(message: str) -> str | None:
    match = _COMMAND_RE.search(message)
    if match is None:
        return None
    return match.group(1)


def _with_json_flag(command: str | None) -> str | None:
    if command is None or "--json" in command:
        return command
    if _is_interlocks_command(command):
        return f"{command} --json"
    return command


def _is_interlocks_command(command: str) -> bool:
    return command.startswith(("interlocks ", "il "))


def _command_mutates(command: str | None) -> bool:
    if command is None:
        return False
    parts = command.split()
    mutating_heads = {"uv", "python", "python3"}
    mutating_interlocks = {"clean", "fix", "init", "presets", "setup", "warm"}
    mutates = bool(parts) and parts[0] in mutating_heads
    if _is_interlocks_command(command) and len(parts) >= 3 and parts[1] == "gate":
        mutates = parts[2] == "format"
    elif _is_interlocks_command(command) and len(parts) >= 2:
        mutates = parts[1] in mutating_interlocks
    return mutates
