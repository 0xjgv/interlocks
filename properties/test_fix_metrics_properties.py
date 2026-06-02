"""Property tests for fix-metrics summary helpers."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

from hypothesis import given
from hypothesis import strategies as st

from interlocks.tasks.fix_metrics import (
    _fix_metrics_payload,
    _int_or_zero,
    _mean,
    _read_json,
    _sources_detail,
    _summarize_optimize,
    _summarize_plan,
    _summarize_replay,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_JSON = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-100, max_value=100),
        st.floats(allow_nan=False, allow_infinity=False, min_value=-100, max_value=100),
        st.text(max_size=20),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=8),
        st.dictionaries(st.text(max_size=20), children, max_size=8),
    ),
    max_leaves=25,
)


@given(samples=st.lists(st.integers(min_value=-1_000, max_value=1_000), max_size=50))
def test_mean_matches_rounded_arithmetic_average(samples: list[int]) -> None:
    expected = 0.0 if not samples else round(sum(samples) / len(samples), 2)

    assert _mean(samples) == expected


@given(samples=st.lists(st.integers(min_value=-1_000, max_value=1_000), min_size=1, max_size=50))
def test_mean_stays_within_sample_bounds(samples: list[int]) -> None:
    average = _mean(samples)

    assert min(samples) <= average <= max(samples)


@given(raw=_JSON)
def test_int_or_zero_accepts_only_integer_like_values(raw: object) -> None:
    parsed = _int_or_zero(raw)

    if raw is None or isinstance(raw, bool):
        assert parsed == 0
    elif isinstance(raw, int):
        assert parsed == raw
    elif isinstance(raw, float):
        assert parsed == (int(raw) if math.isfinite(raw) else 0)
    elif isinstance(raw, str):
        try:
            assert parsed == int(raw)
        except ValueError:
            assert parsed == 0
    else:
        assert parsed == 0


@given(raw=_JSON)
def test_int_or_zero_always_returns_plain_int(raw: object) -> None:
    parsed = _int_or_zero(raw)

    assert isinstance(parsed, int)
    assert not isinstance(parsed, bool)


@given(payload=st.dictionaries(st.text(max_size=10), _JSON, max_size=8))
def test_read_json_returns_only_json_objects(payload: dict[str, object]) -> None:
    with TemporaryDirectory() as raw_root:
        path = Path(raw_root) / "artifact.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert _read_json(path) == payload


@given(raw=st.one_of(st.text(max_size=100), st.lists(_JSON, max_size=5)))
def test_read_json_rejects_malformed_or_non_object_json(raw: object) -> None:
    with TemporaryDirectory() as raw_root:
        path = Path(raw_root) / "artifact.json"
        if isinstance(raw, list):
            path.write_text(json.dumps(raw), encoding="utf-8")
            assert _read_json(path) is None
        else:
            path.write_text(raw, encoding="utf-8")
            try:
                expected = json.loads(raw)
            except ValueError:
                assert _read_json(path) is None
            else:
                assert _read_json(path) == (expected if isinstance(expected, dict) else None)


@given(metrics=st.dictionaries(st.text(max_size=10), _JSON, max_size=8))
def test_fix_metrics_payload_embeds_written_metrics(metrics: dict[str, object]) -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        out_path = root / ".lintfix" / "metrics.json"
        out_path.parent.mkdir()
        out_path.write_text(json.dumps(metrics), encoding="utf-8")

        payload = _fix_metrics_payload(root, out_path)

    assert payload["command"] == "fix-metrics"
    assert payload["passed"] is True
    assert payload["metrics_path"] == ".lintfix/metrics.json"
    assert payload["sources"] == metrics.get("sources", {})
    assert payload["metrics"] == metrics


@given(sources=st.dictionaries(st.text(min_size=1, max_size=10), st.booleans(), max_size=8))
def test_sources_detail_matches_enabled_source_names(sources: dict[str, bool]) -> None:
    detail = _sources_detail({"sources": sources})
    enabled = [name for name, present in sources.items() if present]

    if enabled and len(enabled) == len(sources):
        assert detail == "sources=all"
    elif enabled:
        assert detail == "sources=" + ",".join(enabled)
    else:
        assert detail == "sources=none"


@given(names=st.lists(st.text(min_size=1, max_size=10), max_size=8, unique=True))
def test_sources_detail_collapses_all_truthy_sources(names: list[str]) -> None:
    sources = dict.fromkeys(names, "present")

    detail = _sources_detail({"sources": sources})

    assert detail == ("sources=all" if names else "sources=none")


@given(raw=st.one_of(st.none(), st.text(max_size=20), st.integers(), st.lists(_JSON, max_size=5)))
def test_sources_detail_rejects_non_mapping_sources(raw: object) -> None:
    assert _sources_detail({"sources": raw}) == "sources=none"


@given(st.dictionaries(st.text(max_size=20), _JSON, max_size=10))
def test_fix_metrics_summaries_never_raise_on_json_objects(payload: dict[str, Any]) -> None:
    plan = _summarize_plan(payload)
    optimize = _summarize_optimize(payload)
    replay = _summarize_replay(payload)

    assert plan["candidates_total"] >= 0
    assert optimize["selected"] >= 0
    assert optimize["rejected"] >= 0
    assert replay["rules_total"] >= 0


@given(raw=st.one_of(_JSON, st.dictionaries(st.text(max_size=10), _JSON, max_size=5)))
def test_summarize_plan_ignores_malformed_candidates_collection(raw: object) -> None:
    if isinstance(raw, list):
        return

    summary = _summarize_plan({"candidates": raw})

    assert summary["candidates_total"] == 0


@given(
    selected=st.one_of(_JSON, st.dictionaries(st.text(max_size=10), _JSON, max_size=5)),
    rejected=st.one_of(_JSON, st.dictionaries(st.text(max_size=10), _JSON, max_size=5)),
)
def test_summarize_optimize_ignores_malformed_candidate_collections(
    selected: object,
    rejected: object,
) -> None:
    if isinstance(selected, list) or isinstance(rejected, list):
        return

    summary = _summarize_optimize({"selected": selected, "not_selected": rejected})

    assert summary["selected"] == 0
    assert summary["rejected"] == 0


@given(raw=st.one_of(_JSON, st.dictionaries(st.text(max_size=10), _JSON, max_size=5)))
def test_summarize_replay_ignores_malformed_rules_collection(raw: object) -> None:
    if isinstance(raw, list):
        return

    summary = _summarize_replay({"rules": raw})

    assert summary["rules_total"] == 0


@given(
    candidates=st.lists(
        st.fixed_dictionaries({
            "rule": st.text(max_size=10),
            "classification": st.sampled_from(["auto", "escrow", "advisory", "skip", ""]),
            "changed_lines_total": st.integers(min_value=0, max_value=100),
            "changed_lines_outside_diff": st.integers(min_value=0, max_value=100),
        }),
        max_size=30,
    )
)
def test_summarize_plan_groups_generated_candidates(
    candidates: list[dict[str, object]],
) -> None:
    summary = _summarize_plan({"candidates": candidates})
    by_class = Counter(str(candidate.get("classification") or "") for candidate in candidates)

    assert summary["candidates_total"] == len(candidates)
    assert summary["by_classification"] == dict(by_class)
    for classification, key in (
        ("auto", "auto_rules"),
        ("escrow", "escrow_rules"),
        ("advisory", "advisory_rules"),
        ("skip", "skipped_rules"),
    ):
        assert summary[key] == sorted(
            str(candidate.get("rule") or "")
            for candidate in candidates
            if candidate.get("classification") == classification
        )


@given(
    selected=st.lists(st.dictionaries(st.text(max_size=10), _JSON, max_size=5), max_size=20),
    rejected=st.lists(st.dictionaries(st.text(max_size=10), _JSON, max_size=5), max_size=20),
)
def test_summarize_optimize_counts_generated_selected_and_rejected(
    selected: list[Mapping[str, object]],
    rejected: list[Mapping[str, object]],
) -> None:
    summary = _summarize_optimize({"selected": selected, "not_selected": rejected})
    expected_reasons = Counter(
        str(candidate.get("reason") or "") for candidate in rejected if candidate.get("reason")
    )

    assert summary["selected"] == len(selected)
    assert summary["rejected"] == len(rejected)
    assert summary["rejection_reasons"] == dict(expected_reasons.most_common())


@given(rules=st.lists(st.dictionaries(st.text(max_size=10), _JSON, max_size=5), max_size=20))
def test_summarize_replay_counts_generated_recommendations(
    rules: list[Mapping[str, object]],
) -> None:
    summary = _summarize_replay({"rules": rules})

    assert summary["rules_total"] == len(rules)
    assert summary["by_recommendation"] == dict(
        Counter(str(rule.get("recommended_mode") or "") for rule in rules)
    )
    assert summary["pareto_frontier"] == sorted(
        str(rule.get("rule") or "") for rule in rules if rule.get("on_pareto_frontier")
    )
