"""Step definitions for the scaffolded example feature."""

from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/example.feature")


@given(parsers.parse("the number {value:d}"), target_fixture="value")
def _value(value: int) -> int:
    return value


@when(parsers.parse("I add {addend:d}"), target_fixture="result")
def _add(value: int, addend: int) -> int:
    return value + addend


@then(parsers.parse("the result is {expected:d}"))
def _check(result: int, expected: int) -> None:
    assert result == expected  # noqa: S101
