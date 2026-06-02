"""Repository-level pytest hooks."""

from __future__ import annotations

import pytest

from interlocks.hypothesis_profiles import register_hypothesis_profiles


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    del config
    register_hypothesis_profiles()
