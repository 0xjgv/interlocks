"""Generated-input checks for init-acceptance JSON helpers."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.config import InterlockConfig
from interlocks.defaults_path import path as defaults_path
from interlocks.scaffold import scaffold_status
from interlocks.tasks.init_acceptance import (
    _INIT_ACCEPTANCE_NEXT_ACTIONS,
    _INIT_ACCEPTANCE_OUTPUTS,
    _init_acceptance_domain_payload,
    _init_acceptance_success_payload,
    _is_scaffold_feature,
)


def _cfg(root: Path) -> InterlockConfig:
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'probe'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    return InterlockConfig(
        project_root=root,
        src_dir=root / "src",
        test_dir=root / "tests",
        test_runner="pytest",
        test_invoker="python",
    )


def test_init_acceptance_success_payload_shape_is_stable() -> None:
    files = [{"path": path, "action": "created"} for path in _INIT_ACCEPTANCE_OUTPUTS]

    with TemporaryDirectory() as raw_root:
        payload = _init_acceptance_success_payload(_cfg(Path(raw_root)), files)

    assert payload["command"] == "init-acceptance"
    assert payload["passed"] is True
    assert payload["status"] == "created"
    assert payload["created"] == list(_INIT_ACCEPTANCE_OUTPUTS)
    assert payload["files"] == files
    assert payload["next_actions"] == list(_INIT_ACCEPTANCE_NEXT_ACTIONS)


@given(
    paths=st.lists(st.text(min_size=1, max_size=80), min_size=1, max_size=8, unique=True),
    actions=st.lists(st.sampled_from(("created", "kept")), min_size=1, max_size=8),
)
def test_init_acceptance_success_payload_reports_created_subset(
    paths: list[str],
    actions: list[str],
) -> None:
    files = [
        {"path": path, "action": actions[index % len(actions)]} for index, path in enumerate(paths)
    ]

    with TemporaryDirectory() as raw_root:
        payload = _init_acceptance_success_payload(_cfg(Path(raw_root)), files)

    assert payload["command"] == "init-acceptance"
    assert payload["passed"] is True
    assert payload["status"] == scaffold_status(files)
    assert payload["files"] == files
    assert payload["created"] == [file["path"] for file in files if file["action"] == "created"]
    next_actions = payload["next_actions"]
    assert isinstance(next_actions, list)
    assert next_actions


@given(actions=st.lists(st.sampled_from(("created", "kept")), max_size=8))
def test_init_acceptance_status_distinguishes_all_created(actions: list[str]) -> None:
    files = [
        {"path": f"tests/{index}.py", "action": action} for index, action in enumerate(actions)
    ]

    status = scaffold_status(files)

    assert status == ("created" if files and set(actions) == {"created"} else "scaffold-present")


@given(
    paths=st.lists(
        st.from_regex(r"[A-Za-z0-9_-]+\.feature", fullmatch=True),
        max_size=8,
        unique=True,
    )
)
def test_init_acceptance_domain_payload_reports_domain_files(paths: list[str]) -> None:
    cfg = InterlockConfig(
        project_root=Path(),
        src_dir=Path("src"),
        test_dir=Path("tests"),
        test_runner="pytest",
        test_invoker="python",
    )
    domain_files = [Path("tests/features") / path for path in paths]

    payload = _init_acceptance_domain_payload(cfg, domain_files)

    assert payload["command"] == "init-acceptance"
    assert payload["passed"] is True
    assert payload["status"] == "domain-acceptance-present"
    assert payload["created"] == []
    assert payload["files"] == []
    assert payload["domain_acceptance_feature_count"] == len(domain_files)
    assert payload["domain_acceptance_features"] == [str(path) for path in domain_files]
    assert payload["next_actions"] == ["Run `interlocks acceptance`."]


@given(
    paths=st.lists(
        st.from_regex(r"[A-Za-z0-9_-]+\.feature", fullmatch=True),
        max_size=8,
        unique=True,
    )
)
def test_init_acceptance_domain_payload_reports_project_relative_feature_paths(
    paths: list[str],
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        cfg = InterlockConfig(
            project_root=root,
            src_dir=root / "src",
            test_dir=root / "tests",
            test_runner="pytest",
            test_invoker="python",
        )
        domain_files = [root / "tests" / "features" / path for path in paths]

        payload = _init_acceptance_domain_payload(cfg, domain_files)

    assert payload["domain_acceptance_features"] == [f"tests/features/{path}" for path in paths]
    assert all(not Path(path).is_absolute() for path in payload["domain_acceptance_features"])


@given(scaffold_content=st.booleans())
def test_is_scaffold_feature_matches_only_unchanged_example(scaffold_content: bool) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        feature = root / "example.feature"
        if scaffold_content:
            feature.write_bytes(defaults_path("bdd_example.feature").read_bytes())
        else:
            feature.write_text("Feature: Domain\n  Scenario: custom\n", encoding="utf-8")

        assert _is_scaffold_feature(feature) is scaffold_content
        assert _is_scaffold_feature(root / "billing.feature") is False
