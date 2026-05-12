"""Rule catalog: default mode (auto/escrow/advisory) and mutation class per code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["auto", "escrow", "advisory", "skip"]
MutationClass = Literal[
    "import_sort",
    "eof_newline",
    "import_delete",
    "unused_variable",
    "type_annotation_rewrite",
    "collection_rewrite",
    "control_flow_or_style",
    "broad_modernization",
    "other",
]


@dataclass(frozen=True)
class RulePolicy:
    """Policy metadata for one ruff rule code."""

    rule: str
    mode: Mode
    mutation_class: MutationClass
    base_risk: int


_CATALOG: dict[str, RulePolicy] = {
    "I001": RulePolicy("I001", "auto", "import_sort", 2),
    "W292": RulePolicy("W292", "auto", "eof_newline", 0),
    "F401": RulePolicy("F401", "escrow", "import_delete", 6),
    "F841": RulePolicy("F841", "escrow", "unused_variable", 7),
    "UP007": RulePolicy("UP007", "escrow", "type_annotation_rewrite", 4),
    "UP045": RulePolicy("UP045", "escrow", "type_annotation_rewrite", 4),
}

_PREFIX_FALLBACKS: tuple[tuple[str, RulePolicy], ...] = (
    ("UP", RulePolicy("UP", "escrow", "broad_modernization", 7)),
    ("SIM", RulePolicy("SIM", "advisory", "control_flow_or_style", 10)),
    ("C4", RulePolicy("C4", "advisory", "collection_rewrite", 8)),
    ("PIE", RulePolicy("PIE", "advisory", "other", 5)),
)

_DEFAULT_POLICY = RulePolicy("default", "advisory", "other", 5)


def policy_for(rule: str) -> RulePolicy:
    """Return the policy for ``rule`` — exact match wins over prefix fallback."""
    if rule in _CATALOG:
        return _CATALOG[rule]
    for prefix, fallback in _PREFIX_FALLBACKS:
        if rule.startswith(prefix):
            # Re-tag the policy so callers see the requested code, not the prefix.
            return RulePolicy(rule, fallback.mode, fallback.mutation_class, fallback.base_risk)
    return RulePolicy(
        rule,
        _DEFAULT_POLICY.mode,
        _DEFAULT_POLICY.mutation_class,
        _DEFAULT_POLICY.base_risk,
    )


def known_rules() -> tuple[str, ...]:
    """Rule codes with an exact entry in the catalog (sorted)."""
    return tuple(sorted(_CATALOG))
