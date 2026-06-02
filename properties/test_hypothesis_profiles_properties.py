"""Property tests for shared Hypothesis profile registration."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from interlocks.hypothesis_profiles import (
    PROPERTY_PROFILES,
    hypothesis_profile_setup_source,
    register_hypothesis_profiles,
)


@given(profile=st.sampled_from(PROPERTY_PROFILES))
def test_declared_profiles_can_be_resolved(profile: str) -> None:
    register_hypothesis_profiles()

    assert settings.get_profile(profile) is not None


@given(profile=st.sampled_from(PROPERTY_PROFILES))
def test_setup_source_matches_registered_profile_catalog(profile: str) -> None:
    source = hypothesis_profile_setup_source()

    assert (f"register_profile({profile!r}" in source) is (profile != "default")
