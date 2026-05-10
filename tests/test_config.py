"""Tests for interlocks.config — project-root discovery, overrides, command builders."""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest

from interlocks.config import (
    InterlockConfig,
    build_coverage_test_command,
    build_test_command,
    find_project_root,
    invoker_prefix,
    load_config,
)
from interlocks.defaults.tools import default_pin


def _write(path: Path, text: str) -> None:
    path.write_text(textwrap.dedent(text), encoding="utf-8")


def _setup_pyproject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> Path:
    """Create ``tmp_path/tests`` + ``pyproject.toml`` with ``body`` and chdir."""
    (tmp_path / "tests").mkdir()
    _write(tmp_path / "pyproject.toml", body)
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ─────────────── find_project_root ──────────────────────────────────


def test_find_project_root_walks_upward(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == tmp_path.resolve()


def test_find_project_root_falls_back_to_start_when_missing(tmp_path: Path) -> None:
    nested = tmp_path / "x"
    nested.mkdir()
    assert find_project_root(nested) == nested.resolve()


# ─────────────── load_config defaults (autodetect) ──────────────────


@pytest.fixture
def tmp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "tests").mkdir()
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    _write(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "mypkg"
        version = "0.0.0"
        dependencies = ["pytest>=9"]
        """,
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_load_config_autodetects(tmp_project: Path) -> None:
    cfg = load_config()
    assert cfg.project_root == tmp_project.resolve()
    assert cfg.src_dir == (tmp_project / "mypkg").resolve()
    assert cfg.test_dir == (tmp_project / "tests").resolve()
    assert cfg.test_runner == "pytest"
    assert cfg.test_invoker == "python"
    assert cfg.pytest_args == ()


def test_load_config_uv_lock_flips_invoker(tmp_project: Path) -> None:
    (tmp_project / "uv.lock").write_text("", encoding="utf-8")
    assert load_config().test_invoker == "uv"


# ─────────────── threshold defaults + overrides ─────────────────────


def test_threshold_defaults_when_absent(tmp_project: Path) -> None:
    cfg = load_config()
    assert cfg.skip == frozenset()
    assert cfg.coverage_min == 80
    assert cfg.crap_max == 30.0
    assert cfg.complexity_max_ccn == 15
    assert cfg.complexity_max_loc == 100
    assert cfg.complexity_max_args == 7
    assert cfg.mutation_min_coverage == 70.0
    assert cfg.mutation_max_runtime == 600
    assert cfg.mutation_min_score == 80.0
    assert cfg.enforce_crap is True
    assert cfg.enforce_behavior_attribution is False
    assert cfg.run_mutation_in_ci is False
    assert cfg.enforce_mutation is False


def test_threshold_overrides_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "thresh"
        version = "0.0.0"

        [tool.interlocks]
        coverage_min = 90
        crap_max = 25.5
        complexity_max_ccn = 12
        complexity_max_loc = 80
        complexity_max_args = 5
        mutation_min_coverage = 85.0
        mutation_max_runtime = 300
        mutation_min_score = 92.5
        enforce_crap = false
        enforce_behavior_attribution = true
        run_mutation_in_ci = true
        enforce_mutation = true
        """,
    )
    cfg = load_config()
    assert cfg.coverage_min == 90
    assert cfg.crap_max == 25.5
    assert cfg.complexity_max_ccn == 12
    assert cfg.complexity_max_loc == 80
    assert cfg.complexity_max_args == 5
    assert cfg.mutation_min_coverage == 85.0
    assert cfg.mutation_max_runtime == 300
    assert cfg.mutation_min_score == 92.5
    assert cfg.enforce_crap is False
    assert cfg.enforce_behavior_attribution is True
    assert cfg.run_mutation_in_ci is True
    assert cfg.enforce_mutation is True


def test_tool_version_returns_bundled_default_when_unset(tmp_project: Path) -> None:
    from interlocks.defaults.tools import DEFAULTS

    cfg = load_config()
    assert cfg.tool_version("ruff") == DEFAULTS["ruff"]
    assert cfg.tool_version("basedpyright") == DEFAULTS["basedpyright"]


def test_tool_version_project_override_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "thresh"
        version = "0.0.0"

        [tool.interlocks.tools]
        ruff = "0.14.0"
        basedpyright = "1.40.0"
        """,
    )
    cfg = load_config()
    assert cfg.tool_version("ruff") == "0.14.0"
    assert cfg.tool_version("basedpyright") == "1.40.0"
    # Unconfigured tool falls back to bundled default.
    from interlocks.defaults.tools import DEFAULTS

    assert cfg.tool_version("deptry") == DEFAULTS["deptry"]


def test_tool_version_unknown_raises(tmp_project: Path) -> None:
    cfg = load_config()
    with pytest.raises(KeyError):
        cfg.tool_version("not-a-real-tool")


def test_tool_version_ignores_non_string_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Permissive parser: bad TOML values fall through to bundled default."""
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "thresh"
        version = "0.0.0"

        [tool.interlocks.tools]
        ruff = 12345
        """,
    )
    from interlocks.defaults.tools import DEFAULTS

    assert load_config().tool_version("ruff") == DEFAULTS["ruff"]


def test_skip_project_policy_resolves_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "skip-policy"
        version = "0.0.0"

        [tool.interlocks]
        skip = ["lint", "typecheck", "lint"]
        """,
    )

    cfg = load_config()

    assert cfg.skip == frozenset({"lint", "typecheck"})
    assert cfg.value_sources["skip"] == "project-configured"


def test_skip_project_policy_rejects_unknown_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "skip-bad"
        version = "0.0.0"

        [tool.interlocks]
        skip = ["nope"]
        """,
    )

    from interlocks.config import InterlockConfigError

    with pytest.raises(InterlockConfigError, match=r"unknown .*skip label"):
        load_config()


def test_invalid_threshold_types_fall_back_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "badthresh"
        version = "0.0.0"

        [tool.interlocks]
        coverage_min = "eighty"
        crap_max = true
        """,
    )
    cfg = load_config()
    assert cfg.coverage_min == 80
    assert cfg.crap_max == 30.0


# ─────────────── require_acceptance flag ────────────────────────────


def test_behavior_attribution_enforcement_auto_on_for_interlocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "interlocks"
        version = "0.0.0"
        """,
    )

    cfg = load_config()

    assert cfg.enforce_behavior_attribution is True
    assert cfg.value_sources["enforce_behavior_attribution"] == "auto-detected"


def test_behavior_attribution_enforcement_default_false_downstream(
    tmp_project: Path,
) -> None:
    assert load_config().enforce_behavior_attribution is False


def test_behavior_attribution_enforcement_project_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "interlocks"
        version = "0.0.0"

        [tool.interlocks]
        enforce_behavior_attribution = false
        """,
    )

    cfg = load_config()

    assert cfg.enforce_behavior_attribution is False
    assert cfg.value_sources["enforce_behavior_attribution"] == "project-configured"


def test_require_acceptance_default_false(tmp_project: Path) -> None:
    cfg = load_config()
    assert cfg.require_acceptance is False


def test_require_acceptance_explicit_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "req-acc"
        version = "0.0.0"

        [tool.interlocks]
        require_acceptance = true
        """,
    )
    cfg = load_config()
    assert cfg.require_acceptance is True


def test_require_acceptance_invalid_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "req-acc-bad"
        version = "0.0.0"

        [tool.interlocks]
        require_acceptance = "yes"
        """,
    )
    cfg = load_config()
    assert cfg.require_acceptance is False


# ─────────────── presets ───────────────────────────────────────────


def test_baseline_preset_resolves_low_friction_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "baseline"
        version = "0.0.0"

        [tool.interlocks]
        preset = "baseline"
        """,
    )

    cfg = load_config()

    assert cfg.preset == "baseline"
    assert cfg.coverage_min == 70
    assert cfg.crap_max == 40.0
    assert cfg.enforce_crap is False
    assert cfg.run_mutation_in_ci is False
    assert cfg.enforce_mutation is False
    assert cfg.run_acceptance_in_check is False
    assert cfg.value_sources["coverage_min"] == "preset-derived"
    assert cfg.value_sources["preset"] == "project-configured"


def test_strict_preset_resolves_blocking_gate_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "strict"
        version = "0.0.0"

        [tool.interlocks]
        preset = "strict"
        """,
    )

    cfg = load_config()

    assert cfg.preset == "strict"
    assert cfg.coverage_min == 90
    assert cfg.crap_max == 20.0
    assert cfg.enforce_crap is True
    assert cfg.run_mutation_in_ci is True
    assert cfg.enforce_mutation is True
    assert cfg.mutation_ci_mode == "incremental"
    assert cfg.run_acceptance_in_check is True
    assert cfg.require_acceptance is True


def test_strict_preset_uses_incremental_mutation_ci_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Strict bounds PR latency by mutating only changed files; nightly stays full."""
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "strict-incremental"
        version = "0.0.0"

        [tool.interlocks]
        preset = "strict"
        """,
    )

    cfg = load_config()

    assert cfg.mutation_ci_mode == "incremental"
    assert cfg.value_sources["mutation_ci_mode"] == "preset-derived"


def test_strict_preset_enforces_behavior_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Strict promotes behavior-attribution from advisory to blocking."""
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "strict-attribution"
        version = "0.0.0"

        [tool.interlocks]
        preset = "strict"
        """,
    )

    cfg = load_config()

    assert cfg.enforce_behavior_attribution is True
    assert cfg.value_sources["enforce_behavior_attribution"] == "preset-derived"


def test_progressive_preset_resolves_enforcement_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "progressive"
        version = "0.0.0"

        [tool.interlocks]
        preset = "progressive"
        """,
    )

    cfg = load_config()

    assert cfg.preset == "progressive"
    assert cfg.enforce_crap is True
    assert cfg.enforce_behavior_attribution is True
    assert cfg.enforce_mutation is True
    assert cfg.run_mutation_in_ci is True
    assert cfg.run_acceptance_in_check is True
    assert cfg.require_acceptance is True
    assert cfg.mutation_ci_mode == "incremental"


def test_progressive_preset_with_no_baseline_uses_permissive_thresholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare-repo first run on progressive must not block — thresholds stay permissive."""
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "progressive-bare"
        version = "0.0.0"

        [tool.interlocks]
        preset = "progressive"
        """,
    )

    cfg = load_config()

    assert cfg.coverage_min == 0
    assert cfg.mutation_min_score == 0.0
    assert cfg.crap_max == 100.0
    assert cfg.attribution_min_coverage == 0.0


def test_progressive_preset_elevates_thresholds_from_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "progressive-elevate"
        version = "0.0.0"

        [tool.interlocks]
        preset = "progressive"
        """,
    )
    baseline_dir = tmp_path / ".interlocks"
    baseline_dir.mkdir()
    (baseline_dir / "baseline.json").write_text(
        '{"schema_version": 1, "floors": {"coverage_min": 67, '
        '"mutation_min_score": 51.2, "crap_max": 18.0, '
        '"attribution_min_coverage": 0.92}, "advanced_from_sha": "abc1234"}',
        encoding="utf-8",
    )

    cfg = load_config()

    assert cfg.coverage_min == 67
    assert cfg.mutation_min_score == 51.2
    assert cfg.crap_max == 18.0
    assert cfg.attribution_min_coverage == 0.92
    assert cfg.value_sources["coverage_min"] == "baseline-floor"
    assert cfg.value_sources["mutation_min_score"] == "baseline-floor"
    assert cfg.value_sources["crap_max"] == "baseline-floor"
    assert cfg.value_sources["attribution_min_coverage"] == "baseline-floor"


def test_progressive_preset_baseline_does_not_lower_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit project value above the baseline floor wins — floor never lowers it."""
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "progressive-explicit"
        version = "0.0.0"

        [tool.interlocks]
        preset = "progressive"
        coverage_min = 80
        crap_max = 10.0
        """,
    )
    (tmp_path / ".interlocks").mkdir()
    (tmp_path / ".interlocks" / "baseline.json").write_text(
        '{"schema_version": 1, "floors": {"coverage_min": 67, "crap_max": 18.0}}',
        encoding="utf-8",
    )

    cfg = load_config()

    assert cfg.coverage_min == 80
    assert cfg.crap_max == 10.0
    assert cfg.value_sources["coverage_min"] == "project-configured"
    assert cfg.value_sources["crap_max"] == "project-configured"


def test_legacy_preset_resolves_ratcheting_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "legacy"
        version = "0.0.0"

        [tool.interlocks]
        preset = "legacy"
        """,
    )

    cfg = load_config()

    assert cfg.preset == "legacy"
    assert cfg.coverage_min == 0
    assert cfg.crap_max == 80.0
    assert cfg.enforce_crap is False
    assert cfg.mutation_min_score == 0.0
    assert cfg.run_mutation_in_ci is False


def test_project_explicit_value_overrides_project_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "strict-override"
        version = "0.0.0"

        [tool.interlocks]
        preset = "strict"
        coverage_min = 91
        enforce_mutation = false
        """,
    )

    cfg = load_config()

    assert cfg.preset == "strict"
    assert cfg.coverage_min == 91
    assert cfg.enforce_mutation is False
    assert cfg.value_sources["coverage_min"] == "project-configured"


def test_unsupported_preset_is_reported_without_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "unsupported"
        version = "0.0.0"

        [tool.interlocks]
        preset = "agent-safe"
        """,
    )

    cfg = load_config()

    assert cfg.preset is None
    assert cfg.coverage_min == 80
    assert cfg.unsupported_presets == ("project-configured: agent-safe",)


# ─────────────── load_config overrides ──────────────────────────────


def test_overrides_win_over_autodetect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "spec").mkdir()
    (tmp_path / "source").mkdir()
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [project]
        name = "sample"
        version = "0.0.0"

        [tool.interlocks]
        src_dir = "source"
        test_dir = "spec"
        test_runner = "unittest"
        test_invoker = "uv"
        pytest_args = ["-x", "--tb=short"]
        """,
    )
    cfg = load_config()
    assert cfg.src_dir == (tmp_path / "source").resolve()
    assert cfg.test_dir == (tmp_path / "spec").resolve()
    assert cfg.test_runner == "unittest"
    assert cfg.test_invoker == "uv"
    assert cfg.pytest_args == ("-x", "--tb=short")


def test_invalid_runner_override_falls_back_to_detect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_pyproject(
        tmp_path,
        monkeypatch,
        """
        [tool.interlocks]
        test_runner = "nose"
        """,
    )
    cfg = load_config()
    # Bad value is ignored — detection falls through; no pytest signals → unittest.
    assert cfg.test_runner in ("pytest", "unittest")


# ─────────────── command builders ───────────────────────────────────


_FAKE_ROOT = Path("/proj")


def _cfg(**overrides: object) -> InterlockConfig:
    defaults = {
        "project_root": _FAKE_ROOT,
        "src_dir": _FAKE_ROOT / "mypkg",
        "test_dir": _FAKE_ROOT / "tests",
        "test_runner": "pytest",
        "test_invoker": "python",
        "pytest_args": (),
    }
    defaults.update(overrides)
    return InterlockConfig(**defaults)  # type: ignore[arg-type]


def test_build_test_command_python_pytest() -> None:
    cfg = _cfg()
    assert build_test_command(cfg) == [sys.executable, "-m", "pytest", "tests", "-q"]


def test_build_test_command_pytest_appends_pytest_args() -> None:
    cfg = _cfg(pytest_args=("-x", "--tb=short"))
    expected = [sys.executable, "-m", "pytest", "tests", "-q", "-x", "--tb=short"]
    assert build_test_command(cfg) == expected


def test_build_test_command_uv_pytest() -> None:
    cfg = _cfg(test_invoker="uv")
    assert build_test_command(cfg) == ["uv", "run", "python", "-m", "pytest", "tests", "-q"]


def test_build_test_command_unittest_discover() -> None:
    cfg = _cfg(test_runner="unittest")
    expected = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]
    assert build_test_command(cfg) == expected


def test_build_coverage_test_command_pytest() -> None:
    cfg = _cfg()
    assert build_coverage_test_command(cfg) == [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "-m",
        "pytest",
        "tests",
        "-q",
    ]


def test_build_coverage_test_command_uv() -> None:
    cfg = _cfg(test_invoker="uv", test_runner="unittest")
    spec = f"coverage=={default_pin('coverage')}"
    assert build_coverage_test_command(cfg) == [
        "uv",
        "run",
        "--with",
        spec,
        "--index-strategy",
        "first-index",
        "python",
        "-m",
        "coverage",
        "run",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-q",
    ]
    assert "uv run coverage" not in " ".join(build_coverage_test_command(cfg))


# ─────────────── target-venv interpreter resolution ─────────────────


def _make_stub_venv_python(project_root: Path) -> Path:
    """Create ``.venv/bin/python`` (or ``.venv/Scripts/python.exe`` on Windows)."""
    if os.name == "nt":
        bin_dir = project_root / ".venv" / "Scripts"
        python = bin_dir / "python.exe"
    else:
        bin_dir = project_root / ".venv" / "bin"
        python = bin_dir / "python"
    bin_dir.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    Path(python).chmod(0o755)
    return python


def test_invoker_prefix_uses_target_venv_python(tmp_path: Path) -> None:
    python = _make_stub_venv_python(tmp_path)
    cfg = _cfg(project_root=tmp_path)
    assert invoker_prefix(cfg) == [str(python), "-m"]


def test_invoker_prefix_falls_back_to_sys_executable_when_no_venv(tmp_path: Path) -> None:
    cfg = _cfg(project_root=tmp_path)
    assert invoker_prefix(cfg) == [sys.executable, "-m"]


def test_invoker_prefix_uv_ignores_target_venv(tmp_path: Path) -> None:
    _make_stub_venv_python(tmp_path)
    cfg = _cfg(project_root=tmp_path, test_invoker="uv")
    assert invoker_prefix(cfg) == ["uv", "run", "python", "-m"]
