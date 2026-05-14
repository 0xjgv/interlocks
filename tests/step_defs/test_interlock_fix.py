"""Step defs for tests/features/interlock_fix.feature.

Per-command non-mutating coverage of the lint-fix harness. Each scenario
starts from ``make_legacy_greenfield_project`` and asserts the spec
contract for one ``fix-*`` subcommand. ``conftest.py`` provides the
fixture seeder; this module owns the Gherkin-to-Python wiring and the
JSON-shape assertions per command.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from tests.step_defs.conftest import (
    _LEGACY_CLEAN_ADMIN,  # type: ignore[attr-defined]
    _LEGACY_CLEAN_VIEWS,  # type: ignore[attr-defined]
    commit_legacy_dirty_state,
    interlocks_pythonpath_env,
    make_legacy_greenfield_project,
    run_interlock_in_cwd,
)

scenarios(str(Path(__file__).parent.parent / "features" / "interlock_fix.feature"))


@given(
    "a legacy greenfield project with no quality-gate configuration",
    target_fixture="greenfield_project",
)
def _greenfield_project(tmp_path: Path) -> Path:
    return make_legacy_greenfield_project(tmp_path)


@when(
    parsers.parse('I run "interlocks {subcmd}" in the greenfield project'),
    target_fixture="greenfield_result",
)
def _run_in_greenfield(greenfield_project: Path, subcmd: str) -> subprocess.CompletedProcess[str]:
    return run_interlock_in_cwd(
        greenfield_project, *shlex.split(subcmd), env=interlocks_pythonpath_env()
    )


@then("the greenfield command exits 0")
def _exits_zero(greenfield_result: subprocess.CompletedProcess[str]) -> None:
    assert greenfield_result.returncode == 0, _detail(greenfield_result)


@then(parsers.parse('the file "{relpath}" exists in the greenfield project'))
def _file_exists(greenfield_project: Path, relpath: str) -> None:
    assert (greenfield_project / relpath).is_file(), f"missing {relpath}"


@given("the greenfield project has a few-commit history")
def _few_commit_history(greenfield_project: Path) -> None:
    """Commit the seeded violations, then add a second mainline commit.

    ``fix-replay`` walks ``git rev-list --first-parent -n<N> <base>``, so
    we need at least two commits past the baseline for ``--n=2`` to find
    something to plan against. Both commits introduce I001 deltas vs.
    their parent.
    """
    commit_legacy_dirty_state(greenfield_project, message="introduce I001 + F401")
    extra = greenfield_project / "src" / "legacy" / "more.py"
    extra.write_text("import sys\nimport os\n\nprint(os.name, sys.version)\n", encoding="utf-8")
    commit_legacy_dirty_state(greenfield_project, message="more I001 churn")


@given("the greenfield project working tree is clean")
def _greenfield_clean_tree(greenfield_project: Path) -> None:
    """Restore the seeded files to the clean baseline content.

    ``fix-optimize --base=HEAD`` then sees no diff and no candidates,
    matching the spec §6.5 default-non-mutating contract on a clean tree.
    """
    (greenfield_project / "src" / "legacy" / "views.py").write_text(
        _LEGACY_CLEAN_VIEWS, encoding="utf-8"
    )
    (greenfield_project / "src" / "legacy" / "admin.py").write_text(
        _LEGACY_CLEAN_ADMIN, encoding="utf-8"
    )


@then(parsers.parse('the plan classifies rule "{rule}" as "{classification}"'))
def _plan_classifies(greenfield_project: Path, rule: str, classification: str) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "plan.json").read_text(encoding="utf-8")
    )
    by_rule = {c["rule"]: c for c in payload["candidates"]}
    assert rule in by_rule, f"{rule} missing from plan: {sorted(by_rule)}"
    assert by_rule[rule]["classification"] == classification, by_rule[rule]


@then(
    parsers.parse('every unsafe candidate is classified as skip with reason mentioning "{needle}"')
)
def _unsafe_only_invariant(greenfield_project: Path, needle: str) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "plan.json").read_text(encoding="utf-8")
    )
    for c in payload["candidates"]:
        if not c.get("unsafe"):
            continue
        assert c["classification"] == "skip", c
        reason = c.get("reason") or ""
        assert needle in reason.lower(), c


@then("the replay payload exposes per-rule statistics keys")
def _replay_payload_keys(greenfield_project: Path) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "replay.json").read_text(encoding="utf-8")
    )
    assert isinstance(payload.get("rules"), list), payload
    required = {
        "prs_helped",
        "median_changed_lines",
        "p95_outside_diff_lines",
        "recommended_mode",
    }
    for row in payload["rules"]:
        missing = required - row.keys()
        assert not missing, f"rule {row.get('rule')!r} missing keys: {missing}"


@then("the optimize selected list is empty")
def _optimize_selected_empty(greenfield_project: Path) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "optimize.json").read_text(encoding="utf-8")
    )
    assert payload["selected"] == [], payload


@then("no selected candidate is unsafe")
def _no_unsafe_selected(greenfield_project: Path) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "optimize.json").read_text(encoding="utf-8")
    )
    for entry in payload["selected"]:
        assert entry["unsafe"] is False, entry


@then("the greenfield output has no annotation lines")
def _no_annotation_lines(greenfield_result: subprocess.CompletedProcess[str]) -> None:
    combined = greenfield_result.stdout + greenfield_result.stderr
    assert "::notice file=" not in combined, combined
    assert "::warning file=" not in combined, combined


@then("the metrics sources truthtable is all false")
def _metrics_sources_all_false(greenfield_project: Path) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "metrics.json").read_text(encoding="utf-8")
    )
    sources = payload["sources"]
    assert sources == {"plan": False, "optimize": False, "replay": False}, sources


@then("the greenfield output has annotation lines")
def _has_annotation_lines(greenfield_result: subprocess.CompletedProcess[str]) -> None:
    combined = greenfield_result.stdout + greenfield_result.stderr
    assert "::notice file=" in combined or "::warning file=" in combined, combined


@then("the metrics sources include plan and optimize")
def _metrics_sources_include_plan_optimize(greenfield_project: Path) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "metrics.json").read_text(encoding="utf-8")
    )
    sources = payload["sources"]
    assert sources["plan"] is True, sources
    assert sources["optimize"] is True, sources


@then(parsers.parse('the optimize rejects rule "{rule}" with reason mentioning "{needle}"'))
def _optimize_rejects_rule(greenfield_project: Path, rule: str, needle: str) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "optimize.json").read_text(encoding="utf-8")
    )
    by_rule = {c["rule"]: c for c in payload["not_selected"]}
    assert rule in by_rule, f"{rule} missing from not_selected: {sorted(by_rule)}"
    reason = by_rule[rule]["reason"] or ""
    assert needle in reason, by_rule[rule]


@then("the optimize totals equal the sum of the selected subset")
def _optimize_totals_match_selected(greenfield_project: Path) -> None:
    payload = json.loads(
        (greenfield_project / ".lintfix" / "optimize.json").read_text(encoding="utf-8")
    )
    selected = payload["selected"]
    assert payload["total_value"] == sum(c["value"] for c in selected), payload
    total_cost = payload["total_cost"]
    for dim in ("outside_diff", "changed_lines", "files", "risk"):
        assert total_cost[dim] == sum(c["cost"][dim] for c in selected), (dim, payload)


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return f"exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
