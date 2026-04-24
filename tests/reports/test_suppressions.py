"""Unit tests for harness.reports.suppressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.reports.suppressions import (
    _parse_line_for_suppressions,
    _scan_suppressions,
    print_suppressions_report,
)

# Layout the default-roots tests expect `load_config` to detect.
SRC_NAME = "pkg"
TEST_NAME = "tests"
_PYPROJECT = f"""\
[tool.harness]
src_dir = "{SRC_NAME}"
test_dir = "{TEST_NAME}"
"""


def _write_project_scaffold(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("x = 1  # noqa", [("noqa", [])]),
        ("x = 1  # noqa: E501", [("noqa", ["E501"])]),
        ("x = 1  # noqa: E501, F401", [("noqa", ["E501", "F401"])]),
        ("x = y  # type: ignore", [("type_ignore", [])]),
        ("x = y  # type: ignore[arg-type]", [("type_ignore", ["arg-type"])]),
        ("x = y  # pyright: ignore[reportFoo]", [("pyright_ignore", ["reportFoo"])]),
        ("x = 1  # unrelated comment", []),
        ("", []),
    ],
)
def test_parse_line(line: str, expected: list[tuple[str, list[str]]]) -> None:
    assert _parse_line_for_suppressions(line) == expected


def test_parse_line_multiple_kinds_on_same_line() -> None:
    # A single line with both noqa and type: ignore should emit both.
    out = _parse_line_for_suppressions("x = y  # noqa: E501  # type: ignore[arg-type]")
    kinds = {kind for kind, _ in out}
    assert kinds == {"noqa", "type_ignore"}


def test_scan_suppressions_with_custom_roots(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("x = 1  # noqa: E501\n", encoding="utf-8")
    (pkg / "b.py").write_text(
        "y = 2  # type: ignore[arg-type]\nz = 3  # pyright: ignore[reportFoo]\n",
        encoding="utf-8",
    )

    results = _scan_suppressions(roots=[str(pkg)])

    assert results["noqa"] == [["E501"]]
    assert results["type_ignore"] == [["arg-type"]]
    assert results["pyright_ignore"] == [["reportFoo"]]


def test_scan_suppressions_skips_unreadable_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "ok.py").write_text("x = 1  # noqa\n", encoding="utf-8")
    (pkg / "bad.py").write_text("y = 2\n", encoding="utf-8")

    original_read = Path.read_text

    def flaky_read(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "bad.py":
            raise OSError("boom")
        return original_read(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", flaky_read)
    results = _scan_suppressions(roots=[str(pkg)])
    assert results["noqa"] == [[]]


def test_scan_suppressions_default_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_project_scaffold(tmp_path)
    (tmp_path / SRC_NAME).mkdir()
    (tmp_path / SRC_NAME / "a.py").write_text("x = 1  # noqa: E501\n", encoding="utf-8")
    (tmp_path / TEST_NAME).mkdir()
    (tmp_path / TEST_NAME / "b.py").write_text("y = 2  # type: ignore\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    results = _scan_suppressions()
    assert results["noqa"] == [["E501"]]
    assert results["type_ignore"] == [[]]


def test_print_report_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project_scaffold(tmp_path)
    (tmp_path / SRC_NAME).mkdir()
    (tmp_path / TEST_NAME).mkdir()
    monkeypatch.chdir(tmp_path)

    print_suppressions_report()
    out = capsys.readouterr().out
    assert "── Suppressions " in out
    assert "Suppressions: 0 total" in out


def test_print_report_totals_and_breakdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_project_scaffold(tmp_path)
    (tmp_path / SRC_NAME).mkdir()
    (tmp_path / SRC_NAME / "a.py").write_text(
        "x = 1  # noqa: E501\ny = 2  # noqa: E501\nz = 3  # noqa: F401\n",
        encoding="utf-8",
    )
    (tmp_path / TEST_NAME).mkdir()
    (tmp_path / TEST_NAME / "b.py").write_text(
        "q = 4  # type: ignore[arg-type]\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    print_suppressions_report()
    out = capsys.readouterr().out
    assert "Suppressions: 4 total" in out
    assert "noqa: 3" in out
    assert "type_ignore: 1" in out
    # Most-frequent rule shown first
    assert "E501: 2" in out
    assert "F401: 1" in out
