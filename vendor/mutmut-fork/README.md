# interlock-mutmut

A PyPI-only fork of [boxed/mutmut](https://github.com/boxed/mutmut), published
as the distribution name **`interlock-mutmut`** so that interlock can be
installed cleanly via `pipx install interlock` (or `uv tool install interlock`)
without requiring `git` on the install host.

## Why this exists

Interlock currently depends on a specific upstream SHA that includes the
`set_start_method` guard (see [mutmut#466](https://github.com/boxed/mutmut/pull/466)),
which has not yet been released on PyPI. To avoid forcing every interlock
installer to have `git` available (pipx + the default PyPA resolver choke on
`git+` direct URLs in many sandboxed environments), we publish the exact same
source tree under a rename.

- **Upstream:** https://github.com/boxed/mutmut
- **License:** BSD-3-Clause (inherited unchanged from upstream)
- **Import path:** still `mutmut` — only the distribution name differs. A
  project that `import mutmut`s works identically whether it installed the
  upstream package or this fork.
- **Entry point:** the `mutmut` console script remains `mutmut`.

This is **not** a soft fork: we do not carry patches on top of upstream. The
sole purpose is to republish a known-good SHA under a name that PyPI accepts
and that pipx can resolve without VCS tooling. When upstream cuts a release
that includes the fixes interlock depends on, this fork will be retired and
interlock will switch back to the upstream distribution.

## Relationship to the wider repo

- `vendor/mutmut-fork/README.md` — this file.
- `vendor/mutmut-fork/PUBLISH.md` — the manual publish walkthrough.
- `vendor/mutmut-fork/pyproject.toml` — the template `pyproject.toml` that the
  publisher drops into a local clone of upstream mutmut before running
  `uv build` / `uv publish`.

See `PUBLISH.md` for the step-by-step walkthrough.
