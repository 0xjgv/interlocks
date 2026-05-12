"""Classifier: metrics extraction, risk scoring, mode decision."""

from __future__ import annotations

from interlocks.lintfix.budgets import UNBLOCK
from interlocks.lintfix.classify import classify, measure
from interlocks.lintfix.diff import FileHunks, Hunk
from interlocks.lintfix.rules import policy_for

_I001_PATCH = """\
--- a/pkg/views.py
+++ b/pkg/views.py
@@ -1,3 +1,3 @@
-import os
-import sys
+import sys
+import os
"""

_F401_PATCH = """\
--- a/pkg/admin.py
+++ b/pkg/admin.py
@@ -1,2 +1,1 @@
-import unused_mod
 from .models import Thing
"""

_SIM_OUTSIDE_PATCH = """\
--- a/pkg/views.py
+++ b/pkg/views.py
@@ -50,3 +50,3 @@
-if x == True:
+if x:
@@ -100,2 +100,2 @@
-if y == False:
+if not y:
"""


def _hunks(path: str, *ranges: tuple[int, int]) -> dict[str, FileHunks]:
    return {path: FileHunks(path, tuple(Hunk(s, e) for s, e in ranges))}


def test_measure_counts_files_and_lines() -> None:
    m = measure(_I001_PATCH, _hunks("pkg/views.py", (1, 5)))
    assert m.files_touched == ("pkg/views.py",)
    # 2 deletions + 2 insertions, all at OLD lines 1..3 (inside the seeded hunk).
    assert m.changed_lines_total == 4
    assert m.changed_lines_inside_diff == 4
    assert m.changed_lines_outside_diff == 0


def test_measure_counts_outside_diff_for_far_hunks() -> None:
    m = measure(_SIM_OUTSIDE_PATCH, _hunks("pkg/views.py", (1, 5)))
    # 2 deletions + 2 insertions at OLD lines 50, 100 — all outside hunks 1..5.
    assert m.changed_lines_total == 4
    assert m.changed_lines_inside_diff == 0
    assert m.changed_lines_outside_diff == 4


def test_classify_i001_auto_when_budget_passes() -> None:
    result = classify(
        patch_text=_I001_PATCH,
        diff_hunks=_hunks("pkg/views.py", (1, 5)),
        policy=policy_for("I001"),
        budget=UNBLOCK,
    )
    assert result.mode == "auto"
    assert result.reason is None
    assert result.patch_id == "I001:pkg/views.py"


def test_classify_f401_stays_escrow_even_when_budget_passes() -> None:
    result = classify(
        patch_text=_F401_PATCH,
        diff_hunks=_hunks("pkg/admin.py", (1, 5)),
        policy=policy_for("F401"),
        budget=UNBLOCK,
    )
    assert result.mode == "escrow"


def test_classify_skip_on_empty_patch() -> None:
    result = classify(
        patch_text="",
        diff_hunks={},
        policy=policy_for("I001"),
        budget=UNBLOCK,
    )
    assert result.mode == "skip"


def test_classify_auto_downgrades_to_escrow_on_outside_diff_overflow() -> None:
    # Forge a patch that touches many outside-diff lines.
    big_patch_lines = ["--- a/pkg/x.py", "+++ b/pkg/x.py", "@@ -1000,0 +1000,20 @@"]
    big_patch_lines.extend(f"+line_{i}" for i in range(20))
    patch = "\n".join(big_patch_lines) + "\n"
    result = classify(
        patch_text=patch,
        diff_hunks=_hunks("pkg/x.py", (1, 5)),
        policy=policy_for("I001"),
        budget=UNBLOCK,
    )
    assert result.mode == "escrow"
    assert result.reason is not None
    assert "outside-diff" in result.reason


def test_risky_path_increases_risk() -> None:
    patch = (
        "--- a/pkg/migrations/0001_init.py\n"
        "+++ b/pkg/migrations/0001_init.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-import a\n"
        "+import b\n"
    )
    result = classify(
        patch_text=patch,
        diff_hunks=_hunks("pkg/migrations/0001_init.py", (1, 5)),
        policy=policy_for("I001"),
        budget=UNBLOCK,
    )
    # base_risk(2) + migrations(+10) > UNBLOCK.max_risk(8) → downgrades to escrow.
    assert result.mode == "escrow"
    assert "risk" in (result.reason or "")
