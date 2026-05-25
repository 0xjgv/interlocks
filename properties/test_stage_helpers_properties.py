"""Property tests for stage helper composition."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

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

    old_typecheck = check_stage.task_typecheck
    old_test = check_stage._test_task
    old_acceptance = check_stage._acceptance_task
    old_properties = check_stage._properties_task
    check_stage.task_typecheck = lambda _files: maybe(0)  # type: ignore[assignment]
    check_stage._test_task = lambda _cfg, _scope, _acceptance, _properties: maybe(1)  # type: ignore[assignment]
    check_stage._acceptance_task = lambda _cfg, _scope: maybe(2)  # type: ignore[assignment]
    check_stage._properties_task = lambda _cfg, _scope: maybe(3)  # type: ignore[assignment]
    try:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            cfg = InterlockConfig(
                project_root=root,
                src_dir=root / "src",
                test_dir=root / "tests",
                test_runner="pytest",
                test_invoker="python",
            )
            resolved = check_stage._parallel_tasks(cfg, scope_ref, scoped_files)
    finally:
        check_stage.task_typecheck = old_typecheck
        check_stage._test_task = old_test
        check_stage._acceptance_task = old_acceptance
        check_stage._properties_task = old_properties

    assert resolved == [task for index, task in enumerate(tasks) if present[index]]


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

    old_ready = check_stage.project_env_ready
    old_classify = check_stage.classify_acceptance_with_details
    old_acceptance = check_stage.task_acceptance_with_attribution
    old_failure = check_stage.acceptance_failure_task
    check_stage.project_env_ready = lambda _cfg: ready  # type: ignore[assignment]
    check_stage.classify_acceptance_with_details = lambda _cfg: classification  # type: ignore[assignment]
    check_stage.task_acceptance_with_attribution = lambda _cfg: runnable  # type: ignore[assignment]
    check_stage.acceptance_failure_task = lambda _classification: failure  # type: ignore[assignment]
    try:
        with TemporaryDirectory() as raw_root:
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
    finally:
        check_stage.project_env_ready = old_ready
        check_stage.classify_acceptance_with_details = old_classify
        check_stage.task_acceptance_with_attribution = old_acceptance
        check_stage.acceptance_failure_task = old_failure

    if not ready or not run_in_check or scope_ref is not None:
        assert task is None
    elif classification.is_required_failure:
        assert task is failure
    elif status is AcceptanceStatus.RUNNABLE:
        assert task is runnable
    else:
        assert task is None
