"""Rule catalog: exact-match precedence, prefix fallback, default fallback."""

from __future__ import annotations

from interlocks.lintfix.rules import known_rules, policy_for


def test_exact_match_wins_over_prefix() -> None:
    p = policy_for("UP007")
    assert p.mode == "escrow"
    assert p.mutation_class == "type_annotation_rewrite"
    assert p.base_risk == 4


def test_prefix_fallback_retags_rule() -> None:
    p = policy_for("UP999")
    assert p.rule == "UP999"
    assert p.mode == "escrow"
    assert p.mutation_class == "broad_modernization"


def test_sim_falls_back_to_advisory() -> None:
    assert policy_for("SIM118").mode == "advisory"


def test_unknown_rule_defaults_to_advisory() -> None:
    p = policy_for("ZZZ123")
    assert p.mode == "advisory"
    assert p.mutation_class == "other"


def test_known_rules_sorted_unique() -> None:
    rules = known_rules()
    assert rules == tuple(sorted(rules))
    assert len(rules) == len(set(rules))
    # Phase 1 catalogue must cover the rules called out in section 17.
    assert {"I001", "W292", "F401", "F841", "UP007"}.issubset(set(rules))


def test_auto_rules_carry_low_risk() -> None:
    assert policy_for("I001").mode == "auto"
    assert policy_for("W292").mode == "auto"
    assert policy_for("I001").base_risk <= 3
    assert policy_for("W292").base_risk == 0
