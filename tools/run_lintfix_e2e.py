#!/usr/bin/env python3
"""Run local e2e response checks for the lint-fix feature suite."""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # noqa: S404
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lintfix_playground_lib import (
    DIRTY_FILES,
    PLAYGROUNDS_ROOT,
    REPLAY_REORDERED_IMPORTS,
    REPO_ROOT,
    create_optimizer_repo,
    create_replay_repo,
    git,
    write_text,
)


class E2EFailure(AssertionError):
    """Raised when an e2e response check fails."""


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        return self.stdout + self.stderr


@dataclass(frozen=True)
class ScenarioContext:
    target_root: Path
    repo_root: Path
    verbose: bool


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    detail: str


Scenario = Callable[[ScenarioContext], None]


def run_cli(cwd: Path, *args: str, repo_root: Path = REPO_ROOT) -> CommandResult:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing}" if existing else str(repo_root)
    cmd = (sys.executable, "-m", "interlocks.cli", *args)
    result = subprocess.run(  # noqa: S603
        list(cmd),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(cmd, cwd, result.returncode, result.stdout, result.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-going", action="store_true", help="run all selected scenarios")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=tuple(SCENARIOS),
        help="run one scenario by name; may be passed more than once",
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=PLAYGROUNDS_ROOT / "lintfix-e2e",
        help="directory where scenario repos are recreated",
    )
    parser.add_argument("--verbose", action="store_true", help="print command output on success")
    args = parser.parse_args(argv)

    selected = tuple(args.scenario or SCENARIOS)
    context = ScenarioContext(
        target_root=args.target_root.resolve(),
        repo_root=REPO_ROOT,
        verbose=args.verbose,
    )
    results = run_scenarios(selected, context, keep_going=args.keep_going)
    _print_report(results)
    return 0 if all(r.passed for r in results) else 1


def run_scenarios(
    names: tuple[str, ...],
    context: ScenarioContext,
    *,
    keep_going: bool,
) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for name in names:
        try:
            SCENARIOS[name](context)
        except E2EFailure as exc:
            results.append(ScenarioResult(name, False, str(exc)))
            if not keep_going:
                break
        else:
            results.append(ScenarioResult(name, True, "ok"))
    return results


def _print_report(results: list[ScenarioResult]) -> None:
    print("lint-fix e2e")
    for result in results:
        state = "ok" if result.passed else "fail"
        print(f"  [{state}] {result.name}: {result.detail}")


def _repo(context: ScenarioContext, name: str) -> Path:
    return create_optimizer_repo(context.target_root / name, playgrounds_root=context.target_root)


def _replay_repo(context: ScenarioContext, name: str) -> Path:
    return create_replay_repo(context.target_root / name, playgrounds_root=context.target_root)


def scenario_fix_plan_preview(context: ScenarioContext) -> None:
    repo = _repo(context, "fix-plan-preview")
    result = run_cli(repo, "fix-plan", "--base=HEAD", repo_root=context.repo_root)
    _expect_success(result)
    _expect_output(result, "I001", "F401", "UP045")

    plan = _read_json(repo / ".lintfix" / "plan.json")
    by_rule = {entry["rule"]: entry for entry in plan["candidates"]}
    _expect(by_rule["I001"]["classification"] == "auto", "I001 should be auto")
    _expect(by_rule["W292"]["classification"] == "auto", "W292 should be auto")
    _expect(by_rule["F401"]["classification"] == "escrow", "F401 should be escrow")
    _expect(by_rule["UP045"]["classification"] == "escrow", "UP045 should be escrow")
    _expect((repo / ".lintfix" / "escrow" / "F401.patch").is_file(), "F401 patch missing")
    _expect_unchanged_dirty_files(repo)
    _show_if_verbose(context, result)


def scenario_fix_optimize_preview(context: ScenarioContext) -> None:
    repo = _repo(context, "fix-optimize-preview")
    result = run_cli(repo, "fix-optimize", "--base=HEAD", repo_root=context.repo_root)
    _expect_success(result)
    _expect_output(result, "I001", "W292", "F401", "policy mode is escrow")

    optimize = _read_json(repo / ".lintfix" / "optimize.json")
    selected = {entry["rule"]: entry for entry in optimize["selected"]}
    rejected = {entry["rule"]: entry for entry in optimize["not_selected"]}
    _expect({"I001", "W292"}.issubset(selected), "auto rules not selected")
    _expect(rejected["F401"]["reason"] == "policy mode is escrow", "F401 reason mismatch")
    _expect(rejected["UP045"]["reason"] == "policy mode is escrow", "UP045 reason mismatch")
    _expect(not any(entry["unsafe"] for entry in selected.values()), "unsafe rule selected")
    _expect_unchanged_dirty_files(repo)
    _show_if_verbose(context, result)


def scenario_fix_optimize_budget(context: ScenarioContext) -> None:
    repo = _repo(context, "fix-optimize-budget")
    result = run_cli(
        repo,
        "fix-optimize",
        "--base=HEAD",
        "--budget=renovation",
        repo_root=context.repo_root,
    )
    _expect_success(result)

    optimize = _read_json(repo / ".lintfix" / "optimize.json")
    _expect(optimize["budget"] == "renovation", "budget name mismatch")
    selected = {entry["rule"]: entry for entry in optimize["selected"]}
    rejected = {entry["rule"]: entry for entry in optimize["not_selected"]}

    _expect(
        all(entry["policy_mode"] == "auto" for entry in selected.values()),
        "non-auto rule selected",
    )
    _expect(not any(entry["unsafe"] for entry in selected.values()), "unsafe rule selected")
    for rule in ("F401", "UP045"):
        _expect(
            rejected[rule]["reason"] == "policy mode is escrow",
            f"{rule} reason mismatch",
        )

    total_value = sum(entry["value"] for entry in selected.values())
    _expect(optimize["total_value"] == total_value, "total_value != summed selected value")
    for dim in ("outside_diff", "changed_lines", "files", "risk"):
        summed = sum(entry["cost"][dim] for entry in selected.values())
        _expect(optimize["total_cost"][dim] == summed, f"total_cost {dim} mismatch")

    _expect_unchanged_dirty_files(repo)
    _show_if_verbose(context, result)


def scenario_fix_annotate(context: ScenarioContext) -> None:
    repo = _repo(context, "fix-annotate")
    _expect_success(run_cli(repo, "fix-plan", "--base=HEAD", repo_root=context.repo_root))
    plan_annotations = run_cli(repo, "fix-annotate", repo_root=context.repo_root)
    _expect_success(plan_annotations)
    _expect_output(plan_annotations, "::notice file=", "[I001]", "[F401]")

    _expect_success(run_cli(repo, "fix-optimize", "--base=HEAD", repo_root=context.repo_root))
    opt_annotations = run_cli(
        repo,
        "fix-annotate",
        "--source=optimize",
        repo_root=context.repo_root,
    )
    _expect_success(opt_annotations)
    _expect_output(opt_annotations, "::notice file=", "[I001]", "[F401]")
    _show_if_verbose(context, plan_annotations, opt_annotations)


def scenario_fix_metrics(context: ScenarioContext) -> None:
    repo = _repo(context, "fix-metrics")
    _expect_success(run_cli(repo, "fix-plan", "--base=HEAD", repo_root=context.repo_root))
    _expect_success(run_cli(repo, "fix-optimize", "--base=HEAD", repo_root=context.repo_root))
    result = run_cli(repo, "fix-metrics", repo_root=context.repo_root)
    _expect_success(result)
    _expect_output(result, ".lintfix/metrics.json", "selected=2", "rejected=")

    metrics = _read_json(repo / ".lintfix" / "metrics.json")
    _expect(metrics["sources"]["plan"] is True, "metrics missing plan source")
    _expect(metrics["sources"]["optimize"] is True, "metrics missing optimize source")
    _expect(metrics["optimize"]["selected_rules"] == ["I001", "W292"], "selected summary mismatch")
    _expect("F401" in metrics["plan"]["escrow_rules"], "F401 missing from escrow summary")
    _show_if_verbose(context, result)


def scenario_apply_success(context: ScenarioContext) -> None:
    repo = _repo(context, "apply-success")
    result = run_cli(
        repo,
        "fix-optimize",
        "--base=HEAD",
        "--apply",
        f"--verify-cmd={sys.executable} -c pass",
        repo_root=context.repo_root,
    )
    _expect_success(result)
    imports = (repo / "src" / "playground" / "imports.py").read_text(encoding="utf-8")
    _expect(imports.index("import json") < imports.index("import os"), "imports not sorted")
    _expect("import json" in imports, "escrow-only F401 was applied")
    newline = (repo / "src" / "playground" / "newline.py").read_text(encoding="utf-8")
    _expect(newline.endswith("\n"), "EOF newline not fixed")
    _show_if_verbose(context, result)


def scenario_apply_rollback(context: ScenarioContext) -> None:
    repo = _repo(context, "apply-rollback")
    result = run_cli(
        repo,
        "fix-optimize",
        "--base=HEAD",
        "--apply",
        f'--verify-cmd={sys.executable} -c "import sys; sys.exit(1)"',
        repo_root=context.repo_root,
    )
    _expect(result.returncode != 0, "rollback command should fail")
    _expect_unchanged_dirty_files(repo)
    _expect((repo / ".lintfix" / "failed.patch").is_file(), "failed patch missing")
    _show_if_verbose(context, result)


def scenario_empty_plan(context: ScenarioContext) -> None:
    repo = _repo(context, "empty-plan")
    git(repo, "restore", ".")
    plan_result = run_cli(repo, "fix-plan", "--base=HEAD", repo_root=context.repo_root)
    optimize_result = run_cli(repo, "fix-optimize", "--base=HEAD", repo_root=context.repo_root)
    _expect_success(plan_result)
    _expect_success(optimize_result)
    _expect(_read_json(repo / ".lintfix" / "plan.json")["candidates"] == [], "plan not empty")
    optimize = _read_json(repo / ".lintfix" / "optimize.json")
    _expect(optimize["selected"] == [], "selected not empty")
    _expect(optimize["not_selected"] == [], "not_selected not empty")
    _show_if_verbose(context, plan_result, optimize_result)


def scenario_fix_optimize_self_sufficient(context: ScenarioContext) -> None:
    """One `fix-optimize` run writes the full `.lintfix/` artifact set."""
    repo = _repo(context, "fix-optimize-self-sufficient")
    result = run_cli(repo, "fix-optimize", "--base=HEAD", "--metrics", repo_root=context.repo_root)
    _expect_success(result)
    plan = _read_json(repo / ".lintfix" / "plan.json")
    _expect({"I001", "F401"}.issubset({c["rule"] for c in plan["candidates"]}), "plan.json sparse")
    _expect((repo / ".lintfix" / "optimize.json").is_file(), "optimize.json missing")
    metrics = _read_json(repo / ".lintfix" / "metrics.json")
    _expect(metrics["sources"]["plan"] is True, "metrics missing plan source")
    _expect(metrics["sources"]["optimize"] is True, "metrics missing optimize source")
    _show_if_verbose(context, result)


def scenario_fix_optimize_annotate(context: ScenarioContext) -> None:
    repo = _repo(context, "fix-optimize-annotate")
    result = run_cli(
        repo, "fix-optimize", "--base=HEAD", "--annotate", repo_root=context.repo_root
    )
    _expect_success(result)
    _expect_output(result, "::notice file=", "[I001]")
    _show_if_verbose(context, result)


def scenario_fix_optimize_auto_stats(context: ScenarioContext) -> None:
    """`.lintfix/replay.json` is auto-discovered; `--no-stats` opts out."""
    repo = _replay_repo(context, "fix-optimize-auto-stats")
    _expect_success(
        run_cli(repo, "fix-replay", "--base=main", "--n=2", repo_root=context.repo_root)
    )
    _expect((repo / ".lintfix" / "replay.json").is_file(), "fix-replay wrote no replay.json")

    # A fresh dirty file gives fix-optimize candidates to weigh against the stats.
    write_text(repo / "c.py", REPLAY_REORDERED_IMPORTS)
    discovered = run_cli(
        repo, "fix-optimize", "--base=HEAD", "--verbose", repo_root=context.repo_root
    )
    _expect_success(discovered)
    _expect_output(discovered, ".lintfix/replay.json")

    skipped = run_cli(
        repo,
        "fix-optimize",
        "--base=HEAD",
        "--no-stats",
        "--verbose",
        repo_root=context.repo_root,
    )
    _expect_success(skipped)
    _expect(
        ".lintfix/replay.json" not in skipped.combined_output,
        "--no-stats did not skip replay discovery",
    )
    _show_if_verbose(context, discovered, skipped)


def scenario_unblock_alias(context: ScenarioContext) -> None:
    """`unblock` is an alias for `fix-optimize` — identical artifact set."""
    repo = _repo(context, "unblock-alias")
    result = run_cli(repo, "unblock", "--base=HEAD", repo_root=context.repo_root)
    _expect_success(result)
    _expect((repo / ".lintfix" / "optimize.json").is_file(), "optimize.json missing")
    _expect((repo / ".lintfix" / "plan.json").is_file(), "plan.json missing under unblock alias")
    _expect_unchanged_dirty_files(repo)
    _show_if_verbose(context, result)


def scenario_fix_replay(context: ScenarioContext) -> None:
    repo = _replay_repo(context, "fix-replay")
    result = run_cli(repo, "fix-replay", "--base=main", "--n=2", repo_root=context.repo_root)
    _expect_success(result)
    _expect_output(result, "commits replayed", "rules observed")
    replay = _read_json(repo / ".lintfix" / "replay.json")
    _expect(replay["base_branch"] == "main", "base branch mismatch")
    _expect(replay["n_requested"] == 2, "requested count mismatch")
    _expect(replay["n_replayed"] == 2, "replayed count mismatch")
    by_rule = {entry["rule"]: entry for entry in replay["rules"]}
    _expect("I001" in by_rule, "I001 not observed in replay")
    _show_if_verbose(context, result)


SCENARIOS: dict[str, Scenario] = {
    "fix-plan-preview": scenario_fix_plan_preview,
    "fix-optimize-preview": scenario_fix_optimize_preview,
    "fix-optimize-budget": scenario_fix_optimize_budget,
    "fix-annotate": scenario_fix_annotate,
    "fix-metrics": scenario_fix_metrics,
    "fix-optimize-self-sufficient": scenario_fix_optimize_self_sufficient,
    "fix-optimize-annotate": scenario_fix_optimize_annotate,
    "fix-optimize-auto-stats": scenario_fix_optimize_auto_stats,
    "unblock-alias": scenario_unblock_alias,
    "apply-success": scenario_apply_success,
    "apply-rollback": scenario_apply_rollback,
    "empty-plan": scenario_empty_plan,
    "fix-replay": scenario_fix_replay,
}


def _expect_success(result: CommandResult) -> None:
    _expect(
        result.returncode == 0,
        f"{' '.join(result.args)} failed with rc={result.returncode}\n{result.combined_output}",
    )


def _expect_output(result: CommandResult, *needles: str) -> None:
    output = result.combined_output
    for needle in needles:
        _expect(needle in output, f"missing output fragment {needle!r}\n{output}")


def _expect_unchanged_dirty_files(repo: Path) -> None:
    for relpath, expected in DIRTY_FILES.items():
        actual = (repo / relpath).read_text(encoding="utf-8")
        _expect(actual == expected, f"{relpath} changed unexpectedly")


def _read_json(path: Path) -> dict[str, object]:
    _expect(path.is_file(), f"missing JSON artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _show_if_verbose(context: ScenarioContext, *results: CommandResult) -> None:
    if not context.verbose:
        return
    for result in results:
        print(f"$ {' '.join(result.args)}  # cwd={result.cwd}")
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise E2EFailure(message)


if __name__ == "__main__":
    raise SystemExit(main())
