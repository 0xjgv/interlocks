"""Tests for `interlocks properties` and `interlocks init-properties`."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from interlocks.config import InterlockConfig
from interlocks.defaults_path import path as defaults_path
from tests.conftest import stub_project_venv

_PYPROJECT = textwrap.dedent(
    """\
    [project]
    name = "property-probe"
    version = "0.0.0"
    requires-python = ">=3.11"
    """
)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    stub_project_venv(tmp_path)
    return tmp_path


def _run_cli(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "interlocks.cli", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_property_candidates(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    from interlocks.config import clear_cache
    from interlocks.tasks import property_candidates as property_candidates_mod

    monkeypatch.chdir(project)
    clear_cache()
    argv = ["interlocks", "property-candidates", *args]
    monkeypatch.setattr(sys, "argv", argv)
    returncode = 0
    try:
        property_candidates_mod.cmd_property_candidates()
    except SystemExit as exc:
        returncode = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    clear_cache()
    return subprocess.CompletedProcess(argv, returncode, captured.out, captured.err)


def _run_init_properties(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    from interlocks.config import clear_cache
    from interlocks.tasks import properties as properties_mod

    monkeypatch.chdir(project)
    clear_cache()
    argv = ["interlocks", "init-properties", *args]
    monkeypatch.setattr(sys, "argv", argv)
    returncode = 0
    try:
        properties_mod.cmd_init_properties()
    except SystemExit as exc:
        returncode = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    clear_cache()
    return subprocess.CompletedProcess(argv, returncode, captured.out, captured.err)


def _run_properties_command(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    from interlocks.config import clear_cache
    from interlocks.tasks import properties as properties_mod

    monkeypatch.chdir(project)
    clear_cache()
    argv = ["interlocks", "properties", *args]
    monkeypatch.setattr(sys, "argv", argv)
    returncode = 0
    try:
        properties_mod.cmd_properties()
    except SystemExit as exc:
        returncode = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    clear_cache()
    return subprocess.CompletedProcess(argv, returncode, captured.out, captured.err)


def _load_project_config(project: Path, monkeypatch: pytest.MonkeyPatch) -> InterlockConfig:
    from interlocks.config import clear_cache, load_config

    monkeypatch.chdir(project)
    clear_cache()
    return load_config()


def _write_property(project: Path) -> None:
    properties = project / "properties"
    properties.mkdir()
    (properties / "test_lengths.py").write_text(
        textwrap.dedent(
            """\
            from hypothesis import given
            from hypothesis import strategies as st


            @given(st.lists(st.integers()))
            def test_reversing_preserves_length(values: list[int]) -> None:
                assert len(list(reversed(values))) == len(values)
            """
        ),
        encoding="utf-8",
    )


def test_init_properties_scaffolds_root_layout(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _run_init_properties(tmp_project, monkeypatch, capsys)

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert not (tmp_project / "properties" / "__init__.py").exists()
    assert not (tmp_project / "properties" / "conftest.py").exists()
    assert (tmp_project / "properties" / "test_example_properties.py").is_file()
    assert "hypothesis>=6" in result.stdout
    assert "project environment" in result.stdout
    assert "interlocks properties --profile=check" in result.stdout


def test_init_properties_json_reports_scaffold_actions(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _run_init_properties(tmp_project, monkeypatch, capsys, "--json")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    payload = json.loads(result.stdout)
    assert payload == {
        "command": "init-properties",
        "passed": True,
        "status": "scaffold-present",
        "properties_dir": "properties",
        "files": [
            {
                "path": "properties/test_example_properties.py",
                "action": "created",
            }
        ],
        "domain_property_test_count": 0,
        "domain_property_tests": [],
        "next_actions": [
            "Add `hypothesis>=6` to test/dev dependencies if it is missing.",
            "Create or sync the project environment if `interlocks doctor` reports one missing.",
            "Replace the example property with domain invariants.",
            "Run `interlocks properties --profile=check`.",
        ],
    }
    assert (tmp_project / "properties" / "test_example_properties.py").is_file()


def test_init_properties_preserves_existing_files_and_creates_missing(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_project / "properties" / "conftest.py"
    target.parent.mkdir()
    target.write_text("# pre-existing\n", encoding="utf-8")
    existing_init = tmp_project / "properties" / "__init__.py"
    existing_init.write_text("# existing package marker\n", encoding="utf-8")

    result = _run_init_properties(tmp_project, monkeypatch, capsys)

    assert result.returncode == 0, result.stderr
    assert target.read_text(encoding="utf-8") == "# pre-existing\n"
    assert existing_init.read_text(encoding="utf-8") == "# existing package marker\n"
    assert (tmp_project / "properties" / "test_example_properties.py").is_file()
    assert "properties/conftest.py" not in result.stdout
    assert "properties/__init__.py" not in result.stdout
    assert "created properties/test_example_properties.py" in result.stdout


def test_init_properties_does_not_add_example_when_domain_properties_exist(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_domain_properties.py").write_text(
        "def test_domain() -> None:\n    assert True\n", encoding="utf-8"
    )

    result = _run_init_properties(tmp_project, monkeypatch, capsys)

    assert result.returncode == 0, result.stderr
    assert not (properties / "test_example_properties.py").exists()
    assert "kept properties/" in result.stdout
    assert "replace the example" not in result.stdout
    assert "interlocks properties --profile=check" in result.stdout


def test_init_properties_json_reports_domain_properties_present(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_domain_properties.py").write_text(
        "def test_domain() -> None:\n    assert True\n", encoding="utf-8"
    )

    result = _run_init_properties(tmp_project, monkeypatch, capsys, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "command": "init-properties",
        "passed": True,
        "status": "domain-properties-present",
        "properties_dir": "properties",
        "files": [],
        "domain_property_test_count": 1,
        "domain_property_tests": ["properties/test_domain_properties.py"],
        "next_actions": ["Run `interlocks properties --profile=check`."],
    }
    assert not (properties / "test_example_properties.py").exists()


def test_domain_property_test_files_excludes_unchanged_scaffold_example(
    tmp_project: Path,
) -> None:
    from interlocks.config import clear_cache, load_config
    from interlocks.tasks.properties import domain_property_test_files, property_test_files

    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_example_properties.py").write_bytes(
        defaults_path("properties_test_example.py").read_bytes()
    )
    (properties / "test_domain_properties.py").write_text(
        "def test_domain() -> None:\n    assert True\n", encoding="utf-8"
    )
    clear_cache()
    cfg = load_config(tmp_project)

    assert {path.name for path in property_test_files(cfg)} == {
        "test_domain_properties.py",
        "test_example_properties.py",
    }
    assert [path.name for path in domain_property_test_files(cfg)] == ["test_domain_properties.py"]


def test_task_properties_returns_none_without_property_tests(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.properties import task_properties

    monkeypatch.chdir(tmp_project)
    clear_cache()

    assert task_properties(profile="ci") is None


def test_cmd_properties_skips_without_property_tests(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks.properties import cmd_properties

    monkeypatch.chdir(tmp_project)
    clear_cache()

    cmd_properties()

    assert "no property tests detected" in capsys.readouterr().out


def test_cmd_properties_json_reports_missing_property_tests(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _run_properties_command(tmp_project, monkeypatch, capsys, "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "command": "properties",
        "passed": True,
        "status": "skipped",
        "profile": "ci",
        "properties_dir": "properties",
        "reason": "no property tests detected",
        "next_actions": ["Run `interlocks init-properties` to scaffold properties/."],
    }


def test_cmd_properties_skips_when_project_env_missing(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks import properties as properties_mod

    monkeypatch.chdir(tmp_project)
    clear_cache()
    monkeypatch.setattr(properties_mod, "project_env_ready", lambda _cfg: False)
    monkeypatch.setattr(
        properties_mod, "project_env_skip_message", lambda label: f"{label}: no env"
    )

    properties_mod.cmd_properties()

    assert "properties: no env" in capsys.readouterr().out


def test_cmd_properties_json_reports_project_env_missing(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks import properties as properties_mod

    monkeypatch.chdir(tmp_project)
    clear_cache()
    monkeypatch.setattr(properties_mod, "project_env_ready", lambda _cfg: False)
    monkeypatch.setattr(
        properties_mod, "project_env_skip_message", lambda label: f"{label}: no env"
    )
    monkeypatch.setattr(sys, "argv", ["interlocks", "properties", "--json"])

    properties_mod.cmd_properties()

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "properties"
    assert payload["status"] == "skipped"
    assert payload["reason"] == "properties: no env"


def test_cmd_properties_runs_task_for_requested_profile(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from interlocks.config import clear_cache
    from interlocks.runner import Task
    from interlocks.tasks import properties as properties_mod

    _write_property(tmp_project)
    monkeypatch.chdir(tmp_project)
    clear_cache()
    monkeypatch.setattr(sys, "argv", ["interlocks", "properties", "--profile=check"])
    tasks: list[Task] = []
    monkeypatch.setattr(properties_mod, "run", tasks.append)

    properties_mod.cmd_properties()

    [task] = tasks
    assert task.label == "properties"
    assert task.display == "pytest properties --hypothesis-profile=check"
    assert task.start_status == "running"


def test_cmd_properties_json_runs_task_for_requested_profile(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_property(tmp_project)

    result = _run_properties_command(tmp_project, monkeypatch, capsys, "--profile=check", "--json")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["command"] == "properties"
    assert payload["passed"] is True
    assert payload["profile"] == "check"
    assert payload["properties_dir"] == "properties"
    assert payload["gates"][0]["name"] == "properties"
    assert "hypothesis-profile=check" in result.stderr


def test_properties_cli_skip_mentions_detected_nested_dir(tmp_project: Path) -> None:
    nested = tmp_project / "tests" / "properties"
    nested.mkdir(parents=True)

    result = _run_cli(tmp_project, "properties")

    assert result.returncode == 0, result.stderr
    assert "to scaffold tests/properties/" in result.stdout


def test_properties_cli_runs_root_property_tests(tmp_project: Path) -> None:
    _write_property(tmp_project)

    result = _run_cli(tmp_project, "properties", "--profile=default")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "[properties]" in result.stdout


def test_properties_cli_runs_nested_property_tests_without_scaffold_conftest(
    tmp_project: Path,
) -> None:
    nested = tmp_project / "tests" / "properties"
    nested.mkdir(parents=True)
    (nested / "test_lengths.py").write_text(
        textwrap.dedent(
            """\
            from hypothesis import given
            from hypothesis import strategies as st


            @given(st.lists(st.integers()))
            def test_reversing_preserves_length(values: list[int]) -> None:
                assert len(list(reversed(values))) == len(values)
            """
        ),
        encoding="utf-8",
    )

    result = _run_cli(tmp_project, "properties", "--profile=check")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "[properties]" in result.stdout


def test_properties_cli_rejects_unknown_profile(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_property(tmp_project)

    result = _run_properties_command(tmp_project, monkeypatch, capsys, "--profile=slow")

    assert result.returncode != 0
    assert "unsupported profile" in result.stdout
    assert "expected check|ci|nightly|default" in result.stdout


def test_properties_cli_rejects_unknown_profile_json(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _run_properties_command(tmp_project, monkeypatch, capsys, "--profile=slow", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload == {
        "command": "properties",
        "passed": False,
        "error": "unsupported profile 'slow'",
        "expected_profiles": ["check", "ci", "nightly", "default"],
    }


def test_properties_rejects_unknown_profile_before_env_check(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.config import clear_cache
    from interlocks.tasks import properties as properties_mod

    monkeypatch.chdir(tmp_project)
    clear_cache()
    monkeypatch.setattr(properties_mod, "project_env_ready", lambda _cfg: False)
    monkeypatch.setattr(sys, "argv", ["interlocks", "properties", "--profile=slow", "--json"])

    with pytest.raises(SystemExit) as exc:
        properties_mod.cmd_properties()

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "unsupported profile 'slow'"


def test_existing_nested_properties_dir_is_detected(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.config import clear_cache, load_config

    nested = tmp_project / "tests" / "properties"
    nested.mkdir(parents=True)
    monkeypatch.chdir(tmp_project)
    clear_cache()

    assert load_config().properties_dir == nested.resolve()


def _write_property_candidate_probe(tmp_project: Path) -> None:
    pkg = tmp_project / "property_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        textwrap.dedent(
            """\
            import os
            import sys
            from pathlib import Path


            def parse_count(raw: str) -> int:
                value = raw.strip()
                if not value:
                    return 0
                return int(value)


            def format_debug(raw: str) -> str:
                print(raw)
                if not raw:
                    return ""
                return raw.upper()


            def normalize_items(values: list[int]) -> list[int]:
                return sorted(values)


            def split_pair(pair: tuple[int, str]) -> tuple[int, str]:
                return pair


            def merge_counts(values: dict[str, int]) -> dict[str, int]:
                return dict(values)


            def resolve_probe(path: Path) -> str:
                if path.is_absolute():
                    return path.name
                if path.suffix:
                    return path.stem
                if not path.name:
                    return ""
                return path.name


            async def parse_async(raw: str) -> int:
                return int(raw or "0")


            def cmd_parse(raw: str) -> int:
                return int(raw or "0")


            def parse_system(raw: str) -> int:
                global SEEN
                SEEN = raw
                if raw == "boom":
                    raise ValueError(raw)
                with open(os.devnull, "w", encoding="utf-8") as handle:
                    handle.write(raw)
                sys.path = []
                return 0 if os.path.exists(raw) else len(raw)
            """
        ),
        encoding="utf-8",
    )


def _candidate_by_name(payload: dict[str, object], name: str) -> dict[str, object]:
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    return next(candidate for candidate in candidates if candidate["name"] == name)


def test_property_candidates_json_ranks_pure_typed_functions(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_property_candidate_probe(tmp_project)

    result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--json", "--limit=0")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    payload = json.loads(result.stdout)
    names = [candidate["name"] for candidate in payload["candidates"]]
    assert names[0] == "parse_count"
    first = payload["candidates"][0]
    assert first["strategies"]["raw"] == "st.text()"
    assert "typed generated inputs" in first["reasons"]
    assert first["property_refs"] == 0
    debug_candidate = _candidate_by_name(payload, "format_debug")
    debug_cautions = debug_candidate["cautions"]
    assert isinstance(debug_cautions, list)
    assert "possible side effect call: print" in debug_cautions
    strategies = {
        candidate["name"]: candidate["strategies"] for candidate in payload["candidates"]
    }
    assert strategies["normalize_items"]["values"] == "st.lists(...)"
    assert strategies["split_pair"]["pair"] == "st.tuples(...)"
    assert strategies["merge_counts"]["values"] == "st.dictionaries(...)"
    assert strategies["resolve_probe"]["path"] == "tmp_path-derived Path"


def test_property_candidates_uncovered_hides_property_referenced_functions(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg = tmp_project / "property_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        textwrap.dedent(
            """\
            def parse_count(raw: str) -> int:
                if not raw:
                    return 0
                return int(raw)


            def parse_total(raw: str) -> int:
                if not raw:
                    return 0
                return int(raw)
            """
        ),
        encoding="utf-8",
    )
    (pkg / "other.py").write_text(
        textwrap.dedent(
            """\
            def parse_count(raw: str) -> int:
                if not raw:
                    return 0
                return int(raw)
            """
        ),
        encoding="utf-8",
    )
    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_core_properties.py").write_text(
        "from property_probe.core import parse_count\n\n"
        "def test_count_reference() -> None:\n"
        "    parse_count('1')\n",
        encoding="utf-8",
    )

    all_result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--json", "--limit=0")
    uncovered_result = _run_property_candidates(
        tmp_project, monkeypatch, capsys, "--json", "--uncovered", "--limit=0"
    )

    assert all_result.returncode == 0, all_result.stderr
    assert uncovered_result.returncode == 0, uncovered_result.stderr
    all_payload = json.loads(all_result.stdout)
    uncovered_payload = json.loads(uncovered_result.stdout)
    all_by_symbol = {
        (candidate["path"], candidate["name"]): candidate
        for candidate in all_payload["candidates"]
    }
    uncovered_symbols = {
        (candidate["path"], candidate["name"]) for candidate in uncovered_payload["candidates"]
    }
    assert all_payload["include_referenced"] is True
    assert uncovered_payload["include_referenced"] is False
    assert all_by_symbol["property_probe/core.py", "parse_count"]["property_refs"] >= 1
    assert all_by_symbol["property_probe/other.py", "parse_count"]["property_refs"] == 0
    assert ("property_probe/core.py", "parse_count") not in uncovered_symbols
    assert ("property_probe/other.py", "parse_count") in uncovered_symbols
    assert ("property_probe/core.py", "parse_total") in uncovered_symbols


def test_property_candidates_uncovered_counts_function_local_property_imports(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg = tmp_project / "property_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        textwrap.dedent(
            """\
            def parse_count(raw: str) -> int:
                if not raw:
                    return 0
                return int(raw)
            """
        ),
        encoding="utf-8",
    )
    (pkg / "other.py").write_text(
        textwrap.dedent(
            """\
            def parse_count(raw: str) -> int:
                if not raw:
                    return 0
                return int(raw)
            """
        ),
        encoding="utf-8",
    )
    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_core_properties.py").write_text(
        "def test_count_reference() -> None:\n"
        "    from property_probe.core import parse_count\n"
        "    parse_count('1')\n",
        encoding="utf-8",
    )

    all_result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--json", "--limit=0")
    uncovered_result = _run_property_candidates(
        tmp_project, monkeypatch, capsys, "--json", "--uncovered", "--limit=0"
    )

    assert all_result.returncode == 0, all_result.stderr
    assert uncovered_result.returncode == 0, uncovered_result.stderr
    all_payload = json.loads(all_result.stdout)
    uncovered_payload = json.loads(uncovered_result.stdout)
    all_by_symbol = {
        (candidate["path"], candidate["name"]): candidate
        for candidate in all_payload["candidates"]
    }
    uncovered_symbols = {
        (candidate["path"], candidate["name"]) for candidate in uncovered_payload["candidates"]
    }
    assert all_by_symbol["property_probe/core.py", "parse_count"]["property_refs"] >= 1
    assert all_by_symbol["property_probe/other.py", "parse_count"]["property_refs"] == 0
    assert ("property_probe/core.py", "parse_count") not in uncovered_symbols
    assert ("property_probe/other.py", "parse_count") in uncovered_symbols


def test_property_candidates_uncovered_requires_property_call_reference(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg = tmp_project / "property_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        textwrap.dedent(
            """\
            def parse_count(raw: str) -> int:
                if not raw:
                    return 0
                return int(raw)
            """
        ),
        encoding="utf-8",
    )
    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_core_properties.py").write_text(
        "from property_probe.core import parse_count\n\n"
        "def test_count_reference() -> None:\n"
        "    assert parse_count is not None\n",
        encoding="utf-8",
    )

    all_result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--json", "--limit=0")
    uncovered_result = _run_property_candidates(
        tmp_project, monkeypatch, capsys, "--json", "--uncovered", "--limit=0"
    )

    assert all_result.returncode == 0, all_result.stderr
    assert uncovered_result.returncode == 0, uncovered_result.stderr
    all_payload = json.loads(all_result.stdout)
    uncovered_payload = json.loads(uncovered_result.stdout)
    [candidate] = all_payload["candidates"]
    uncovered_symbols = {
        (candidate["path"], candidate["name"]) for candidate in uncovered_payload["candidates"]
    }
    assert candidate["property_refs"] == 0
    assert ("property_probe/core.py", "parse_count") in uncovered_symbols


def test_property_candidates_uncovered_resolves_conflicting_local_import_aliases_by_scope(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg = tmp_project / "property_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for module in ("core", "other"):
        (pkg / f"{module}.py").write_text(
            textwrap.dedent(
                """\
                def parse_count(raw: str) -> int:
                    if not raw:
                        return 0
                    return int(raw)
                """
            ),
            encoding="utf-8",
        )
    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_core_properties.py").write_text(
        "def test_core_reference() -> None:\n"
        "    from property_probe.core import parse_count\n"
        "    parse_count('1')\n\n"
        "def test_other_reference() -> None:\n"
        "    from property_probe.other import parse_count\n"
        "    parse_count('1')\n",
        encoding="utf-8",
    )

    all_result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--json", "--limit=0")
    uncovered_result = _run_property_candidates(
        tmp_project, monkeypatch, capsys, "--json", "--uncovered", "--limit=0"
    )

    assert all_result.returncode == 0, all_result.stderr
    assert uncovered_result.returncode == 0, uncovered_result.stderr
    all_payload = json.loads(all_result.stdout)
    uncovered_payload = json.loads(uncovered_result.stdout)
    all_by_symbol = {
        (candidate["path"], candidate["name"]): candidate
        for candidate in all_payload["candidates"]
    }
    uncovered_symbols = {
        (candidate["path"], candidate["name"]) for candidate in uncovered_payload["candidates"]
    }
    assert all_by_symbol["property_probe/core.py", "parse_count"]["property_refs"] >= 1
    assert all_by_symbol["property_probe/other.py", "parse_count"]["property_refs"] >= 1
    assert ("property_probe/core.py", "parse_count") not in uncovered_symbols
    assert ("property_probe/other.py", "parse_count") not in uncovered_symbols


def test_property_candidates_uncovered_hides_instance_method_property_references(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg = tmp_project / "property_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        textwrap.dedent(
            """\
            class Parser:
                def parse_value(self, raw: str) -> int:
                    if not raw:
                        return 0
                    return int(raw)
            """
        ),
        encoding="utf-8",
    )
    (pkg / "other.py").write_text(
        textwrap.dedent(
            """\
            class Parser:
                def parse_value(self, raw: str) -> int:
                    if not raw:
                        return 0
                    return int(raw)
            """
        ),
        encoding="utf-8",
    )
    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_core_properties.py").write_text(
        "from property_probe.core import Parser\n\n"
        "def test_parser_reference() -> None:\n"
        "    parser = Parser()\n"
        "    parser.parse_value('1')\n",
        encoding="utf-8",
    )

    all_result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--json", "--limit=0")
    uncovered_result = _run_property_candidates(
        tmp_project, monkeypatch, capsys, "--json", "--uncovered", "--limit=0"
    )

    assert all_result.returncode == 0, all_result.stderr
    assert uncovered_result.returncode == 0, uncovered_result.stderr
    all_payload = json.loads(all_result.stdout)
    uncovered_payload = json.loads(uncovered_result.stdout)
    all_by_symbol = {
        (candidate["path"], candidate["qualname"]): candidate
        for candidate in all_payload["candidates"]
    }
    uncovered_symbols = {
        (candidate["path"], candidate["qualname"]) for candidate in uncovered_payload["candidates"]
    }
    assert all_by_symbol["property_probe/core.py", "Parser.parse_value"]["property_refs"] >= 1
    assert all_by_symbol["property_probe/other.py", "Parser.parse_value"]["property_refs"] == 0
    assert ("property_probe/core.py", "Parser.parse_value") not in uncovered_symbols
    assert ("property_probe/other.py", "Parser.parse_value") in uncovered_symbols


def test_property_candidates_text_output_shows_class_qualname(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg = tmp_project / "property_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        textwrap.dedent(
            """\
            class Parser:
                def parse_value(self, raw: str) -> int:
                    if not raw:
                        return 0
                    return int(raw)
            """
        ),
        encoding="utf-8",
    )

    result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--limit=1")

    assert result.returncode == 0, result.stderr
    assert "Parser.parse_value" in result.stdout


def test_property_candidates_limit_rejects_negative(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--limit=-1")

    assert result.returncode != 0
    assert "--limit must be >= 0" in result.stdout


def test_property_candidates_limit_rejects_non_integer(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--limit=lots")

    assert result.returncode != 0
    assert "--limit must be an integer" in result.stdout


def test_property_candidates_limit_json_error_is_parseable(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--json", "--limit=lots")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["command"] == "property-candidates"
    assert payload["error"] == "property-candidates: --limit must be an integer"
    assert payload["expected_limit"] == "integer >= 0"
    assert "usage: interlocks property-candidates" in payload["usage"]


def test_property_candidates_usage_contract_is_exact() -> None:
    from interlocks.tasks import property_candidates as property_candidates_mod

    assert property_candidates_mod._property_candidates_usage() == (
        "usage: interlocks property-candidates "
        "[--changed[=REF]] [--uncovered] [--limit=N] [--json]"
    )


def test_property_candidates_json_error_contract_is_exact() -> None:
    from interlocks.tasks import property_candidates as property_candidates_mod

    payload = property_candidates_mod._property_candidates_error_payload(
        "property-candidates: --limit must be >= 0"
    )

    assert payload == {
        "command": "property-candidates",
        "error": "property-candidates: --limit must be >= 0",
        "usage": (
            "usage: interlocks property-candidates "
            "[--changed[=REF]] [--uncovered] [--limit=N] [--json]"
        ),
        "expected_limit": "integer >= 0",
    }


def test_fail_property_candidates_routes_json_and_human_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks import property_candidates as property_candidates_mod

    monkeypatch.setattr(property_candidates_mod.ui, "is_json", lambda: True)
    with pytest.raises(SystemExit) as exc:
        property_candidates_mod._fail_property_candidates("bad limit")
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["error"] == "bad limit"

    messages: list[str] = []
    monkeypatch.setattr(property_candidates_mod.ui, "is_json", lambda: False)
    monkeypatch.setattr(
        property_candidates_mod,
        "fail_skip",
        lambda message: messages.append(message) or (_ for _ in ()).throw(SystemExit(1)),
    )
    with pytest.raises(SystemExit):
        property_candidates_mod._fail_property_candidates("human bad limit")
    assert messages == ["human bad limit"]


def test_property_candidates_text_output_reports_no_candidates(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--limit=0")

    assert result.returncode == 0, result.stderr
    assert "no source functions look like strong property-test candidates" in result.stdout


def test_property_candidates_changed_scope_filters_and_skips_bad_python(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks import property_candidates as property_candidates_mod

    pkg = tmp_project / "property_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        "def parse_count(raw: str) -> int:\n"
        "    if not raw:\n"
        "        return 0\n"
        "    return int(raw)\n",
        encoding="utf-8",
    )
    (pkg / "other.py").write_text(
        "def parse_total(raw: str) -> int:\n"
        "    if not raw:\n"
        "        return 0\n"
        "    return int(raw)\n",
        encoding="utf-8",
    )
    (pkg / "broken.py").write_text("def nope(:\n", encoding="utf-8")
    monkeypatch.setattr(
        property_candidates_mod,
        "changed_py_files_vs",
        lambda ref: {"property_probe/core.py", "property_probe/broken.py"},
    )

    result = _run_property_candidates(
        tmp_project, monkeypatch, capsys, "--json", "--changed=HEAD", "--limit=0"
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["scope"] == "changed vs HEAD"
    assert [(candidate["path"], candidate["name"]) for candidate in payload["candidates"]] == [
        ("property_probe/core.py", "parse_count")
    ]


def test_property_candidates_resolves_reference_alias_variants(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pkg = tmp_project / "property_probe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        textwrap.dedent(
            """\
            def parse_count(raw: str) -> int:
                if not raw:
                    return 0
                return int(raw)


            class Parser:
                def parse_value(self, raw: str) -> int:
                    if not raw:
                        return 0
                    return int(raw)
            """
        ),
        encoding="utf-8",
    )
    (pkg / "other.py").write_text(
        textwrap.dedent(
            """\
            def parse_count(raw: str) -> int:
                if not raw:
                    return 0
                return int(raw)
            """
        ),
        encoding="utf-8",
    )
    properties = tmp_project / "properties"
    properties.mkdir()
    (properties / "test_references.py").write_text(
        "import property_probe.core as core_alias\n"
        "from property_probe import other as other_module\n"
        "from property_probe.core import Parser\n"
        "from property_probe.core import parse_count as ambiguous\n"
        "from property_probe.other import parse_count as ambiguous\n"
        "from property_probe.core import parse_count as ambiguous\n\n"
        "core_alias.parse_count('0')\n"
        "parser: Parser = Parser()\n\n"
        "class TestReferences:\n"
        "    def test_method(self) -> None:\n"
        "        core_alias.parse_count('1')\n\n"
        "def test_references() -> None:\n"
        "    other_module.parse_count('2')\n"
        "    Parser.parse_value(Parser(), '3')\n"
        "    parser.parse_value('4')\n"
        "    ambiguous('5')\n",
        encoding="utf-8",
    )

    result = _run_property_candidates(tmp_project, monkeypatch, capsys, "--json", "--limit=0")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    by_symbol = {
        (candidate["path"], candidate["qualname"]): candidate
        for candidate in payload["candidates"]
    }
    assert by_symbol["property_probe/core.py", "parse_count"]["property_refs"] >= 2
    assert by_symbol["property_probe/other.py", "parse_count"]["property_refs"] >= 1
    assert by_symbol["property_probe/core.py", "Parser.parse_value"]["property_refs"] >= 2


def test_property_candidate_internal_edges(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from interlocks.tasks import property_candidates as property_candidates_mod

    cfg = _load_project_config(tmp_project, monkeypatch)
    single = tmp_project / "single.py"
    single.write_text(
        "def parse_count(raw: str) -> int:\n"
        "    if not raw:\n"
        "        return 0\n"
        "    return int(raw)\n",
        encoding="utf-8",
    )

    assert property_candidates_mod._iter_source_files(replace(cfg, src_dir=single)) == [single]
    assert (
        property_candidates_mod._iter_source_files(replace(cfg, src_dir=tmp_project / "missing"))
        == []
    )
    assert property_candidates_mod._candidate_function_items(ast.Expression(ast.Constant(1))) == []
    assert property_candidates_mod._candidate_function_nodes(ast.parse(single.read_text()))[0].name
    assert (
        property_candidates_mod._property_references_from_tree(
            cfg, ast.Expression(ast.Constant(1))
        )
        == []
    )
    assert property_candidates_mod._reference_aliases(
        cfg, ast.Expression(ast.Constant(1))
    ) == property_candidates_mod._ReferenceAliases({}, {}, {})

    property_candidates_mod._record_import_from_aliases(
        cfg,
        ast.ImportFrom(module=None, names=[ast.alias(name="parse_count")], level=1),
        property_candidates_mod._ReferenceAliases({}, {}, {}),
    )
    assert property_candidates_mod._dotted_parts(ast.Constant("x")) == ()
    assert property_candidates_mod._call_name(ast.Constant("x")) == ""
    assert property_candidates_mod._strategy_for_annotation("set[int]") is None
