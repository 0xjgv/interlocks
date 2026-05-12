"""Unit tests for ``interlocks.lintfix.plan`` orchestrator + serializer.

Real ruff is bypassed — :func:`monkeypatch` stubs ``simulate.simulate_rule``
and ``discover.discover_fixable_rules`` so each test runs in milliseconds and
isolates the orchestration logic.
"""

from __future__ import annotations

import json

import pytest

from interlocks.lintfix import discover, simulate
from interlocks.lintfix import plan as plan_module
from interlocks.lintfix.diff import FileHunks, Hunk


def _stub_files(monkeypatch: pytest.MonkeyPatch, *, base_sha: str, files: tuple[str, ...]) -> None:
    monkeypatch.setattr(plan_module.diff, "resolve_base", lambda _: base_sha)
    monkeypatch.setattr(plan_module.diff, "changed_files", lambda _: files)
    monkeypatch.setattr(
        plan_module.diff,
        "changed_hunks",
        lambda _base, fs: {f: FileHunks(f, (Hunk(1, 200),)) for f in fs},
    )
    monkeypatch.setattr(plan_module.diff, "head_sha", lambda: "HEAD_SHA")


_I001_PATCH = """\
--- a/sample.py
+++ b/sample.py
@@ -1,3 +1,3 @@
-import sys
-import os
+import os
+import sys
"""


def test_build_plan_classifies_safe_fixable_rule_as_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_files(monkeypatch, base_sha="BASE", files=("sample.py",))
    monkeypatch.setattr(
        discover,
        "discover_fixable_rules",
        lambda files: discover.DiscoveryResult(
            (discover.RuleCandidate("I001", files, True, False, 1),), 1, ""
        ),
    )
    monkeypatch.setattr(
        simulate,
        "simulate_rule",
        lambda rule, files: simulate.CandidatePatch(rule, files, _I001_PATCH, 0),
    )

    plan = plan_module.build_plan(base="origin/main", budget_name="unblock")
    [candidate] = plan.candidates
    assert candidate.classification.rule == "I001"
    assert candidate.classification.mode == "auto"
    assert candidate.unsafe is False
    assert candidate.mutation_class == "import_sort"


def test_build_plan_marks_unsafe_only_rule_as_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unsafe-only rules never invoke ruff a second time and report ``skip``."""
    _stub_files(monkeypatch, base_sha="BASE", files=("sample.py",))
    monkeypatch.setattr(
        discover,
        "discover_fixable_rules",
        lambda files: discover.DiscoveryResult(
            (discover.RuleCandidate("T201", files, False, True, 3),), 1, ""
        ),
    )

    def _no_simulate(*_args: object, **_kw: object) -> simulate.CandidatePatch:
        msg = "simulate must not be called for unsafe-only rules"
        raise AssertionError(msg)

    monkeypatch.setattr(simulate, "simulate_rule", _no_simulate)

    plan = plan_module.build_plan(base="origin/main", budget_name="unblock")
    [candidate] = plan.candidates
    assert candidate.classification.mode == "skip"
    assert candidate.unsafe is True
    assert candidate.classification.reason and "unsafe" in candidate.classification.reason


def test_build_plan_simulates_only_files_with_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulation is scoped to the rule's hit-files, not the full changed set."""
    _stub_files(monkeypatch, base_sha="BASE", files=("a.py", "b.py", "c.py"))
    rule_files = ("b.py",)
    monkeypatch.setattr(
        discover,
        "discover_fixable_rules",
        lambda files: discover.DiscoveryResult(
            (discover.RuleCandidate("I001", rule_files, True, False, 1),), 1, ""
        ),
    )
    seen: list[tuple[str, ...]] = []

    def _record(rule: str, files: tuple[str, ...]) -> simulate.CandidatePatch:
        seen.append(files)
        return simulate.CandidatePatch(rule, files, _I001_PATCH, 0)

    monkeypatch.setattr(simulate, "simulate_rule", _record)

    plan_module.build_plan(base="origin/main", budget_name="unblock")
    assert seen == [rule_files]


def test_build_plan_empty_when_base_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_files(monkeypatch, base_sha="", files=())
    plan = plan_module.build_plan(base="origin/main", budget_name="unblock")
    assert plan.candidates == ()
    assert plan.discovery_error is None
    assert plan.head == "HEAD_SHA"


def test_build_plan_empty_when_no_changed_files(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_files(monkeypatch, base_sha="BASE", files=())
    plan = plan_module.build_plan(base="origin/main", budget_name="unblock")
    assert plan.candidates == ()
    assert plan.discovery_error is None


def test_build_plan_surfaces_ruff_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_files(monkeypatch, base_sha="BASE", files=("sample.py",))
    monkeypatch.setattr(
        discover,
        "discover_fixable_rules",
        lambda files: discover.DiscoveryResult((), 2, "boom"),
    )
    plan = plan_module.build_plan(base="origin/main", budget_name="unblock")
    assert plan.candidates == ()
    assert plan.discovery_error is not None
    assert plan.discovery_error.returncode == 2
    assert plan.discovery_error.stderr == "boom"


def test_serialize_matches_spec_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_files(monkeypatch, base_sha="BASE", files=("sample.py",))
    monkeypatch.setattr(
        discover,
        "discover_fixable_rules",
        lambda files: discover.DiscoveryResult(
            (discover.RuleCandidate("I001", files, True, False, 1),), 1, ""
        ),
    )
    monkeypatch.setattr(
        simulate,
        "simulate_rule",
        lambda rule, files: simulate.CandidatePatch(rule, files, _I001_PATCH, 0),
    )

    plan = plan_module.build_plan(base="origin/main", budget_name="unblock")
    payload = plan_module.serialize(plan, patch_paths={"I001": ".lintfix/escrow/I001.patch"})

    assert payload["base"] == "origin/main"
    assert payload["mode"] == "unblock"
    assert payload["head"] == "HEAD_SHA"
    [c] = payload["candidates"]
    expected_keys = {
        "id",
        "rule",
        "mode",
        "classification",
        "mutation_class",
        "files_touched",
        "changed_lines_total",
        "changed_lines_inside_diff",
        "changed_lines_outside_diff",
        "risk",
        "diagnostic_count",
        "unsafe",
        "patch_path",
        "reason",
    }
    assert set(c) == expected_keys
    assert c["rule"] == "I001"
    assert c["mode"] == "auto"
    assert c["mutation_class"] == "import_sort"
    assert c["patch_path"] == ".lintfix/escrow/I001.patch"


def test_write_plan_json_creates_dir_and_writes_payload(tmp_path) -> None:
    payload = {"base": "main", "candidates": []}
    target = plan_module.write_plan_json(tmp_path, payload)
    assert target == tmp_path / ".lintfix" / "plan.json"
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_materialize_escrow_skips_auto_and_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Only escrow/advisory candidates with non-empty diffs reach disk."""
    _stub_files(monkeypatch, base_sha="BASE", files=("sample.py",))
    monkeypatch.setattr(
        discover,
        "discover_fixable_rules",
        lambda files: discover.DiscoveryResult(
            (
                discover.RuleCandidate("I001", files, True, False, 1),  # auto, has patch
                discover.RuleCandidate("F401", files, True, False, 1),  # escrow, has patch
            ),
            1,
            "",
        ),
    )
    patches = {
        "I001": _I001_PATCH,
        "F401": "--- a/sample.py\n+++ b/sample.py\n@@ -1,1 +1,0 @@\n-import json\n",
    }
    monkeypatch.setattr(
        simulate,
        "simulate_rule",
        lambda rule, files: simulate.CandidatePatch(rule, files, patches[rule], 0),
    )

    plan = plan_module.build_plan(base="origin/main", budget_name="unblock")
    paths = plan_module.materialize_escrow_patches(tmp_path, plan)

    # Auto candidate is NOT materialized (it's meant for fix-rule --apply).
    assert "I001" not in paths
    # Escrow candidate IS materialized.
    assert "F401" in paths
    assert (tmp_path / ".lintfix" / "escrow" / "F401.patch").is_file()
