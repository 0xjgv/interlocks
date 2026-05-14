#!/usr/bin/env python3
"""Run local adoption-friction scenarios against generated repos."""

from __future__ import annotations

import argparse
import json
import subprocess  # noqa: S404
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from adoption_friction_lib import (
        ADOPTION_ROOT,
        create_bare_repo,
        create_legacy_repo,
        create_partial_repo,
        create_progressive_repo,
        create_strict_repo,
        isolated_env,
    )
    from lintfix_playground_lib import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - exercised when imported as tools.*
    from tools.adoption_friction_lib import (
        ADOPTION_ROOT,
        create_bare_repo,
        create_legacy_repo,
        create_partial_repo,
        create_progressive_repo,
        create_strict_repo,
        isolated_env,
    )
    from tools.lintfix_playground_lib import REPO_ROOT


class LabFailure(AssertionError):
    """Raised when a scenario no longer reproduces expected adaptation evidence."""


@dataclass(frozen=True)
class CommandRecord:
    command: str
    returncode: int
    elapsed_seconds: float
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


@dataclass
class ScenarioRun:
    name: str
    repo: Path
    commands: list[CommandRecord] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    friction_score: int = 0

    def command(self, *args: str, expect_success: bool | None = None) -> CommandRecord:
        start = time.monotonic()
        cmd = (sys.executable, "-m", "interlocks.cli", *args)
        result = subprocess.run(  # noqa: S603
            list(cmd),
            cwd=self.repo,
            env=isolated_env(self.repo, repo_root=REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        record = CommandRecord(
            command=" ".join(("interlocks", *args)),
            returncode=result.returncode,
            elapsed_seconds=round(time.monotonic() - start, 3),
            stdout=result.stdout,
            stderr=result.stderr,
        )
        self.commands.append(record)
        if result.returncode != 0:
            self.friction_score += 2
        if expect_success is True and result.returncode != 0:
            raise LabFailure(f"{record.command} failed unexpectedly:\n{record.output}")
        if expect_success is False and result.returncode == 0:
            raise LabFailure(f"{record.command} unexpectedly succeeded")
        return record

    def require_fragment(self, record: CommandRecord, *fragments: str) -> None:
        for fragment in fragments:
            if fragment not in record.output:
                self.friction_score += 1
                raise LabFailure(f"{record.command} missing actionable fragment {fragment!r}")
            self.next_actions.append(fragment)

    def note_artifact(self, path: str) -> None:
        target = self.repo / path
        if not target.exists():
            self.friction_score += 1
            raise LabFailure(f"missing artifact {path}")
        self.artifacts.append(path)


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    friction_score: int
    commands: list[dict[str, object]]
    artifacts: list[str]
    next_actions: list[str]
    detail: str


@dataclass(frozen=True)
class LabContext:
    target_root: Path
    verbose: bool


Scenario = Callable[[LabContext], ScenarioRun]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-going", action="store_true", help="run every selected scenario")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=tuple(SCENARIOS),
        help="run one scenario by name; may be repeated",
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=ADOPTION_ROOT,
        help="directory where scenario repos and report.json are recreated",
    )
    parser.add_argument("--verbose", action="store_true", help="print command outputs")
    args = parser.parse_args(argv)

    context = LabContext(target_root=args.target_root.resolve(), verbose=args.verbose)
    selected = tuple(args.scenario or SCENARIOS)
    results = run_scenarios(selected, context, keep_going=args.keep_going)
    report_path = write_report(context.target_root, results)
    print_report(results, report_path)
    return 0 if all(result.passed for result in results) else 1


def run_scenarios(
    names: tuple[str, ...],
    context: LabContext,
    *,
    keep_going: bool,
) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for name in names:
        run: ScenarioRun | None = None
        try:
            run = SCENARIOS[name](context)
        except LabFailure as exc:
            results.append(_result_from_run(name, run, passed=False, detail=str(exc)))
            if not keep_going:
                break
        else:
            results.append(_result_from_run(name, run, passed=True, detail="ok"))
            if context.verbose:
                _print_transcript(run)
    return results


def scenario_bare_repo(context: LabContext) -> ScenarioRun:
    run = ScenarioRun(
        "bare-repo",
        create_bare_repo(context.target_root / "bare-repo", root=context.target_root),
    )
    doctor = run.command("doctor", "--verbose")
    run.require_fragment(doctor, "pyproject", "Fix blockers")
    setup = run.command("setup", "--check", "--verbose", expect_success=False)
    run.require_fragment(setup, "setup")
    changed = run.command("check", "--changed=HEAD")
    if changed.returncode not in (0, 1, 2):
        raise LabFailure("check --changed returned an unexpected status")
    return run


def scenario_legacy_ai_patch(context: LabContext) -> ScenarioRun:
    run = ScenarioRun(
        "legacy-ai-patch",
        create_legacy_repo(context.target_root / "legacy-ai-patch", root=context.target_root),
    )
    doctor = run.command("doctor", "--verbose")
    run.require_fragment(doctor, "src", "tests")
    plan = run.command("fix-plan", "--base=HEAD", expect_success=True)
    run.require_fragment(plan, "I001", "F401")
    run.note_artifact(".lintfix/plan.json")
    optimize = run.command("fix-optimize", "--base=HEAD", expect_success=True)
    run.require_fragment(optimize, "policy mode is escrow")
    run.note_artifact(".lintfix/optimize.json")
    check = run.command("check", expect_success=False)
    run.require_fragment(check, "failed")
    evaluate = run.command("evaluate", "--verbose", expect_success=True)
    run.require_fragment(evaluate, "command=evaluate")
    return run


def scenario_partial_adoption(context: LabContext) -> ScenarioRun:
    run = ScenarioRun(
        "partial-adoption",
        create_partial_repo(context.target_root / "partial-adoption", root=context.target_root),
    )
    doctor = run.command("doctor", "--verbose")
    run.require_fragment(doctor, "baseline")
    setup = run.command("setup", "--check", "--verbose", expect_success=False)
    run.require_fragment(setup, "setup")
    presets = run.command("presets", expect_success=True)
    run.require_fragment(presets, "baseline", "strict")
    evaluate = run.command("evaluate", "--verbose", expect_success=True)
    run.require_fragment(evaluate, "command=evaluate")
    check = run.command("check")
    if check.returncode not in (0, 1):
        raise LabFailure("partial check returned an unexpected status")
    return run


def scenario_progressive_ratchet(context: LabContext) -> ScenarioRun:
    run = ScenarioRun(
        "progressive-ratchet",
        create_progressive_repo(
            context.target_root / "progressive-ratchet",
            root=context.target_root,
        ),
    )
    show = run.command("baseline", "show", "--json", expect_success=True)
    run.require_fragment(show, "lint_violations_max")
    lint = run.command("lint", expect_success=False)
    run.require_fragment(lint, "violations")
    check = run.command("baseline", "check", "--json", expect_success=False)
    run.require_fragment(check, "lint_violations_max")
    run.note_artifact(".interlocks/baseline.json")
    run.note_artifact(".interlocks/run-summary.json")
    return run


def scenario_strict_wired(context: LabContext) -> ScenarioRun:
    run = ScenarioRun(
        "strict-wired",
        create_strict_repo(context.target_root / "strict-wired", root=context.target_root),
    )
    local_setup = run.command("setup", "--verbose", expect_success=True)
    run.require_fragment(local_setup, "setup")
    setup = run.command("setup", "--ci=github", "--verbose", expect_success=True)
    run.require_fragment(setup, "GitHub CI Setup")
    run.note_artifact(".github/workflows/interlocks.yml")
    setup_check = run.command("setup", "--check", "--verbose", expect_success=True)
    run.require_fragment(setup_check, "Setup Check")
    doctor = run.command("doctor", "--verbose", expect_success=True)
    run.require_fragment(doctor, "strict")
    evaluate = run.command("evaluate", "--verbose", expect_success=True)
    run.require_fragment(evaluate, "command=evaluate")
    return run


SCENARIOS: dict[str, Scenario] = {
    "bare-repo": scenario_bare_repo,
    "legacy-ai-patch": scenario_legacy_ai_patch,
    "partial-adoption": scenario_partial_adoption,
    "progressive-ratchet": scenario_progressive_ratchet,
    "strict-wired": scenario_strict_wired,
}


def write_report(target_root: Path, results: list[ScenarioResult]) -> Path:
    target_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.time(),
        "scenarios": [asdict(result) for result in results],
    }
    target = target_root / "report.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def print_report(results: list[ScenarioResult], report_path: Path) -> None:
    print("adoption friction lab")
    for result in results:
        state = "ok" if result.passed else "fail"
        print(f"  [{state}] {result.name}: friction={result.friction_score}  {result.detail}")
    print(f"  report {report_path}")


def _result_from_run(
    name: str,
    run: ScenarioRun | None,
    *,
    passed: bool,
    detail: str,
) -> ScenarioResult:
    if run is None:
        return ScenarioResult(name, passed, 1, [], [], [], detail)
    return ScenarioResult(
        name=run.name,
        passed=passed,
        friction_score=run.friction_score,
        commands=[
            {
                "command": command.command,
                "returncode": command.returncode,
                "elapsed_seconds": command.elapsed_seconds,
            }
            for command in run.commands
        ],
        artifacts=run.artifacts,
        next_actions=sorted(set(run.next_actions)),
        detail=detail,
    )


def _print_transcript(run: ScenarioRun) -> None:
    for command in run.commands:
        print(f"$ {command.command}  # cwd={run.repo}")
        if command.stdout:
            print(command.stdout, end="" if command.stdout.endswith("\n") else "\n")
        if command.stderr:
            print(command.stderr, end="" if command.stderr.endswith("\n") else "\n")


if __name__ == "__main__":
    raise SystemExit(main())
