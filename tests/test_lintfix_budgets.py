"""Budget profile selection + check_budget pass/fail edge cases."""

from __future__ import annotations

from interlocks.lintfix.budgets import (
    RENOVATION,
    UNBLOCK,
    CandidateCost,
    check_budget,
    dynamic,
    profile,
)


def _cost(**overrides: int | bool) -> CandidateCost:
    defaults: dict[str, int | bool] = {
        "files_touched": 1,
        "changed_lines_total": 10,
        "changed_lines_outside_diff": 0,
        "risk": 2,
        "unsafe": False,
    }
    defaults.update(overrides)
    return CandidateCost(**defaults)  # type: ignore[arg-type]


def test_profile_lookup() -> None:
    assert profile("unblock") is UNBLOCK
    assert profile("renovation") is RENOVATION


def test_unknown_profile_defaults_to_unblock() -> None:
    assert profile("nonsense") is UNBLOCK


def test_check_budget_passes_within_limits() -> None:
    assert check_budget(_cost(), UNBLOCK) is None


def test_check_budget_blocks_unsafe() -> None:
    reason = check_budget(_cost(unsafe=True), UNBLOCK)
    assert reason == "unsafe fix not allowed"


def test_check_budget_blocks_files() -> None:
    reason = check_budget(_cost(files_touched=UNBLOCK.max_files + 1), UNBLOCK)
    assert reason is not None
    assert reason.startswith("files ")


def test_check_budget_blocks_outside_diff() -> None:
    reason = check_budget(
        _cost(changed_lines_outside_diff=UNBLOCK.max_outside_diff_lines + 1), UNBLOCK
    )
    assert reason is not None
    assert "outside-diff" in reason


def test_check_budget_blocks_risk() -> None:
    reason = check_budget(_cost(risk=UNBLOCK.max_risk + 1), UNBLOCK)
    assert reason is not None
    assert reason.startswith("risk ")


def test_renovation_admits_what_unblock_blocks() -> None:
    big = _cost(
        files_touched=20,
        changed_lines_total=500,
        changed_lines_outside_diff=200,
        risk=25,
    )
    assert check_budget(big, UNBLOCK) is not None
    assert check_budget(big, RENOVATION) is None


def test_dynamic_micro_change_has_zero_outside_hunk_budget() -> None:
    budget = dynamic(10)
    assert budget.name == "dynamic"
    assert budget.max_changed_lines == 5
    assert budget.max_outside_diff_lines == 0


def test_dynamic_normal_change_uses_ratio() -> None:
    budget = dynamic(100)
    assert budget.max_changed_lines == 33
    assert budget.max_outside_diff_lines == 5


def test_dynamic_large_change_uses_absolute_caps() -> None:
    budget = dynamic(10_000)
    assert budget.max_changed_lines == 300
    assert budget.max_outside_diff_lines == 50


def test_profile_dynamic_uses_author_cost() -> None:
    assert profile("dynamic", author_cost=100).max_changed_lines == 33
