"""Property tests for project autodetection helpers."""

from __future__ import annotations

import string
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from interlocks.config import InterlockConfig
from interlocks.detect import (
    _PYTEST_WORD,
    _deps_mention,
    _has_pytest_config,
    _iter_declared_dep_names,
    _iter_declared_deps,
    _normalize_dependency_name,
    dependency_declared,
    detect_acceptance_runner,
    detect_features_dir,
    detect_src_dir,
    detect_test_dir,
    detect_test_runner,
)

_DEP = st.text(min_size=1, max_size=40)
_DEP_NAME = st.text(
    alphabet=string.ascii_letters + string.digits + "-_.",
    min_size=1,
    max_size=30,
)
_MALFORMED_CONTAINER = st.one_of(
    st.none(),
    st.text(max_size=20),
    st.integers(),
    st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=3),
)


def _write_pyproject(root: Path, dependencies: list[str] | None = None) -> None:
    deps = "" if dependencies is None else f"dependencies = {dependencies!r}\n"
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'probe'\nversion = '0.0.0'\n" + deps,
        encoding="utf-8",
    )


def _cfg(
    root: Path,
    *,
    features_dir: Path | None,
    acceptance_runner: str | None = None,
) -> InterlockConfig:
    return InterlockConfig(
        project_root=root,
        src_dir=root / "src",
        test_dir=root / "tests",
        test_runner="pytest",
        test_invoker="python",
        features_dir=features_dir,
        acceptance_runner=acceptance_runner,  # type: ignore[arg-type]
    )


@given(tool=st.one_of(_MALFORMED_CONTAINER, st.just({"pytest": {}})))
def test_pytest_config_detection_requires_tool_table(tool: object) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        test_dir = root / "tests"

        detected = _has_pytest_config(root, {"tool": tool}, test_dir)

        assert detected is (isinstance(tool, dict) and "pytest" in tool)


@given(
    has_tests=st.booleans(),
    has_test=st.booleans(),
    has_src_tests=st.booleans(),
)
def test_detect_test_dir_preserves_preference_order(
    has_tests: bool,
    has_test: bool,
    has_src_tests: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        if has_tests:
            (root / "tests").mkdir()
        if has_test:
            (root / "test").mkdir()
        if has_src_tests:
            (root / "src" / "tests").mkdir(parents=True)

        expected = (
            root / "tests"
            if has_tests
            else root / "test"
            if has_test
            else root / "src" / "tests"
            if has_src_tests
            else root / "tests"
        )
        assert detect_test_dir(root) == expected


@given(
    has_tests_features=st.booleans(),
    has_top_features=st.booleans(),
    has_custom_features=st.booleans(),
)
def test_detect_features_dir_preserves_preference_order(
    has_tests_features: bool,
    has_top_features: bool,
    has_custom_features: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        custom_tests = root / "custom_tests"
        if has_tests_features:
            (root / "tests" / "features").mkdir(parents=True)
        if has_top_features:
            (root / "features").mkdir()
        if has_custom_features:
            (custom_tests / "features").mkdir(parents=True)

        expected = (
            (root / "tests" / "features").resolve()
            if has_tests_features
            else (root / "features").resolve()
            if has_top_features
            else (custom_tests / "features").resolve()
            if has_custom_features
            else None
        )
        assert detect_features_dir(root, custom_tests) == expected


@given(
    has_uv_declared=st.booleans(),
    has_hatch_declared=st.booleans(),
    has_setuptools_declared=st.booleans(),
    has_src_package=st.booleans(),
    has_top_package=st.booleans(),
    has_properties_test_dir=st.booleans(),
    has_project_name_package=st.booleans(),
)
def test_detect_src_dir_preserves_declared_and_layout_preference_order(
    has_uv_declared: bool,
    has_hatch_declared: bool,
    has_setuptools_declared: bool,
    has_src_package: bool,
    has_top_package: bool,
    has_properties_test_dir: bool,
    has_project_name_package: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        pyproject: dict[str, object] = {"project": {"name": "project-name"}, "tool": {}}
        tool = pyproject["tool"]
        assert isinstance(tool, dict)
        if has_uv_declared:
            tool["uv"] = {"build-backend": {"module-name": "uvpkg"}}
            (root / "uvpkg").mkdir()
        if has_hatch_declared:
            tool["hatch"] = {"build": {"targets": {"wheel": {"packages": ["hatchpkg"]}}}}
            (root / "hatchpkg").mkdir()
        if has_setuptools_declared:
            tool["setuptools"] = {"packages": ["setuptools.pkg"]}
            (root / "setuptools" / "pkg").mkdir(parents=True)
        if has_src_package:
            (root / "src" / "srcpkg").mkdir(parents=True)
            (root / "src" / "srcpkg" / "__init__.py").write_text("", encoding="utf-8")
        if has_top_package:
            (root / "toppkg").mkdir()
            (root / "toppkg" / "__init__.py").write_text("", encoding="utf-8")
        if has_properties_test_dir:
            (root / "properties").mkdir()
            (root / "properties" / "__init__.py").write_text("", encoding="utf-8")
            (root / "properties" / "test_example_properties.py").write_text(
                "def test_example() -> None:\n    pass\n", encoding="utf-8"
            )
        if has_project_name_package:
            (root / "project_name").mkdir()

        detected = detect_src_dir(root, pyproject)

        expected = (
            root / "uvpkg"
            if has_uv_declared
            else root / "hatchpkg"
            if has_hatch_declared
            else root / "setuptools" / "pkg"
            if has_setuptools_declared
            else root / "src" / "srcpkg"
            if has_src_package
            else root / "toppkg"
            if has_top_package
            else root / "project_name"
            if has_project_name_package
            else root
        ).resolve()
        assert detected == expected


@given(st.sampled_from(["off", "behave", "pytest-bdd"]))
def test_explicit_acceptance_runner_override_wins(runner: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        _write_pyproject(root)
        cfg = _cfg(root, features_dir=None, acceptance_runner=runner)

        assert detect_acceptance_runner(cfg) == (None if runner == "off" else runner)


@given(has_behave=st.booleans(), has_pytest_bdd=st.booleans())
def test_acceptance_runner_dep_detection_prefers_pytest_bdd_when_both_present(
    has_behave: bool,
    has_pytest_bdd: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        features = root / "features"
        features.mkdir()
        dependencies = [
            dep
            for enabled, dep in (
                (has_behave, "behave>=1.2"),
                (has_pytest_bdd, "pytest-bdd>=8"),
            )
            if enabled
        ]
        _write_pyproject(root, dependencies)

        expected = "behave" if has_behave and not has_pytest_bdd else "pytest-bdd"
        assert detect_acceptance_runner(_cfg(root, features_dir=features)) == expected


@given(has_steps=st.booleans(), has_environment=st.booleans())
def test_acceptance_runner_behave_layout_requires_steps_and_environment(
    has_steps: bool,
    has_environment: bool,
) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        features = root / "features"
        features.mkdir()
        if has_steps:
            (features / "steps").mkdir()
        if has_environment:
            (features / "environment.py").write_text("", encoding="utf-8")
        _write_pyproject(root)

        expected = "behave" if has_steps and has_environment else "pytest-bdd"
        assert detect_acceptance_runner(_cfg(root, features_dir=features)) == expected


@given(
    project_deps=st.one_of(st.lists(_DEP, max_size=5), _MALFORMED_CONTAINER),
    groups=st.one_of(
        st.dictionaries(
            st.text(max_size=10),
            st.one_of(st.lists(_DEP, max_size=5), _MALFORMED_CONTAINER),
            max_size=5,
        ),
        _MALFORMED_CONTAINER,
    ),
    uv_deps=st.one_of(st.lists(_DEP, max_size=5), _MALFORMED_CONTAINER),
    uv_dev_deps=st.one_of(st.lists(_DEP, max_size=5), _MALFORMED_CONTAINER),
)
def test_iter_declared_deps_ignores_malformed_dependency_containers(
    project_deps: object,
    groups: object,
    uv_deps: object,
    uv_dev_deps: object,
) -> None:
    pyproject = {
        "project": {"dependencies": project_deps},
        "dependency-groups": groups,
        "tool": {"uv": {"dependencies": uv_deps, "dev-dependencies": uv_dev_deps}},
    }
    expected: list[str] = []
    if isinstance(project_deps, list):
        expected.extend(project_deps)
    if isinstance(groups, dict):
        for group in groups.values():
            if isinstance(group, list):
                expected.extend(group)
    if isinstance(uv_dev_deps, list):
        expected.extend(uv_dev_deps)
    if isinstance(uv_deps, list):
        expected.extend(uv_deps)

    assert list(_iter_declared_deps(pyproject)) == expected


@given(items=st.lists(st.one_of(_DEP, _MALFORMED_CONTAINER), max_size=12))
def test_iter_declared_deps_yields_only_string_items(items: list[object]) -> None:
    pyproject = {"project": {"dependencies": items}}

    assert list(_iter_declared_deps(pyproject)) == [
        item for item in items if isinstance(item, str)
    ]


@given(deps=st.lists(_DEP, max_size=12))
def test_deps_mention_matches_declared_dependency_words(deps: list[str]) -> None:
    pyproject = {"project": {"dependencies": deps}}

    assert _deps_mention(_PYTEST_WORD, pyproject) is any(
        _PYTEST_WORD.search(dep) is not None for dep in deps
    )


@given(package=st.sampled_from(["hypothesis", "pytest-bdd", "some_pkg", "some.pkg"]))
def test_dependency_declared_matches_normalized_distribution_name(package: str) -> None:
    pyproject = {"dependency-groups": {"dev": [f"{package}[extra]>=1"]}}

    assert dependency_declared(pyproject, package.replace("_", "-").replace(".", "-")) is True
    assert dependency_declared(pyproject, f"{package}-other") is False


@given(name=_DEP_NAME)
def test_normalize_dependency_name_collapses_pep503_separators(name: str) -> None:
    normalized = _normalize_dependency_name(name)

    assert normalized == normalized.lower()
    assert "_" not in normalized
    assert "." not in normalized
    assert _normalize_dependency_name(normalized) == normalized


@given(
    names=st.lists(_DEP_NAME, max_size=8),
    suffix=st.sampled_from(["", ">=1", "[extra]>=1", " ; python_version >= '3.11'"]),
)
def test_iter_declared_dep_names_extracts_distribution_names(
    names: list[str],
    suffix: str,
) -> None:
    pyproject = {"project": {"dependencies": [f"  {name}{suffix}" for name in names]}}

    assert list(_iter_declared_dep_names(pyproject)) == names


@given(tool=st.text(min_size=1, max_size=20))
def test_detect_test_runner_ignores_malformed_tool_table(tool: str) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        test_dir = root / "tests"

        assert detect_test_runner(root, {"tool": tool}, test_dir) == "unittest"
