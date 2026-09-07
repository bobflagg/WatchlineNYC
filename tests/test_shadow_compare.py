"""Hermetic tests for the shadow-comparison pure core (Option B Phase 4)."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.shadow_compare import compare_partitions


def test_v2_refines_legacy_is_clean():
    # legacy fused {1,2,3} (via an assoc edge); v2 splits into {1,2} and {3}. Refinement, no cross-merge.
    legacy = {1: "OG-1", 2: "OG-1", 3: "OG-1"}
    v2 = {1: "RE-1", 2: "RE-1", 3: "RE-3"}
    out = compare_partitions(v2, legacy)
    assert out["legacy_groups_split_in_v2"] == 1
    assert out["v2_entities_spanning_legacy_groups"] == 0        # invariant holds
    assert out["shared_nodes"] == 3


def test_v2_cross_merge_is_flagged():
    # anomaly: v2 merges across two legacy groups (should never happen if v2 edges ⊆ legacy edges).
    legacy = {1: "OG-1", 2: "OG-2"}
    v2 = {1: "RE-1", 2: "RE-1"}
    out = compare_partitions(v2, legacy)
    assert out["v2_entities_spanning_legacy_groups"] == 1
    assert out["v2_cross_examples"] == ["RE-1"]


def test_nodes_that_left_identity_are_counted():
    # node 9 is legacy-grouped (via registered-llc/deed) but absent from v2 = association-only.
    legacy = {1: "OG-1", 2: "OG-1", 9: "OG-1"}
    v2 = {1: "RE-1", 2: "RE-1"}
    out = compare_partitions(v2, legacy)
    assert out["left_identity_nodes"] == 1
    assert out["legacy_only_nodes"] == 1 and out["shared_nodes"] == 2


def test_coverage_counts():
    out = compare_partitions({1: "RE-1", 2: "RE-1"}, {2: "OG-2", 3: "OG-2"})
    assert out["v2_nodes"] == 2 and out["legacy_nodes"] == 2
    assert out["shared_nodes"] == 1 and out["v2_only_nodes"] == 1 and out["legacy_only_nodes"] == 1
