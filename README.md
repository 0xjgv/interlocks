# pyharness

A zero-config Python quality harness: lint, format, typecheck, test, coverage, audit, dep hygiene, architectural contracts — all behind `harness <task>`.

## Install

```
pipx install pyharness   # or: uv tool install pyharness
```

All tools (ruff, basedpyright, coverage, lizard, mutmut, pip-audit, deptry, import-linter, pytest) ship with the CLI.

## Usage

Run inside any Python project:

```
harness help         # show commands + detected project config
harness check        # fix + format + typecheck + test
harness ci           # read-only lint + format check + typecheck + deps + arch + coverage + complexity
harness pre-commit   # staged-only checks (install via `harness setup-hooks`)
harness coverage --min=80
harness audit                        # CVE scan via pip-audit
harness deps                         # dep hygiene (unused/missing/transitive) via deptry
harness arch                         # architectural contracts via import-linter (default: src ↛ tests)
harness crap --max=30                # advisory complexity × coverage gate
harness mutation --max-runtime=600   # advisory mutation score
```

## Configuration

`harness` walks up from your current directory to the nearest `pyproject.toml` and auto-detects:

- **project root** — first directory with `pyproject.toml` (pytest-style rootdir walk)
- **test runner** — `pytest` if `[tool.pytest.*]`, `pytest.ini`, `<test_dir>/conftest.py`, or pytest is declared/importable; otherwise `unittest`
- **test dir** — first existing of `tests/`, `test/`, `src/tests/`
- **source dir** — `[tool.uv.build-backend] module-name`, Hatch/Setuptools packages, `src/<pkg>`, or the first top-level `__init__.py`-bearing dir
- **test invoker** — `uv run` when `uv.lock` is present at the root, else `python -m`

Override any of these via `[tool.harness]` in your `pyproject.toml` (all keys optional):

```toml
[tool.harness]
src_dir = "mypkg"
test_dir = "tests"
test_runner = "pytest"     # or "unittest"
test_invoker = "python"    # or "uv"
pytest_args = ["-q", "-x"]
```

Run `harness help` to see what was auto-detected in your repo.
