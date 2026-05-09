"""Pre-fetch the bundled tool wheels into ``~/.cache/uv``.

Subsequent ``UV_OFFLINE=1 interlocks <stage>`` invocations dispatch through uvx
without touching the network. Two modes:

* When ``interlocks/defaults/tools.txt`` ships hash-pinned wheels (release
  artifact — generated via ``uv pip compile --generate-hashes``), warm uses
  ``uv pip install --require-hashes`` against a throw-away target so every wheel
  is verified and lands in the user's cache.
* Otherwise (development checkout with no ``tools.txt``), warm falls back to
  per-tool ``uvx --from <pkg>==<ver> <entry> --help`` to populate the cache
  with the same pins, just without hash enforcement. ``--help`` is the most
  portable probe: ``--version`` is unsupported by ``lint-imports`` and breaks
  on ``mutmut`` whose ``click.version_option`` reads metadata for the literal
  package name ``mutmut`` rather than our ``interlocks-mutmut`` distribution.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from interlocks.defaults.tools import DEFAULTS, entrypoint
from interlocks.runner import fail, ok, section, uvx_tool, warn_skip


def _tools_txt_path() -> Path:
    return Path(__file__).resolve().parent.parent / "defaults" / "tools.txt"


def _warm_via_tools_txt(tools_txt: Path) -> bool:
    """Hash-verified pre-fetch. Returns True on success."""
    target = Path(tempfile.mkdtemp(prefix="interlocks-warm-"))
    try:
        result = subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--require-hashes",
                "--target",
                str(target),
                "-r",
                str(tools_txt),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            fail("warm: hash-pinned pre-fetch failed")
            sys.stdout.write(result.stdout)
            sys.stdout.write(result.stderr)
            return False
        ok(f"warm: hash-verified {len(DEFAULTS)} tool(s) cached via tools.txt")
        return True
    finally:
        shutil.rmtree(target, ignore_errors=True)


def _warm_per_tool() -> bool:
    """Best-effort fallback: probe each pinned tool through uvx so its wheel lands in cache."""
    failed: list[str] = []
    for name, version in DEFAULTS.items():
        cmd = uvx_tool(name, "--help", version=version, entrypoint=entrypoint(name))
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        spec = f"{name}=={version}"
        if result.returncode == 0:
            ok(f"warm: cached {spec}")
        else:
            fail(f"warm: failed to fetch {spec}")
            failed.append(name)
    return not failed


def cmd_warm() -> None:
    """Populate ``~/.cache/uv`` with the bundled tool pins so offline runs work."""
    section("Warm uvx cache")
    if shutil.which("uv") is None:
        fail("warm: `uv` not found on PATH; install uv before warming the cache")
        sys.exit(1)
    tools_txt = _tools_txt_path()
    if tools_txt.is_file() and tools_txt.stat().st_size > 0:
        if _warm_via_tools_txt(tools_txt):
            return
        sys.exit(1)
    warn_skip("warm: tools.txt missing — falling back to per-tool uvx probes (no hash check)")
    if not _warm_per_tool():
        sys.exit(1)
