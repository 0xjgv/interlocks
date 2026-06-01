"""Tests for static `interlocks evaluate` report."""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from pathlib import Path
from typing import cast

import pytest

from interlocks.config import InterlockConfig, load_config
from interlocks.defaults_path import path as defaults_path
from interlocks.tasks import evaluate as evaluate_mod
from interlocks.tasks.evaluate import (
    _ITEM_COUNT,
    ClosurePath,
    EvaluationItem,
    cmd_evaluate,
    evaluate,
)
from tests.conftest import TmpProjectFactory


def _pyproject(
    *,
    branch: bool = True,
    mutation_mode: str = "full",
    run_mutation_in_ci: bool | None = None,
    importlinter: bool = True,
) -> str:
    legacy_mutation_line = ""
    if run_mutation_in_ci is not None:
        value = str(run_mutation_in_ci).lower()
        legacy_mutation_line = f"run_mutation_in_ci = {value}\n"
    body = f"""\
    [project]
    name = "pkg"
    version = "0.0.0"
    requires-python = ">=3.11"

    [dependency-groups]
    dev = ["pytest>=9", "pytest-bdd>=8"]

    [tool.interlocks]
    preset = "strict"
    src_dir = "pkg"
    test_dir = "tests"
    test_runner = "pytest"
    test_invoker = "python"
    mutation_ci_mode = "{mutation_mode}"
    evaluate_dependency_freshness = true
    audit_severity_threshold = "high"
    pr_ci_runtime_budget_seconds = 600
    {legacy_mutation_line}
    [tool.coverage.run]
    source = ["pkg"]
    branch = {str(branch).lower()}

    [tool.mutmut]
    paths_to_mutate = ["pkg/"]
    tests_dir = ["tests/"]
    """
    if importlinter:
        body += """\

        [tool.importlinter]
        root_packages = ["pkg", "tests"]

        [[tool.importlinter.contracts]]
        name = "Production does not import tests"
        type = "forbidden"
        source_modules = ["pkg"]
        forbidden_modules = ["tests"]
        """
    return textwrap.dedent(body)


_SRC_FILES = {"pkg/__init__.py": ""}
_TEST_FILES = {"test_smoke.py": "def test_ok() -> None:\n    assert True\n"}
_PROPERTY_FILES = {
    "test_lengths.py": "def test_reversing_preserves_length() -> None:\n    assert True\n"
}
_FEATURE = """\
Feature: checkout

  @req-checkout
  Scenario: paid order succeeds
    Given buyer has cart
    When buyer pays
    Then order is created
"""
_UNTRACED_FEATURE = """\
Feature: checkout

  Scenario: paid order succeeds
    Given buyer has cart
    When buyer pays
    Then order is created
"""
_WORKFLOW = """\
name: ci
on: [push]
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - run: uv run interlocks ci
"""


def _write_dedented(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _project(make_tmp_project: TmpProjectFactory, **overrides: object) -> Path:
    pyproject = cast("str | None", overrides.pop("pyproject", None))
    test_files = cast("dict[str, str] | None", overrides.pop("test_files", None))
    property_files = cast(
        "dict[str, str] | None",
        overrides.pop("property_files", _PROPERTY_FILES),
    )
    feature = cast("str | None", overrides.pop("feature", _FEATURE))
    workflow = cast("str | None", overrides.pop("workflow", _WORKFLOW))
    if overrides:
        raise AssertionError(f"unexpected project override(s): {sorted(overrides)}")
    project = make_tmp_project(
        pyproject=_pyproject() if pyproject is None else pyproject,
        src_files=_SRC_FILES,
        test_files=_TEST_FILES if test_files is None else test_files,
    )
    if feature is not None:
        _write_dedented(project / "tests" / "features" / "checkout.feature", feature)
    if property_files is not None:
        for name, content in property_files.items():
            _write_dedented(project / "properties" / name, content)
    if workflow is not None:
        _write_dedented(project / ".github" / "workflows" / "ci.yml", workflow)
    _write_ci_evidence(project)
    return project


def _write_ci_evidence(
    project: Path,
    *,
    elapsed_seconds: float = 30.0,
    created_at: float | None = None,
    passed: bool = True,
    skipped: list[str] | None = None,
) -> None:
    path = project / ".interlocks" / "ci.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "command": "interlocks ci",
        "elapsed_seconds": elapsed_seconds,
        "created_at": time.time() if created_at is None else created_at,
        "passed": passed,
    }
    if skipped:
        payload["skipped"] = skipped
    path.write_text(json.dumps(payload), encoding="utf-8")


def _item(cfg: InterlockConfig, category: str) -> EvaluationItem:
    report = evaluate(cfg)
    return next(item for item in report.items if item.category == category)


def test_all_pass_project_scores_36_of_36(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_project(make_tmp_project))
    report = evaluate(load_config())

    assert report.total == 36
    assert report.max_total == 36
    assert report.verdict == "HEALTHY"
    assert all(item.score == 3 for item in report.items)


def test_comment_before_scenario_counts_as_traceability(tmp_path: Path) -> None:
    feature = tmp_path / "checkout.feature"
    feature.write_text(
        textwrap.dedent(
            """\
            Feature: checkout

              # req: checkout-paid
              Scenario: paid order succeeds
                Given buyer has cart
            """
        ),
        encoding="utf-8",
    )

    assert evaluate_mod._feature_scenarios_with_traceability(feature) == (1, 1)


def test_missing_feature_files_scores_acceptance_lower_and_emits_next_action(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, feature=None)
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 0
    assert item.next_action == "Run `interlocks init-acceptance` to scaffold feature files."


def test_feature_file_with_no_scenarios_scores_acceptance_one(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, feature="Feature: checkout\n")
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 1
    assert "Add at least one Scenario" in (item.next_action or "")


def test_acceptance_disabled_scores_as_not_ci_wired(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'mutation_ci_mode = "full"\n',
        'mutation_ci_mode = "full"\nacceptance_runner = "off"\n',
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 1
    assert item.next_action == (
        "Enable acceptance runner so `interlocks ci` can run feature scenarios."
    )


def test_behavior_coverage_gap_drives_acceptance_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace('name = "pkg"', 'name = "interlocks"')
    project = _project(make_tmp_project, pyproject=pyproject, feature=_UNTRACED_FEATURE)
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 1
    assert item.next_action is not None
    assert "# req: " in item.next_action
    assert "@req-" in item.next_action


def test_scenario_without_traceability_tag_lowers_acceptance_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, feature=_UNTRACED_FEATURE)
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 1
    assert item.next_action is not None
    assert "@req-*" in item.next_action


def test_missing_tests_lowers_unit_test_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, test_files={})
    monkeypatch.chdir(project)

    item = _item(load_config(), "unit-tests")

    assert item.score == 0
    assert "Add test_*.py" in (item.next_action or "")


def test_missing_property_tests_lowers_properties_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, property_files=None)
    monkeypatch.chdir(project)

    item = _item(load_config(), "properties")

    assert item.score == 0
    assert item.detail == "no property tests detected"
    assert "init-properties" in (item.next_action or "")


def test_scaffold_only_property_tests_do_not_score_as_domain_properties(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = defaults_path("properties_test_example.py").read_text(encoding="utf-8")
    project = _project(
        make_tmp_project,
        property_files={"test_example_properties.py": example},
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "properties")

    assert item.score == 1
    assert item.detail == "only scaffold example property detected"
    assert "Replace properties/test_example_properties.py" in (item.next_action or "")


def test_scaffold_only_property_next_action_uses_configured_dir(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'test_dir = "tests"\n',
        'test_dir = "tests"\nproperties_dir = "tests/properties"\n',
    )
    example = defaults_path("properties_test_example.py").read_text(encoding="utf-8")
    project = _project(make_tmp_project, pyproject=pyproject, property_files=None)
    _write_dedented(project / "tests" / "properties" / "test_example_properties.py", example)
    monkeypatch.chdir(project)

    item = _item(load_config(), "properties")

    assert item.score == 1
    assert item.next_action == (
        "Replace tests/properties/test_example_properties.py with domain invariants."
    )


def test_domain_property_tests_report_ci_wiring_detail(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)

    item = _item(load_config(), "properties")

    assert item.score == 3
    assert item.detail == "domain properties in CI"


def test_domain_property_tests_without_ci_wiring_report_partial_detail(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)
    monkeypatch.setattr(evaluate_mod, "_ci_source_contains", lambda _needle: False)

    item = _item(load_config(), "properties")

    assert item.score == 1
    assert item.detail == "domain properties present but not wired into CI"
    assert item.next_action == "Wire task_properties() into `interlocks ci`."


def test_coveragerc_branch_setting_is_read_when_pyproject_coverage_absent(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        '[tool.coverage.run]\nsource = ["pkg"]\nbranch = true\n\n',
        "",
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    (project / ".coveragerc").write_text("[run]\nbranch = false\n", encoding="utf-8")
    monkeypatch.chdir(project)

    item = _item(load_config(), "coverage")

    assert item.score == 2
    assert item.next_action == "Enable branch coverage in [tool.coverage.run]."


def test_coverage_min_zero_scores_coverage_zero(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'preset = "strict"\n',
        'preset = "strict"\ncoverage_min = 0\n',
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "coverage")

    assert item.score == 0
    assert item.next_action == "Set coverage_min to at least 80."


def test_coverage_min_below_80_scores_coverage_two(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'preset = "strict"\n',
        'preset = "strict"\ncoverage_min = 79\n',
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "coverage")

    assert item.score == 2
    assert item.next_action == "Raise coverage_min to at least 80."


def test_missing_branch_coverage_lowers_coverage_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, pyproject=_pyproject(branch=False))
    monkeypatch.chdir(project)

    item = _item(load_config(), "coverage")

    assert item.score == 2
    assert item.next_action == "Enable branch coverage in [tool.coverage.run]."


def test_missing_mutmut_config_lowers_mutation_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        '[tool.mutmut]\npaths_to_mutate = ["pkg/"]\ntests_dir = ["tests/"]\n',
        "",
    )
    project = _project(make_tmp_project, pyproject=pyproject, test_files={})
    monkeypatch.chdir(project)

    item = _item(load_config(), "mutation")

    assert item.score == 0
    assert "[tool.mutmut]" in (item.next_action or "")


def test_mutation_ci_without_enforcement_scores_two(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'mutation_ci_mode = "full"\n',
        'mutation_ci_mode = "full"\nenforce_mutation = false\n',
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "mutation")

    assert item.score == 2
    assert item.next_action == "Set enforce_mutation = true and mutation_min_score > 0."


def test_mutation_item_surfaces_partial_cached_evidence(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    evidence = project / ".interlocks/mutation.json"
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text('{"completed": false}', encoding="utf-8")
    monkeypatch.chdir(project)

    item = _item(load_config(), "mutation")

    assert item.score == 2
    assert item.status == "warn"
    assert "latest evidence partial" in item.detail
    assert item.next_action == ("Rerun `interlocks mutation --min-score=85 --max-runtime=900`.")
    assert item.closure is not None
    assert item.closure.command == "interlocks nightly"


def test_mutation_item_surfaces_no_result_cached_evidence(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    evidence = project / ".interlocks/mutation.json"
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text('{"completed": false, "no_results": true}', encoding="utf-8")
    monkeypatch.chdir(project)

    item = _item(load_config(), "mutation")

    assert item.score == 2
    assert item.status == "warn"
    assert "latest evidence had no checked mutants" in item.detail
    assert item.next_action == (
        "Rerun `interlocks mutation --min-score=85 --max-runtime=900` "
        "with more runtime, or use `--changed-only` for a bounded pass."
    )
    assert item.closure is not None
    assert item.closure.command == "interlocks nightly"


def test_mutation_off_lowers_mutation_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(
        make_tmp_project,
        pyproject=_pyproject(mutation_mode="off", run_mutation_in_ci=False),
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "mutation")

    assert item.score == 1
    assert item.next_action == 'Set mutation_ci_mode = "incremental" or "full".'


def test_advisory_crap_lowers_complexity_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'mutation_ci_mode = "full"\n',
        'mutation_ci_mode = "full"\nenforce_crap = false\n',
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "complexity")

    assert item.score == 2
    assert item.next_action == "Set enforce_crap = true."


def test_missing_complexity_thresholds_score_zero(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace(
        'mutation_ci_mode = "full"\n',
        'mutation_ci_mode = "full"\ncomplexity_max_ccn = 0\ncomplexity_max_args = 0\n'
        "complexity_max_loc = 0\ncrap_max = 0\n",
    )
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "complexity")

    assert item.score == 0
    assert item.next_action == "Set positive complexity_max_* and crap_max thresholds."


def test_missing_import_linter_contracts_lowers_dependency_rules_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, pyproject=_pyproject(importlinter=False))
    monkeypatch.chdir(project)

    item = _item(load_config(), "deps")

    assert item.score == 0
    assert "importlinter" in (item.next_action or "")


def test_default_arch_contract_scores_dependency_rules_two(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(
        make_tmp_project,
        pyproject=_pyproject(importlinter=False),
        test_files={"__init__.py": "", **_TEST_FILES},
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "deps")

    assert item.score == 2
    assert item.next_action == "Add forbidden, layers, or acyclic import-linter contracts."


def test_import_linter_sidecar_contract_scores_dependency_rules_three(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, pyproject=_pyproject(importlinter=False))
    (project / ".importlinter").write_text(
        textwrap.dedent(
            """\
            [importlinter]
            root_package = pkg

            [importlinter:contract:no-tests]
            name = Production does not import tests
            type = forbidden
            source_modules = pkg
            forbidden_modules = tests
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "deps")

    assert item.score == 3


def test_audit_absent_from_ci_lowers_security_score(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        evaluate_mod,
        "_ci_source_contains",
        lambda needle: needle != "task_audit(",
    )

    item = _item(load_config(), "security")

    assert item.score == 2
    assert item.next_action == "Wire task_audit() into `interlocks ci`."


def test_audit_not_exposed_scores_security_zero(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)
    monkeypatch.setattr(evaluate_mod, "_cli_source_contains", lambda _needle: False)

    item = _item(load_config(), "security")

    assert item.score == 0
    assert item.next_action == "Expose `interlocks audit` and task_audit()."


def test_deps_absent_from_ci_lowers_security_score(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        evaluate_mod,
        "_ci_source_contains",
        lambda needle: needle != "task_deps(",
    )

    item = _item(load_config(), "security")

    assert item.score == 2
    assert item.next_action == "Wire task_deps() into `interlocks ci`."


# ─────────────── added gap-closure policies ─────────────────────


def test_evaluate_reports_advisory_trace_detail(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    trace_path = project / ".interlocks" / "acceptance-trace.json"
    trace_path.write_text(
        json.dumps({
            "symbols": [
                {"symbol": "pkg:checkout", "reached": True},
                {"symbol": "pkg:cancel", "reached": False},
            ]
        }),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert "advisory trace (1/2 reached)" in item.detail
    assert item.score == 3


def test_partial_acceptance_traceability_reports_missing_count(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    feature = """\
    Feature: checkout

      @req-paid-order
      Scenario: paid order succeeds
        Given buyer has cart

      Scenario: cancelled order releases stock
        Given buyer has cart
    """
    project = _project(make_tmp_project, feature=feature)
    monkeypatch.chdir(project)

    item = _item(load_config(), "acceptance")

    assert item.score == 2
    assert item.next_action == "Add @req-* tags or # req: comments to 1 acceptance scenario(s)."
    assert item.closure is not None
    assert item.closure.command == "interlocks evaluate"


def test_req_marker_inside_scenario_body_does_not_count_as_traceability(tmp_path: Path) -> None:
    feature = tmp_path / "checkout.feature"
    feature.write_text(
        textwrap.dedent(
            """\
            Feature: checkout

              Scenario: paid order succeeds
                # req: too-late
                Given buyer has cart
            """
        ),
        encoding="utf-8",
    )

    assert evaluate_mod._feature_scenarios_with_traceability(feature) == (1, 0)


def test_dependency_freshness_absent_policy_scores_separately(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace("evaluate_dependency_freshness = true\n", "")
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "deps-freshness")

    assert item.score == 0
    assert item.next_action is not None
    assert "interlocks deps-freshness" in item.next_action
    assert _item(load_config(), "security").score == 3


def test_dependency_freshness_configured_scores_without_live_lookup(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks import deps_freshness as deps_freshness_mod

    def fail_if_called(*_args: object, **_kwargs: object) -> list[str]:
        raise AssertionError("evaluate must not perform package-index lookup")

    monkeypatch.setattr(deps_freshness_mod, "freshness_cmd", fail_if_called)
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)

    item = _item(load_config(), "deps-freshness")

    assert item.score == 3


def test_audit_severity_missing_threshold_scores_partial(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace('audit_severity_threshold = "high"\n', "")
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "audit-severity")

    assert item.score == 2
    assert item.next_action == (
        'Set audit_severity_threshold = "high" for explicit high-severity policy.'
    )


def test_audit_severity_configured_scores_full(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)

    item = _item(load_config(), "audit-severity")

    assert item.score == 3


def test_audit_severity_without_audit_scores_zero(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)
    monkeypatch.setattr(evaluate_mod, "_cli_source_contains", lambda _needle: False)

    item = _item(load_config(), "audit-severity")

    assert item.score == 0
    assert item.next_action == "Expose `interlocks audit` before configuring severity policy."


def test_pr_speed_missing_budget_scores_zero(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = _pyproject().replace("pr_ci_runtime_budget_seconds = 600\n", "")
    project = _project(make_tmp_project, pyproject=pyproject)
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 0
    assert item.next_action == (
        "Set pr_ci_runtime_budget_seconds to declare the PR CI runtime budget."
    )


def test_pr_speed_budget_without_evidence_scores_partial(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    (project / ".interlocks" / "ci.json").unlink()
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 1
    assert item.next_action is not None
    assert "write timing evidence" in item.next_action


def test_pr_speed_stale_evidence_scores_partial(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    _write_ci_evidence(project, created_at=time.time() - 25 * 3600)
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 1
    assert item.next_action is not None
    assert "Refresh stale CI timing evidence" in item.next_action


def test_pr_speed_input_stale_evidence_scores_partial(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    edited = project / "pkg" / "__init__.py"
    edited.write_text("# edited after CI\n", encoding="utf-8")
    future = time.time() + 10
    os.utime(edited, (future, future))
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 1
    assert item.next_action is not None
    assert "source, test, or property inputs changed" in item.next_action


def test_pr_speed_passing_evidence_scores_full(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 3


def test_pr_speed_failing_evidence_scores_partial(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    _write_ci_evidence(project, passed=False)
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 1
    assert item.next_action == "Fix failing `interlocks ci` evidence before scoring PR speed."


def test_pr_speed_skipped_evidence_scores_partial(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project)
    _write_ci_evidence(project, skipped=["mutation", "coverage"])
    monkeypatch.chdir(project)

    item = _item(load_config(), "pr-speed")

    assert item.score == 1
    assert item.next_action == "Run `interlocks ci` without --skip to write full timing evidence."


def test_closure_guidance_covers_task_stage_and_standalone_paths(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(
        make_tmp_project,
        pyproject=_pyproject(mutation_mode="off")
        .replace("evaluate_dependency_freshness = true\n", "")
        .replace(
            'preset = "strict"\n',
            'preset = "strict"\ncoverage_min = 0\nenforce_mutation = false\n',
        ),
        feature=_UNTRACED_FEATURE,
    )
    monkeypatch.chdir(project)
    cfg = load_config()

    acceptance = _item(cfg, "acceptance")
    coverage = _item(cfg, "coverage")
    mutation = _item(cfg, "mutation")
    freshness = _item(cfg, "deps-freshness")

    assert acceptance.closure is not None
    assert acceptance.closure.command == "interlocks evaluate"
    assert acceptance.closure.kind == "task"
    assert "interlocks acceptance only runs scenarios" in acceptance.closure.rationale
    assert coverage.closure is not None
    assert coverage.closure.command == "interlocks ci"
    assert coverage.closure.kind == "stage"
    assert mutation.closure is not None
    assert mutation.closure.command == "interlocks nightly"
    assert mutation.closure.kind == "stage"
    assert freshness.closure is not None
    assert freshness.closure.command == "interlocks deps-freshness"
    assert freshness.closure.kind == "task"


def test_next_actions_include_closure_command(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(make_tmp_project, feature=_UNTRACED_FEATURE)
    monkeypatch.chdir(project)

    cmd_evaluate()

    out = capsys.readouterr().out
    assert "[acceptance] Add @req-* tags" in out
    assert "Close with `interlocks evaluate` (task)" in out


def test_action_workflow_without_local_command_scores_ci_two(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = """\
    name: ci
    on: [push]
    jobs:
      ci:
        runs-on: ubuntu-latest
        steps:
          - uses: 0xjgv/interlocks@v1
    """
    project = _project(make_tmp_project, workflow=workflow)
    monkeypatch.chdir(project)

    item = _item(load_config(), "ci")

    assert item.score == 2
    assert item.next_action == "Make workflow command explicitly reproducible as `interlocks ci`."


def test_unrelated_workflow_scores_ci_one(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = """\
    name: ci
    on: [push]
    jobs:
      ci:
        runs-on: ubuntu-latest
        steps:
          - run: pytest
    """
    project = _project(make_tmp_project, workflow=workflow)
    monkeypatch.chdir(project)

    item = _item(load_config(), "ci")

    assert item.score == 1
    assert item.next_action == "Add `interlocks ci` to a GitHub Actions workflow."


def test_source_contains_returns_false_for_missing_file(tmp_path: Path) -> None:
    assert evaluate_mod._source_contains(tmp_path / "missing.py", "needle") is False


def test_verdicts_cover_all_bands() -> None:
    assert evaluate_mod._verdict(36, 36) == "HEALTHY"
    assert evaluate_mod._verdict(25, 36) == "GAPS"
    assert evaluate_mod._verdict(0, 36) == "NEEDS WORK"
    assert evaluate_mod._verdict(0, 0) == "NEEDS WORK"


def test_workflow_missing_interlocks_ci_lowers_ci_enforcement_score(
    make_tmp_project: TmpProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(make_tmp_project, workflow=None)
    monkeypatch.chdir(project)

    item = _item(load_config(), "ci")

    assert item.score == 0
    assert item.next_action == "Add .github/workflows CI that runs `interlocks ci`."


def test_cmd_evaluate_handles_malformed_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text("not = [valid\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cmd_evaluate()

    out = capsys.readouterr().out
    assert "command=evaluate" in out
    assert "pyproject.toml unreadable" in out
    assert "0 / 36" in out


def test_cmd_evaluate_prints_report_sections(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(make_tmp_project, feature=None, workflow=None)
    monkeypatch.chdir(project)

    cmd_evaluate()

    out = capsys.readouterr().out
    assert "command=evaluate" in out
    assert "── Checklist" in out
    assert "── Score" in out
    assert "── Next Actions" in out
    assert "total" in out


def test_cmd_evaluate_exits_zero_even_for_low_score(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(make_tmp_project, test_files={}, feature=None, workflow=None)
    monkeypatch.chdir(project)

    cmd_evaluate()

    out = capsys.readouterr().out
    assert "command=evaluate" in out
    assert "total" in out
    assert "Next Actions" in out


def test_evaluate_json_is_parseable(
    make_tmp_project: TmpProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(make_tmp_project, feature=None, workflow=None)
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["interlocks", "evaluate", "--json"])

    cmd_evaluate()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "evaluate"
    assert set(payload["score"]) == {"earned", "max"}
    assert payload["verdict"] in {"HEALTHY", "GAPS", "NEEDS WORK"}
    assert len(payload["checks"]) == _ITEM_COUNT
    for check in payload["checks"]:
        assert set(check.keys()) == {
            "name",
            "earned",
            "max",
            "status",
            "rationale",
            "next_action",
            "closure",
        }
    actions = {check["name"]: check for check in payload["checks"]}
    assert actions["acceptance"]["next_action"] == (
        "Run `interlocks init-acceptance` to scaffold feature files."
    )
    assert actions["acceptance"]["closure"] == {
        "command": "interlocks init-acceptance",
        "kind": "task",
        "rationale": "scaffolds acceptance feature files",
    }
    assert actions["ci"]["next_action"] == "Add .github/workflows CI that runs `interlocks ci`."
    assert actions["ci"]["closure"] == {
        "command": "interlocks ci",
        "kind": "stage",
        "rationale": "PR-grade merge gate owner",
    }


def test_evaluate_json_without_pyproject_reports_init_next_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "evaluate", "--json"])

    cmd_evaluate()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "evaluate"
    assert payload["score"] == {"earned": 0, "max": evaluate_mod._MAX_TOTAL}
    assert payload["verdict"] == "NEEDS WORK"
    assert payload["checks"] == []
    assert payload["next_actions"] == [
        "Run `interlocks init` to scaffold pyproject.toml, tests, and interlocks defaults."
    ]


def test_evaluate_human_without_pyproject_reports_init_next_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "evaluate"])

    cmd_evaluate()

    out = capsys.readouterr().out
    assert "Run `interlocks init` to scaffold pyproject.toml" in out
    assert "[acceptance]" not in out
    assert "[properties]" not in out


def test_evaluate_check_json_serializes_optional_action_and_closure() -> None:
    item = EvaluationItem(
        "sample",
        1,
        status="warn",
        detail="needs work",
        next_action="Do the thing.",
        closure=ClosurePath("interlocks sample", "task", "sample owner"),
    )

    assert evaluate_mod._check_json(item) == {
        "name": "sample",
        "earned": 1,
        "max": 3,
        "status": "warn",
        "rationale": "needs work",
        "next_action": "Do the thing.",
        "closure": {
            "command": "interlocks sample",
            "kind": "task",
            "rationale": "sample owner",
        },
    }


def test_evaluate_json_error_when_pyproject_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text("not = [valid\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["interlocks", "evaluate", "--json"])

    cmd_evaluate()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "evaluate"
    assert "error" in payload
