"""Property tests for stage helper composition."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from interlocks.acceptance_status import AcceptanceClassification, AcceptanceStatus
from interlocks.config import InterlockConfig
from interlocks.runner import Task
from interlocks.stages import check as check_stage
from interlocks.stages.ci import _should_run_mutation


@given(mode=st.sampled_from(["off", "incremental", "full"]), run_in_ci=st.booleans())
def test_should_run_mutation_preserves_legacy_flag_for_off_mode(
    mode: str,
    run_in_ci: bool,
) -> None:
    assert _should_run_mutation(mode, run_in_ci=run_in_ci) is (mode != "off" or run_in_ci)


@given(mode=st.sampled_from(["incremental", "full"]), run_in_ci=st.booleans())
def test_should_run_mutation_always_runs_explicit_ci_modes(
    mode: str,
    run_in_ci: bool,
) -> None:
    assert _should_run_mutation(mode, run_in_ci=run_in_ci) is True


@given(
    present=st.lists(st.booleans(), min_size=4, max_size=4),
    scope_ref=st.one_of(st.none(), st.text(max_size=20)),
    scoped_files=st.one_of(st.none(), st.lists(st.text(max_size=20), max_size=5)),
)
def test_parallel_tasks_keeps_non_none_optional_tasks_in_order(
    present: list[bool],
    scope_ref: str | None,
    scoped_files: list[str] | None,
) -> None:
    tasks = [Task(f"task-{index}", [f"cmd-{index}"]) for index in range(4)]

    def maybe(index: int) -> Task | None:
        return tasks[index] if present[index] else None

    with (
        patch.object(check_stage, "task_typecheck", lambda _files: maybe(0)),
        patch.object(
            check_stage,
            "_test_task",
            lambda _cfg, _scope, _acceptance, _properties: maybe(1),
        ),
        patch.object(check_stage, "_acceptance_task", lambda _cfg, _scope: maybe(2)),
        patch.object(check_stage, "_properties_task", lambda _cfg, _scope: maybe(3)),
        TemporaryDirectory() as raw_root,
    ):
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )
        resolved = check_stage._parallel_tasks(cfg, scope_ref, scoped_files)

    assert resolved == [task for index, task in enumerate(tasks) if present[index]]


@given(
    scope_ref=st.one_of(st.none(), st.text(max_size=20)),
    scoped_files=st.one_of(st.none(), st.lists(st.text(max_size=20), max_size=5)),
    has_acceptance=st.booleans(),
    has_properties=st.booleans(),
)
def test_parallel_tasks_threads_scope_and_dependent_tasks(
    scope_ref: str | None,
    scoped_files: list[str] | None,
    has_acceptance: bool,
    has_properties: bool,
) -> None:
    typecheck = Task("typecheck", ["typecheck"])
    test = Task("test", ["test"])
    acceptance = Task("acceptance", ["acceptance"]) if has_acceptance else None
    properties = Task("properties", ["properties"]) if has_properties else None
    seen: dict[str, object] = {}

    def fake_typecheck(files: list[str] | None) -> Task:
        seen["typecheck_files"] = files
        return typecheck

    def fake_acceptance(_cfg: InterlockConfig, scope: str | None) -> Task | None:
        seen["acceptance_scope"] = scope
        return acceptance

    def fake_properties(_cfg: InterlockConfig, scope: str | None) -> Task | None:
        seen["properties_scope"] = scope
        return properties

    def fake_test(
        _cfg: InterlockConfig,
        scope: str | None,
        acceptance_task: Task | None,
        properties_task: Task | None,
    ) -> Task:
        seen["test_scope"] = scope
        seen["test_acceptance"] = acceptance_task
        seen["test_properties"] = properties_task
        return test

    with (
        patch.object(check_stage, "task_typecheck", fake_typecheck),
        patch.object(check_stage, "_acceptance_task", fake_acceptance),
        patch.object(check_stage, "_properties_task", fake_properties),
        patch.object(check_stage, "_test_task", fake_test),
        TemporaryDirectory() as raw_root,
    ):
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )
        resolved = check_stage._parallel_tasks(cfg, scope_ref, scoped_files)

    assert seen == {
        "typecheck_files": scoped_files,
        "acceptance_scope": scope_ref,
        "properties_scope": scope_ref,
        "test_scope": scope_ref,
        "test_acceptance": acceptance,
        "test_properties": properties,
    }
    assert resolved == [typecheck, test, *(task for task in (acceptance, properties) if task)]


@given(
    features_exists=st.booleans(),
    step_defs_exists=st.booleans(),
    runner=st.sampled_from(("pytest", "unittest")),
    acceptance_description=st.sampled_from(("Acceptance (pytest-bdd)", "Acceptance (required)")),
)
def test_acceptance_ignore_args_only_targets_pytest_bdd_paths_under_test_dir(
    features_exists: bool,
    step_defs_exists: bool,
    runner: str,
    acceptance_description: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        test_dir = root / "tests"
        features = test_dir / "features"
        step_defs = test_dir / "step_defs"
        test_dir.mkdir()
        if features_exists:
            features.mkdir()
        if step_defs_exists:
            step_defs.mkdir()
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=test_dir,
            test_runner=runner,
            test_invoker="python",
            features_dir=features,
        )
        acceptance = Task(acceptance_description, ["pytest"])

        ignores = check_stage._acceptance_ignore_args(cfg, acceptance)

    if runner != "pytest" or acceptance_description != "Acceptance (pytest-bdd)":
        assert ignores == ()
    else:
        expected = []
        if features_exists:
            expected.append("--ignore=tests/features")
        if step_defs_exists:
            expected.append("--ignore=tests/step_defs")
        assert ignores == tuple(expected)


@given(
    configured=st.booleans(),
    under_test_dir=st.booleans(),
    features_exists=st.booleans(),
    runner=st.sampled_from(("pytest", "unittest")),
    acceptance_description=st.sampled_from(("Acceptance (pytest-bdd)", "Acceptance (required)")),
)
def test_acceptance_ignore_args_only_ignores_configured_collected_feature_dir(
    configured: bool,
    under_test_dir: bool,
    features_exists: bool,
    runner: str,
    acceptance_description: str,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        test_dir = root / "tests"
        features = test_dir / "features" if under_test_dir else root / "features"
        test_dir.mkdir()
        if features_exists:
            features.mkdir(parents=True)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=test_dir,
            test_runner=runner,
            test_invoker="python",
            features_dir=features if configured else None,
        )
        acceptance = Task(acceptance_description, ["pytest"])

        ignores = check_stage._acceptance_ignore_args(cfg, acceptance)

    should_ignore = (
        configured
        and under_test_dir
        and features_exists
        and runner == "pytest"
        and acceptance_description == "Acceptance (pytest-bdd)"
    )
    assert ignores == (("--ignore=tests/features",) if should_ignore else ())


@given(
    properties_exists=st.booleans(),
    under_test_dir=st.booleans(),
    runner=st.sampled_from(("pytest", "unittest")),
    has_properties_task=st.booleans(),
    configured=st.booleans(),
)
def test_properties_ignore_args_only_targets_collected_property_dir(
    properties_exists: bool,
    under_test_dir: bool,
    runner: str,
    has_properties_task: bool,
    configured: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        test_dir = root / "tests"
        test_dir.mkdir()
        properties_dir = test_dir / "properties" if under_test_dir else root / "properties"
        if properties_exists:
            properties_dir.mkdir(parents=True)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=test_dir,
            test_runner=runner,
            test_invoker="python",
            properties_dir=properties_dir if configured else None,
        )
        properties = Task("Property tests", ["pytest"]) if has_properties_task else None

        ignores = check_stage._properties_ignore_args(cfg, properties)

    should_ignore = (
        configured
        and has_properties_task
        and runner == "pytest"
        and properties_exists
        and under_test_dir
    )
    assert ignores == (("--ignore=tests/properties",) if should_ignore else ())


@given(
    ready=st.booleans(),
    scope_ref=st.one_of(st.none(), st.text(max_size=20)),
    runner=st.sampled_from(("pytest", "unittest")),
    features_exists=st.booleans(),
    step_defs_exists=st.booleans(),
    properties_exists=st.booleans(),
    acceptance_description=st.sampled_from(("Acceptance (pytest-bdd)", "Acceptance (required)")),
    has_acceptance=st.booleans(),
    has_properties=st.booleans(),
    has_test_task=st.booleans(),
)
def test_test_task_matches_readiness_scope_and_ignore_args(
    ready: bool,
    scope_ref: str | None,
    runner: str,
    features_exists: bool,
    step_defs_exists: bool,
    properties_exists: bool,
    acceptance_description: str,
    has_acceptance: bool,
    has_properties: bool,
    has_test_task: bool,
) -> None:
    test_task = Task("Run tests", ["pytest"], label="test")
    seen_args: list[tuple[str, ...]] = []
    skipped: list[str] = []

    def fake_task_test(*, extra_pytest_args: tuple[str, ...] = ()) -> Task | None:
        seen_args.append(extra_pytest_args)
        return test_task if has_test_task else None

    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        test_dir = root / "tests"
        features = test_dir / "features"
        step_defs = test_dir / "step_defs"
        properties_dir = test_dir / "properties"
        test_dir.mkdir()
        if features_exists:
            features.mkdir()
        if step_defs_exists:
            step_defs.mkdir()
        if properties_exists:
            properties_dir.mkdir()

        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=test_dir,
            test_runner=runner,
            test_invoker="python",
            features_dir=features,
            properties_dir=properties_dir,
        )
        acceptance = (
            Task(acceptance_description, ["pytest"], label="acceptance")
            if has_acceptance
            else None
        )
        properties = (
            Task("Property tests", ["pytest"], label="properties") if has_properties else None
        )

        with (
            patch.object(check_stage, "project_env_ready", lambda _cfg: ready),
            patch.object(check_stage, "task_test", fake_task_test),
            patch.object(check_stage, "warn_skip", skipped.append),
            patch.object(
                check_stage,
                "record_skip",
                lambda label, _reason, **_kwargs: skipped.append(label),
            ),
        ):
            resolved = check_stage._test_task(cfg, scope_ref, acceptance, properties)

    if scope_ref is not None:
        assert resolved is None
        assert seen_args == []
        assert "test" in skipped
        return
    if not ready:
        assert resolved is None
        assert seen_args == []
        assert skipped == []
        return

    expected_args: list[str] = []
    if (
        runner == "pytest"
        and has_acceptance
        and acceptance_description == "Acceptance (pytest-bdd)"
    ):
        if features_exists:
            expected_args.append("--ignore=tests/features")
        if step_defs_exists:
            expected_args.append("--ignore=tests/step_defs")
    if runner == "pytest" and has_properties and properties_exists:
        expected_args.append("--ignore=tests/properties")

    assert seen_args == [tuple(expected_args)]
    expected_task = test_task if has_test_task else None
    assert resolved is expected_task
    assert ("test" in skipped) is (not has_test_task)


@given(
    ready=st.booleans(),
    run_in_check=st.booleans(),
    scope_ref=st.one_of(st.none(), st.text(max_size=20)),
    status=st.sampled_from(tuple(AcceptanceStatus)),
)
def test_acceptance_task_matches_readiness_scope_and_classification(
    ready: bool,
    run_in_check: bool,
    scope_ref: str | None,
    status: AcceptanceStatus,
) -> None:
    runnable = Task("acceptance-runnable", ["pytest"])
    failure = Task("acceptance-failure", ["fail"])
    classification = AcceptanceClassification(status, None)

    with (
        patch.object(check_stage, "project_env_ready", lambda _cfg: ready),
        patch.object(
            check_stage,
            "classify_acceptance_with_details",
            lambda _cfg: classification,
        ),
        patch.object(check_stage, "task_acceptance_with_attribution", lambda _cfg: runnable),
        patch.object(check_stage, "acceptance_failure_task", lambda _classification: failure),
        TemporaryDirectory() as raw_root,
    ):
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
            run_acceptance_in_check=run_in_check,
        )

        task = check_stage._acceptance_task(cfg, scope_ref)

    if not ready or not run_in_check or scope_ref is not None:
        assert task is None
    elif classification.is_required_failure:
        assert task is failure
    elif status is AcceptanceStatus.RUNNABLE:
        assert task is runnable
    else:
        assert task is None
