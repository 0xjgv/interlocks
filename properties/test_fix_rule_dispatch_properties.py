"""Property tests for fix-rule dispatch invariants."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix.budgets import CandidateCost
from interlocks.lintfix.classify import CandidateMetrics, Classification
from interlocks.lintfix.simulate import CandidatePatch
from interlocks.lintfix.verify import VerifyResult
from interlocks.tasks import fix_rule

if TYPE_CHECKING:
    from interlocks.lintfix.rules import Mode

_RULES = st.from_regex(r"[A-Z][A-Z0-9]{0,5}", fullmatch=True)
_FILES = st.lists(
    st.from_regex(
        r"(?:src|tests)/(?:[A-Za-z0-9_]{1,8}/){0,2}[A-Za-z0-9_]{1,12}\.py",
        fullmatch=True,
    ),
    max_size=4,
    unique=True,
).map(tuple)
_PATCH_TEXT = st.text(
    alphabet=st.characters(blacklist_characters="\r", blacklist_categories=("Cs",)),
    max_size=120,
)
_MODES = st.sampled_from(("auto", "escrow", "advisory", "skip"))


class _FakeCfg:
    """Minimal config stand-in for dispatch-only tests."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def relpath(self, path: Path) -> str:
        return str(path.relative_to(self.project_root))


def _classification(rule: str, mode: Mode, files: tuple[str, ...]) -> Classification:
    metrics = CandidateMetrics(
        files_touched=files,
        changed_lines_total=max(1, len(files)),
        changed_lines_inside_diff=max(1, len(files)),
        changed_lines_outside_diff=0,
        comment_deletes=0,
        control_flow_edits=0,
    )
    return Classification(
        rule=rule,
        mode=mode,
        metrics=metrics,
        cost=CandidateCost(
            files_touched=len(files),
            changed_lines_total=metrics.changed_lines_total,
            changed_lines_outside_diff=0,
            risk=0,
        ),
        reason="property generated" if mode == "skip" else None,
        patch_id=":".join((rule, *files)) if files else rule,
    )


@given(
    mode=_MODES,
    apply=st.booleans(),
    rule=_RULES,
    returncode=st.integers(min_value=-5, max_value=12),
)
def test_fix_rule_status_prioritizes_failure_then_mode(
    mode: str,
    apply: bool,
    rule: str,
    returncode: int,
) -> None:
    classification = _classification(rule, cast("Mode", mode), ())
    args = fix_rule._FixRuleArgs(rule, apply, "origin/main", "unblock", ("interlocks", "ci"))

    status = fix_rule._fix_rule_status(classification, args, returncode)

    if returncode:
        assert status == "apply-failed"
    elif mode in {"escrow", "advisory", "skip"}:
        assert status == mode
    elif apply:
        assert status == "applied"
    else:
        assert status == "auto-eligible"


@given(apply=st.booleans(), returncode=st.integers().filter(bool))
def test_fix_rule_status_failure_precedes_auto_apply_state(
    apply: bool,
    returncode: int,
) -> None:
    classification = _classification("I001", "auto", ())
    args = fix_rule._FixRuleArgs("I001", apply, "origin/main", "unblock", ("interlocks", "ci"))

    assert fix_rule._fix_rule_status(classification, args, returncode) == "apply-failed"


@given(apply=st.booleans())
def test_fix_rule_status_reports_auto_success_from_apply_flag(apply: bool) -> None:
    classification = _classification("I001", "auto", ())
    args = fix_rule._FixRuleArgs("I001", apply, "origin/main", "unblock", ("interlocks", "ci"))

    assert fix_rule._fix_rule_status(classification, args, 0) == (
        "applied" if apply else "auto-eligible"
    )


@given(
    mode=_MODES,
    rule=_RULES,
    returncode=st.integers(min_value=-5, max_value=12),
)
def test_fix_rule_artifact_paths_only_describe_written_artifacts(
    mode: str,
    rule: str,
    returncode: int,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        payload: dict[str, object] = {"command": "fix rule"}

        fix_rule._add_fix_rule_artifact_paths(
            payload,
            _FakeCfg(root),  # type: ignore[arg-type]
            _classification(rule, cast("Mode", mode), ()),
            returncode,
        )

        if mode in {"escrow", "advisory"}:
            assert payload["patch_path"] == f".lintfix/escrow/{rule}.patch"
        else:
            assert "patch_path" not in payload
        if returncode:
            assert payload["failed_patch"] == ".lintfix/failed.patch"
        else:
            assert "failed_patch" not in payload


@given(
    payload=st.dictionaries(st.text(min_size=1, max_size=12), st.integers(), max_size=6),
    mode=_MODES,
    rule=_RULES,
    returncode=st.integers(min_value=-5, max_value=12),
)
def test_fix_rule_artifact_paths_preserve_existing_payload_fields(
    payload: dict[str, int],
    mode: str,
    rule: str,
    returncode: int,
) -> None:
    original = dict(payload)
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)

        fix_rule._add_fix_rule_artifact_paths(
            payload,  # type: ignore[arg-type]
            _FakeCfg(root),  # type: ignore[arg-type]
            _classification(rule, cast("Mode", mode), ()),
            returncode,
        )

    for key, value in original.items():
        assert payload[key] == value
    assert set(payload) <= {*original, "patch_path", "failed_patch"}


@given(
    mode=_MODES,
    apply=st.booleans(),
    rule=_RULES,
    metric_files=_FILES,
    changed_files=_FILES,
    patch_text=_PATCH_TEXT,
    verify_applied=st.booleans(),
    verify_rc=st.integers(min_value=0, max_value=12),
)
def test_fix_rule_dispatch_obeys_mode_invariants(
    mode: str,
    apply: bool,
    rule: str,
    metric_files: tuple[str, ...],
    changed_files: tuple[str, ...],
    patch_text: str,
    verify_applied: bool,
    verify_rc: int,
) -> None:
    calls: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    verify_cmd = ("interlocks", "ci")

    def fake_apply_with_verify(
        *, rule: str, files: tuple[str, ...], verify_cmd: tuple[str, ...]
    ) -> VerifyResult:
        calls.append((rule, files, verify_cmd))
        return VerifyResult(
            applied=verify_applied,
            returncode=verify_rc,
            stdout="",
            stderr="",
            restored=not verify_applied,
        )

    with (
        TemporaryDirectory() as raw_root,
        patch.object(fix_rule.ui, "row", lambda *_args, **_kwargs: None),
        patch.object(fix_rule.verify, "apply_with_verify", fake_apply_with_verify),
    ):
        root = Path(raw_root)
        rc = fix_rule._dispatch_classification(
            _classification(rule, cast("Mode", mode), metric_files),
            fix_rule._FixRuleArgs(rule, apply, "origin/main", "unblock", verify_cmd),
            CandidatePatch(rule, changed_files, patch_text, 0),
            changed_files,
            _FakeCfg(root),  # type: ignore[arg-type]
        )

        lintfix_dir = root / ".lintfix"
        failed_patch = lintfix_dir / "failed.patch"

        if mode == "skip":
            assert rc == 0
            assert calls == []
            assert not lintfix_dir.exists()
        elif mode in {"escrow", "advisory"}:
            assert rc == 0
            assert calls == []
            assert (lintfix_dir / "escrow" / f"{rule}.patch").read_text(
                encoding="utf-8"
            ) == patch_text
        elif not apply:
            assert rc == 0
            assert calls == []
            assert not lintfix_dir.exists()
        else:
            expected_files = metric_files or changed_files
            assert calls == [(rule, expected_files, verify_cmd)]
            if verify_applied:
                assert rc == 0
                assert not failed_patch.exists()
            else:
                assert rc == (verify_rc or 1)
                assert failed_patch.read_text(encoding="utf-8") == patch_text
