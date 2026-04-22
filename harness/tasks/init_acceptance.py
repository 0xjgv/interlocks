"""Scaffold the pytest-bdd canonical layout under the project's test_dir.

Writes three files from bundled templates; refuses to overwrite anything that
already exists so re-running is safe. Stdlib-only.
"""

from __future__ import annotations

from harness.config import _relative_str, load_config
from harness.defaults_path import path as defaults_path
from harness.runner import fail_skip, ok, section


def cmd_init_acceptance() -> None:
    section("Init acceptance (pytest-bdd)")
    cfg = load_config()
    test_dir = cfg.test_dir
    test_dir.mkdir(parents=True, exist_ok=True)

    targets = [
        (test_dir / "features" / "example.feature", "bdd_example.feature"),
        (test_dir / "step_defs" / "test_example.py", "bdd_test_example.py"),
        (test_dir / "step_defs" / "conftest.py", "bdd_conftest.py"),
    ]

    existing = [t for t, _ in targets if t.exists()]
    if existing:
        rels = ", ".join(_relative_str(p, cfg.project_root) for p in existing)
        fail_skip(f"init-acceptance: refusing to overwrite existing files: {rels}")
        return  # fail_skip exits; this line only runs in tests that stub it.

    for target, template in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(defaults_path(template).read_bytes())
        ok(f"created {_relative_str(target, cfg.project_root)}")
