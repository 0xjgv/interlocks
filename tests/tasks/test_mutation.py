"""Integration test for `cmd_mutation` — advisory mutation score via mutmut."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from interlocks import metrics as metrics_mod
from interlocks.config import InterlockConfig
from interlocks.tasks import mutation as mutation_mod
from interlocks.tasks.mutation import (
    _changed_to_globs,
    _mutant_in_changed,
    _print_survivors,
    _resolve_min_score,
    cmd_mutation,
)

_MODULE_SRC = textwrap.dedent(
    """\
    def is_positive(x):
        return x > 0
    """
)

_TEST_SRC = textwrap.dedent(
    """\
    import unittest
    from mypkg.mod import is_positive

    class TestIsPositive(unittest.TestCase):
        def test_positive(self):
            self.assertTrue(is_positive(1))
        def test_zero(self):
            self.assertFalse(is_positive(0))
        def test_negative(self):
            self.assertFalse(is_positive(-1))
    """
)

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "mut-probe"
    version = "0.0.1"
    requires-python = ">=3.13"

    [tool.coverage.run]
    source = ["mypkg"]
    branch = true

    [tool.mutmut]
    paths_to_mutate = ["mypkg/"]
    tests_dir = ["tests/"]
    """
)


def _run_coverage(cwd: Path) -> None:
    """Run the project's unittest suite under coverage so `.coverage` exists."""
    cmd = [sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"]
    subprocess.run(cmd, cwd=cwd, check=True)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Project with `mypkg/mod.py` + covering unittest under `tests/`."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_MODULE_SRC, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text(_TEST_SRC, encoding="utf-8")
    return tmp_path


def test_mutation_skips_when_coverage_missing(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No .coverage → cmd_mutation should warn_skip, never SystemExit."""
    monkeypatch.chdir(tmp_project)
    # Defaults (min-coverage=70) apply; no coverage.xml exists → skip path.
    monkeypatch.setattr(sys, "argv", ["interlocks", "mutation"])

    cmd_mutation()  # no SystemExit expected

    captured = capsys.readouterr()
    assert "mutation" in captured.out.lower()


@pytest.mark.slow
def test_mutation_runs_and_prints_score(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Happy path: coverage primed, short --max-runtime, mutmut reports a score."""
    monkeypatch.chdir(tmp_project)
    monkeypatch.syspath_prepend(str(tmp_project))
    _run_coverage(tmp_project)
    monkeypatch.setattr(
        sys, "argv", ["interlocks", "mutation", "--max-runtime=30", "--min-coverage=0"]
    )

    cmd_mutation()  # advisory — must never SystemExit

    captured = capsys.readouterr()
    assert "Mutation: score" in captured.out


# ─────────────── threshold cascade ─────────────────────


def test_mutation_min_coverage_comes_from_config(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """[tool.interlocks] mutation_min_coverage = 95 → skip message mentions 95.0%."""
    (tmp_project / "pyproject.toml").write_text(
        _PYPROJECT + "\n[tool.interlocks]\nmutation_min_coverage = 95\n", encoding="utf-8"
    )
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="0.5"></coverage>')
    monkeypatch.setattr(sys, "argv", ["interlocks", "mutation"])

    cmd_mutation()  # advisory — must never SystemExit
    captured = capsys.readouterr()
    assert "95" in captured.out  # threshold surfaced in the skip message


# ─────────────── _resolve_min_score precedence ─────────────────────


def _cfg(*, enforce: bool = False, min_score: float = 80.0) -> InterlockConfig:
    """Minimal cfg for `_resolve_min_score`; paths aren't touched."""
    root = Path()
    return InterlockConfig(
        project_root=root,
        src_dir=root / "src",
        test_dir=root / "tests",
        test_runner="pytest",
        test_invoker="python",
        enforce_mutation=enforce,
        mutation_min_score=min_score,
    )


def test_resolve_min_score_cli_flag_wins_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--min-score=42.5` beats caller-supplied default."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "mutation", "--min-score=42.5"])
    assert _resolve_min_score(_cfg(), default=99.0) == 42.5


def test_resolve_min_score_default_wins_over_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    """No CLI flag → caller-supplied default beats cfg.mutation_min_score."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "mutation"])
    assert _resolve_min_score(_cfg(enforce=True, min_score=80.0), default=55.0) == 55.0


def test_resolve_min_score_enforce_when_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """No CLI flag, no default → cfg.mutation_min_score when enforcing."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "mutation"])
    assert _resolve_min_score(_cfg(enforce=True, min_score=70.0)) == 70.0


def test_resolve_min_score_returns_none_when_advisory(monkeypatch: pytest.MonkeyPatch) -> None:
    """No CLI flag, no default, advisory → None (no gate)."""
    monkeypatch.setattr(sys, "argv", ["interlocks", "mutation"])
    assert _resolve_min_score(_cfg(enforce=False)) is None


# ─────────────── _mutant_in_changed ─────────────────────


def test_mutant_in_changed_matches_module_path() -> None:
    assert _mutant_in_changed("interlocks.git.x_foo__mutmut_1", {"interlocks/git.py"})


def test_mutant_in_changed_handles_nested_modules() -> None:
    assert _mutant_in_changed(
        "interlocks.tasks.mutation.x__parse_results__mutmut_5", {"interlocks/tasks/mutation.py"}
    )


def test_mutant_in_changed_matches_suffix() -> None:
    """Path matches if any changed file ends with '/<module-path>'."""
    assert _mutant_in_changed("interlocks.git.x_foo__mutmut_1", {"src/interlocks/git.py"})


def test_mutant_in_changed_misses_unrelated() -> None:
    assert not _mutant_in_changed("interlocks.git.x_foo__mutmut_1", {"interlocks/runner.py"})


def test_mutant_in_changed_empty_set_is_miss() -> None:
    assert not _mutant_in_changed("interlocks.git.x_foo__mutmut_1", set())


# ─────────────── _print_survivors ─────────────────────


def test_print_survivors_prints_nothing_when_empty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_survivors([], None)
    assert capsys.readouterr().out == ""


def test_print_survivors_prints_header_and_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_survivors(["interlocks.a.x__mutmut_1", "interlocks.b.x__mutmut_2"], None)
    out = capsys.readouterr().out
    assert "surviving mutants (2 shown)" in out
    assert "interlocks.a.x__mutmut_1" in out
    assert "interlocks.b.x__mutmut_2" in out


def test_print_survivors_caps_at_twenty(capsys: pytest.CaptureFixture[str]) -> None:
    many = [f"interlocks.a.x__mutmut_{i}" for i in range(30)]
    _print_survivors(many, None)
    out = capsys.readouterr().out
    assert "surviving mutants (20 shown)" in out
    assert "interlocks.a.x__mutmut_0" in out
    assert "interlocks.a.x__mutmut_19" in out
    assert "interlocks.a.x__mutmut_20" not in out


def test_print_survivors_filters_to_changed_set(
    capsys: pytest.CaptureFixture[str],
) -> None:
    survivors = ["interlocks.git.x_foo__mutmut_1", "interlocks.runner.x_bar__mutmut_2"]
    _print_survivors(survivors, {"interlocks/git.py"})
    out = capsys.readouterr().out
    assert "interlocks.git.x_foo__mutmut_1" in out
    assert "interlocks.runner.x_bar__mutmut_2" not in out


def test_print_survivors_silent_when_nothing_matches_changed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_survivors(["interlocks.runner.x_foo__mutmut_1"], {"interlocks/git.py"})
    assert capsys.readouterr().out == ""


# ─────────────── coverage fixture (shared with threshold test) ─────────


@pytest.fixture
def primed_coverage_xml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Path]:
    """Return a factory that writes `.coverage` + `coverage.xml` and stubs regeneration."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".coverage").write_text("", encoding="utf-8")
    xml = tmp_path / "coverage.xml"
    monkeypatch.setattr(metrics_mod, "generate_coverage_xml", lambda: xml)

    def _write(body: str) -> Path:
        xml.write_text(body, encoding="utf-8")
        return xml

    return _write


# ─────────────── _changed_to_globs ─────────────────────


def test_changed_to_globs_drops_tests() -> None:
    """Test paths under tests/ never become mutmut globs."""
    globs = _changed_to_globs({"interlocks/tasks/foo.py", "tests/test_x.py"}, "interlocks")
    assert globs == ["interlocks.tasks.foo.*"]


def test_changed_to_globs_handles_init() -> None:
    """`__init__.py` paths translate to dotted module globs without losing the name."""
    globs = _changed_to_globs({"interlocks/__init__.py"}, "interlocks")
    assert globs == ["interlocks.__init__.*"]


def test_changed_to_globs_returns_empty_when_no_src_files() -> None:
    """Diff with only test-tree paths produces no globs (caller will skip)."""
    globs = _changed_to_globs({"tests/x.py"}, "interlocks")
    assert globs == []


# ─────────────── cmd_mutation incremental wiring ─────────────────────


def test_cmd_mutation_skips_when_no_changed_src(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--changed-only` with empty src diff → warn_skip + no mutmut launch."""
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.setattr(mutation_mod, "changed_py_files_vs", lambda _ref: {"tests/test_x.py"})

    def _no_run(*_args: object, **_kwargs: object) -> tuple[bool, Path]:
        pytest.fail("_run_mutmut should not run when no src files changed")

    monkeypatch.setattr(mutation_mod, "_run_mutmut", _no_run)
    monkeypatch.setattr(sys, "argv", ["interlocks", "mutation", "--min-coverage=0"])

    cmd_mutation(changed_only=True)

    captured = capsys.readouterr()
    assert "no changed src files" in captured.out


def test_cmd_mutation_passes_globs_to_mutmut(
    tmp_project: Path,
    primed_coverage_xml: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--changed-only` with src diff → mutmut argv carries module globs."""
    primed_coverage_xml('<?xml version="1.0" ?><coverage line-rate="1.0"></coverage>')
    monkeypatch.chdir(tmp_project)
    monkeypatch.setattr(
        mutation_mod,
        "changed_py_files_vs",
        lambda _ref: {"mypkg/mod.py", "mypkg/other.py"},
    )

    captured_argv: list[list[str]] = []

    def _spy_run(argv: list[str], _timeout: int) -> tuple[bool, Path]:
        captured_argv.append(argv)
        return True, tmp_project / ".interlocks" / "mutation.log"

    monkeypatch.setattr(mutation_mod, "_run_mutmut", _spy_run)
    monkeypatch.setattr(
        mutation_mod, "read_mutation_summary", lambda: None
    )  # short-circuit before parsing
    monkeypatch.setattr(sys, "argv", ["interlocks", "mutation", "--min-coverage=0"])

    cmd_mutation(changed_only=True)

    assert captured_argv, "expected _run_mutmut to be called"
    argv = captured_argv[0]
    assert "mutmut" in " ".join(argv)
    # globs sorted by _changed_to_globs; both modules surface as trailing args.
    assert argv[-2:] == ["mypkg.mod.*", "mypkg.other.*"]
