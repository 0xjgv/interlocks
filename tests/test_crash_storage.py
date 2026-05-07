"""Unit tests for ``interlocks.crash.storage``.

These tests isolate the cache root via ``XDG_CACHE_HOME`` so they never touch
the developer's real ``~/.cache``. Atomicity is verified by glob-asserting no
``*.tmp*`` leftovers post-write — we don't simulate a kernel crash, just the
happy-path cleanup contract.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from interlocks.crash import storage


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect ``XDG_CACHE_HOME`` at every test so we never touch the real cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def test_cache_dir_creates_chain_with_0700() -> None:
    directory = storage.cache_dir()
    assert directory.is_dir()
    assert directory.name == "crashes"
    assert directory.parent.name == "interlocks"
    mode = stat.S_IMODE(directory.stat().st_mode)
    assert mode == 0o700, f"expected 0700, got {oct(mode)}"


def test_cache_dir_idempotent() -> None:
    first = storage.cache_dir()
    second = storage.cache_dir()
    assert first == second
    assert second.is_dir()


def test_write_crash_round_trip() -> None:
    payload = {
        "fingerprint": "abc1234567890def",
        "exception_type": "RuntimeError",
        "subcommand": "lint",
        "frames": [["interlocks/cli.py", "main"]],
    }

    target = storage.write_crash(payload)

    assert target.exists()
    assert target.name == "abc1234567890def.json"
    assert target.parent == storage.cache_dir()

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"

    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed == payload


def test_write_crash_leaves_no_temp_artifacts() -> None:
    payload = {"fingerprint": "deadbeef00112233", "exception_type": "ValueError"}
    storage.write_crash(payload)

    directory = storage.cache_dir()
    leftovers = list(directory.glob("*.tmp*")) + list(directory.glob(".*tmp*"))
    # Filter to only paths that still match the tmp suffix; the final file is .json.
    tmp_only = [p for p in leftovers if ".tmp" in p.name]
    assert tmp_only == [], f"unexpected temp files: {tmp_only}"


def test_write_crash_missing_fingerprint_raises() -> None:
    with pytest.raises(ValueError):
        storage.write_crash({"exception_type": "RuntimeError"})


def test_write_crash_empty_fingerprint_raises() -> None:
    with pytest.raises(ValueError):
        storage.write_crash({"fingerprint": ""})


def test_should_suppress_within_window() -> None:
    fingerprint = "withinwindow0001"
    now = 1_700_000_000.0
    storage.record_seen(fingerprint, now=now - 86400)  # 1 day ago

    assert storage.should_suppress_transport(fingerprint, now=now) is True


def test_should_suppress_outside_window() -> None:
    fingerprint = "outsidewindow001"
    now = 1_700_000_000.0
    storage.record_seen(fingerprint, now=now - (31 * 86400))  # 31 days ago

    assert storage.should_suppress_transport(fingerprint, now=now) is False


def test_should_suppress_unknown_fingerprint() -> None:
    storage.record_seen("known00000000000", now=1_700_000_000.0)

    assert storage.should_suppress_transport("unknown000000000", now=1_700_000_000.0) is False


def test_should_suppress_missing_dedup_file() -> None:
    # cache_dir created, but no record_seen call → dedup.json absent.
    storage.cache_dir()

    assert storage.should_suppress_transport("nofileatall00000", now=1_700_000_000.0) is False


def test_should_suppress_corrupt_dedup_file_does_not_raise() -> None:
    directory = storage.cache_dir()
    (directory / "dedup.json").write_text("not-json", encoding="utf-8")

    # Must not raise, must return False.
    assert storage.should_suppress_transport("anything00000000", now=1_700_000_000.0) is False


def test_record_seen_round_trip_via_should_suppress() -> None:
    fingerprint = "roundtrip0000001"
    now = 1_700_000_000.0
    storage.record_seen(fingerprint, now=now)

    assert storage.should_suppress_transport(fingerprint, now=now) is True


def test_record_seen_overwrites_corrupt_file() -> None:
    directory = storage.cache_dir()
    (directory / "dedup.json").write_text("not-json", encoding="utf-8")

    fingerprint = "afterCorrupt0001"
    now = 1_700_000_000.0
    storage.record_seen(fingerprint, now=now)

    parsed = json.loads((directory / "dedup.json").read_text(encoding="utf-8"))
    assert parsed == {fingerprint: now}


def test_record_seen_preserves_other_entries() -> None:
    now = 1_700_000_000.0
    storage.record_seen("first00000000000", now=now - 100)
    storage.record_seen("second0000000000", now=now)

    directory = storage.cache_dir()
    parsed = json.loads((directory / "dedup.json").read_text(encoding="utf-8"))
    assert parsed == {"first00000000000": now - 100, "second0000000000": now}


def test_record_seen_atomic_no_temp_leftovers() -> None:
    storage.record_seen("notemp0000000001", now=1_700_000_000.0)

    directory = storage.cache_dir()
    tmp_only = [p for p in directory.iterdir() if ".tmp" in p.name]
    assert tmp_only == [], f"unexpected temp files: {tmp_only}"
