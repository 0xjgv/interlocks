# Publishing `interlock-mutmut` to PyPI

This is a **manual, one-off workflow**. Interlock maintainers run it when the
upstream SHA interlock pins needs to be republished under the
`interlock-mutmut` distribution name so that `pipx install interlocks` works
without `git` available on the install host.

## Prerequisites

- `git`, `uv` (>=0.9.5), and a PyPI API token scoped to the
  `interlock-mutmut` project.
- Maintainer access to https://pypi.org/project/interlock-mutmut/ (or the
  ability to claim the name on first publish).

## Walkthrough

### 1. Clone upstream mutmut

```sh
git clone https://github.com/boxed/mutmut.git /tmp/mutmut-fork
cd /tmp/mutmut-fork
```

### 2. Pin to a known-good SHA

Interlock today pins mutmut to commit
**`e31d923c734383ddb7df4aa439ab3c60fd7d629a`** (see the `mutmut @ git+...`
entry in interlock's root `pyproject.toml`). That commit corresponds to
upstream version **3.5.0** with the `set_start_method` guard from
[mutmut#466](https://github.com/boxed/mutmut/pull/466).

Check out that SHA:

```sh
git checkout e31d923c734383ddb7df4aa439ab3c60fd7d629a
```

If a newer upstream tag exists that supersedes both 3.5.0 and the
`set_start_method` guard, prefer that tag instead — but bump the `version`
in the template `pyproject.toml` (step 3) to match whatever upstream says.

### 3. Swap in the template `pyproject.toml`

Overwrite upstream's `pyproject.toml` with the skeleton shipped in this repo:

```sh
cp /path/to/interlock/vendor/mutmut-fork/pyproject.toml ./pyproject.toml
```

The skeleton keeps every upstream runtime dependency, the `mutmut` console
script, and the BSD-3-Clause license. It differs from upstream only in:

- `name = "interlock-mutmut"` (was `mutmut`)
- `description` — reflects the republish purpose
- `urls` — points back to upstream + interlock repo for issue routing
- authors — credits the upstream maintainer

Double-check the `version` field. Keep it in lockstep with upstream at the
pinned SHA (currently `3.5.0`). If a previous `interlock-mutmut` publish has
already claimed that version on PyPI, bump a local suffix
(e.g. `3.5.0.post1`) rather than picking an arbitrary version — this
preserves the upstream-version signal for downstream consumers.

### 4. Patch distribution-name fallback

The module import path stays `mutmut`, but the published distribution name is
`interlock-mutmut`. Patch upstream's version lookup so `import mutmut` works
when only `interlock-mutmut` metadata exists:

```sh
python - <<'PY'
from pathlib import Path

path = Path("src/mutmut/__init__.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    '__version__ = importlib.metadata.version("mutmut")\n',
    'try:\n'
    '    __version__ = importlib.metadata.version("mutmut")\n'
    'except importlib.metadata.PackageNotFoundError:\n'
    '    __version__ = importlib.metadata.version("interlock-mutmut")\n',
)
path.write_text(text, encoding="utf-8")
PY
```

### 5. Build

```sh
uv build
```

Verify `dist/interlock_mutmut-<version>-py3-none-any.whl` and the matching
`.tar.gz` are produced, and that the wheel still ships the `mutmut/` package
directory (i.e. the import path is unchanged):

```sh
unzip -l dist/interlock_mutmut-*.whl | grep '^.* mutmut/'
uvx twine check dist/*
```

Smoke-test from a fresh environment before publishing:

```sh
uv venv /tmp/interlock-mutmut-smoke
uv pip install --python /tmp/interlock-mutmut-smoke/bin/python dist/interlock_mutmut-*.whl
/tmp/interlock-mutmut-smoke/bin/python -c 'import mutmut; print(mutmut.__version__)'
/tmp/interlock-mutmut-smoke/bin/mutmut --help
```

### 6. Publish

```sh
uv publish --token "$PYPI_TOKEN"
```

On first publish, PyPI will register the `interlock-mutmut` project against
your account. Subsequent publishes need the same token scope.

Smoke-test from a fresh environment:

```sh
uv tool install --from interlock-mutmut mutmut
mutmut --help
```

### 7. Follow-up PR in interlock

This scaffold unit deliberately does **not** modify interlock's own
`pyproject.toml`. Once the first `interlock-mutmut` release is live on PyPI,
open a follow-up PR that rewrites the dependency line from:

```toml
"mutmut @ git+https://github.com/boxed/mutmut.git@<sha>",
```

to:

```toml
"interlock-mutmut>=3.5.0",
```

and regenerates `uv.lock`. That PR is intentionally separate so the publish
step (which requires human-held PyPI credentials) stays decoupled from
interlock's normal review flow.
