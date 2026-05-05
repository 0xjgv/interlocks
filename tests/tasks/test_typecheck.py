"""Integration tests for interlocks.tasks.typecheck.

``cmd_typecheck`` targets whatever ``load_config().src_dir`` resolves to. The
fixture here creates a flat ``interlocks/`` package so autodetect picks it up. A
subprocess with ``cwd=tmp_project`` would find the tmp dir's ``interlocks/``
before the installed package (ModuleNotFoundError on ``interlocks.cli``), so we
invoke the function directly under ``monkeypatch.chdir``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PYPROJECT = textwrap.dedent("""
    [project]
    name = "sample"
    version = "0.0.0"
    requires-python = ">=3.13"

    [tool.basedpyright]
    pythonVersion = "3.13"
    typeCheckingMode = "standard"
    reportMissingTypeStubs = false
""")

CLEAN = "def add(a: int, b: int) -> int:\n    return a + b\n"
VIOLATING = "def bad() -> int:\n    return 'not an int'\n"  # return-type mismatch


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "interlocks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_typecheck_clean_exits_zero(
    tmp_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from interlocks.tasks.typecheck import cmd_typecheck

    (tmp_project / "interlocks" / "mod.py").write_text(CLEAN, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    cmd_typecheck()

    out = capsys.readouterr().out
    assert "[typecheck]" in out
    assert "ok" in out


def test_typecheck_violating_exits_nonzero(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from interlocks.tasks.typecheck import cmd_typecheck

    (tmp_project / "interlocks" / "mod.py").write_text(VIOLATING, encoding="utf-8")
    monkeypatch.chdir(tmp_project)
    with pytest.raises(SystemExit) as excinfo:
        cmd_typecheck()
    assert excinfo.value.code != 0


# ─────────────── bundled pyrightconfig fallback ─────────────────────

_BARE_PYPROJECT = textwrap.dedent("""\
    [project]
    name = "bare"
    version = "0.0.0"
    requires-python = ">=3.13"
""")


def test_typecheck_injects_bundled_config_in_bare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare project: task must pass --project <bundled-pyrightconfig>."""
    from interlocks.tasks.typecheck import task_typecheck

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "interlocks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cmd = task_typecheck().cmd
    assert "--project" in cmd
    cfg_path = Path(cmd[cmd.index("--project") + 1])
    assert cfg_path.name == "pyrightconfig.json"
    assert cfg_path.is_file()


def test_typecheck_omits_config_when_project_has_tool_basedpyright(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[tool.basedpyright] in project pyproject: task must NOT inject --project."""
    from interlocks.tasks.typecheck import task_typecheck

    monkeypatch.chdir(tmp_project)
    assert "--project" not in task_typecheck().cmd


def test_typecheck_omits_config_when_project_has_pyrightconfig_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pyrightconfig.json in project root: task must NOT inject --project."""
    from interlocks.tasks.typecheck import task_typecheck

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text("{}\n", encoding="utf-8")
    pkg = tmp_path / "interlocks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert "--project" not in task_typecheck().cmd


# ─────────────── target venv pythonpath ─────────────────────


def _make_stub_venv_python(project_root: Path) -> Path:
    """Create the conventional in-tree venv Python executable for this platform."""
    from interlocks.detect import expected_target_interpreter

    python = expected_target_interpreter(project_root)
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    python.chmod(0o755)
    return python


def _run_setup_cmd(cmd: list[str | Path], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in cmd],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def test_typecheck_uses_target_venv_pythonpath_for_non_uv_project(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-uv project with .venv: basedpyright gets --pythonpath <target python>."""
    from interlocks.tasks.typecheck import task_typecheck

    python = _make_stub_venv_python(tmp_project)
    monkeypatch.chdir(tmp_project)

    cmd = task_typecheck().cmd

    assert "--pythonpath" in cmd
    assert cmd[cmd.index("--pythonpath") + 1] == str(python)
    assert "basedpyright" in Path(cmd[0]).name
    assert "-m" not in cmd[:2]


def test_typecheck_omits_pythonpath_when_no_target_venv(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No concrete target interpreter: keep existing basedpyright command behavior."""
    from interlocks.tasks.typecheck import task_typecheck

    monkeypatch.chdir(tmp_project)

    assert "--pythonpath" not in task_typecheck().cmd


def test_typecheck_uv_project_omits_pythonpath_even_when_venv_exists(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uv uses a command prefix, not a concrete --pythonpath file, in this implementation."""
    from interlocks.tasks.typecheck import task_typecheck

    _make_stub_venv_python(tmp_project)
    (tmp_project / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_project)

    assert "--pythonpath" not in task_typecheck().cmd


def test_typecheck_file_targets_follow_basedpyright_options(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stage-provided changed-file targets remain the final basedpyright args."""
    from interlocks.tasks.typecheck import task_typecheck

    python = _make_stub_venv_python(tmp_project)
    monkeypatch.chdir(tmp_project)

    cmd = task_typecheck(files=["interlocks/mod.py"]).cmd

    assert cmd[-1] == "interlocks/mod.py"
    assert cmd[cmd.index("--pythonpath") + 1] == str(python)


def test_typecheck_combines_bundled_config_and_target_pythonpath_in_bare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bare project with .venv: keep bundled --project and add target --pythonpath."""
    from interlocks.tasks.typecheck import task_typecheck

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    pkg = tmp_path / "interlocks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    python = _make_stub_venv_python(tmp_path)
    monkeypatch.chdir(tmp_path)

    cmd = task_typecheck().cmd

    assert "--project" in cmd
    cfg_path = Path(cmd[cmd.index("--project") + 1])
    assert cfg_path.name == "pyrightconfig.json"
    assert cfg_path.is_file()
    assert cmd[cmd.index("--pythonpath") + 1] == str(python)


def test_typecheck_project_tool_config_omits_project_but_keeps_pythonpath(
    tmp_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[tool.basedpyright] still suppresses bundled config when --pythonpath is present."""
    from interlocks.tasks.typecheck import task_typecheck

    python = _make_stub_venv_python(tmp_project)
    monkeypatch.chdir(tmp_project)

    cmd = task_typecheck().cmd

    assert "--project" not in cmd
    assert cmd[cmd.index("--pythonpath") + 1] == str(python)


def test_typecheck_pyright_sidecar_omits_project_but_keeps_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pyrightconfig sidecar still suppresses bundled config when --pythonpath is present."""
    from interlocks.tasks.typecheck import task_typecheck

    (tmp_path / "pyproject.toml").write_text(_BARE_PYPROJECT, encoding="utf-8")
    (tmp_path / "pyrightconfig.json").write_text("{}\n", encoding="utf-8")
    pkg = tmp_path / "interlocks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    python = _make_stub_venv_python(tmp_path)
    monkeypatch.chdir(tmp_path)

    cmd = task_typecheck().cmd

    assert "--project" not in cmd
    assert cmd[cmd.index("--pythonpath") + 1] == str(python)


@pytest.mark.slow
def test_typecheck_resolves_imports_from_target_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Bundled basedpyright should analyze imports against the target .venv."""
    if os.name == "nt":
        pytest.skip("POSIX venv layout assumed")

    from interlocks.tasks.typecheck import cmd_typecheck

    dependency = tmp_path / "dependency"
    dependency_pkg = dependency / "target_dep"
    dependency_pkg.mkdir(parents=True)
    (dependency / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "target-dep"
            version = "0.0.0"
            requires-python = ">=3.13"
            """
        ),
        encoding="utf-8",
    )
    (dependency_pkg / "__init__.py").write_text(
        "def marker() -> str:\n    return 'ok'\n",
        encoding="utf-8",
    )

    project = tmp_path / "project"
    app = project / "app"
    app.mkdir(parents=True)
    (project / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "uses_dep.py").write_text(
        "from target_dep import marker\n\nVALUE: str = marker()\n",
        encoding="utf-8",
    )

    _run_setup_cmd([sys.executable, "-m", "venv", project / ".venv"], cwd=project)
    venv_python = project / ".venv" / "bin" / "python"
    _run_setup_cmd([venv_python, "-m", "pip", "install", dependency], cwd=project)

    monkeypatch.chdir(project)
    cmd_typecheck()

    out = capsys.readouterr().out
    assert "[typecheck]" in out
    assert "ok" in out
