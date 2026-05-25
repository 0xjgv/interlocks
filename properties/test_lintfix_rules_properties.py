"""Property tests for lintfix rule policy selection."""

from __future__ import annotations

import string

from hypothesis import given
from hypothesis import strategies as st

from interlocks.lintfix.rules import known_rules, policy_for

_RULE_SUFFIX = st.text(alphabet=string.ascii_uppercase + string.digits, min_size=1, max_size=6)
_UNKNOWN_RULE = st.from_regex(r"[A-Z][A-Z0-9]{1,8}", fullmatch=True).filter(
    lambda rule: rule not in known_rules() and not rule.startswith(("UP", "SIM", "C4", "PIE"))
)


@given(rule=st.sampled_from(known_rules()))
def test_policy_for_known_rules_is_exact(rule: str) -> None:
    policy = policy_for(rule)

    assert policy.rule == rule
    assert rule in known_rules()


@given(prefix=st.sampled_from(("UP", "SIM", "C4", "PIE")), suffix=_RULE_SUFFIX)
def test_policy_for_prefix_fallback_retags_requested_rule(prefix: str, suffix: str) -> None:
    rule = f"{prefix}{suffix}"
    if rule in known_rules():
        return

    policy = policy_for(rule)

    assert policy.rule == rule
    if prefix == "UP":
        assert policy.mode == "escrow"
        assert policy.mutation_class == "broad_modernization"
    else:
        assert policy.mode == "advisory"


@given(rule=_UNKNOWN_RULE)
def test_policy_for_unknown_rules_defaults_to_advisory_other(rule: str) -> None:
    policy = policy_for(rule)

    assert policy.rule == rule
    assert policy.mode == "advisory"
    assert policy.mutation_class == "other"
    assert policy.base_risk == 5
