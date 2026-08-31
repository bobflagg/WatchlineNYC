"""Hermetic tests for the OwnerGroup union-find grouping.

Pure function, no dependencies — owner_groups is now a Neo4j-only step (it reads the
materialized CONNECTED_BY_SPLINK edges), so this runs in the default hermetic tier.
"""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.owner_groups import _union_groups


def test_merges_transitively_and_ids_by_min_node():
    # 1-2 and 2-3 -> one group {1,2,3}, id keyed on the min node.
    g = _union_groups([(1, 2), (2, 3)])
    assert g == {1: "OG-1", 2: "OG-1", 3: "OG-1"}


def test_singletons_and_below_min_size_are_dropped():
    # 5-6 is a 2-group (kept); 9 never appears in any pair (absent).
    g = _union_groups([(5, 6)])
    assert g == {5: "OG-5", 6: "OG-5"}
    assert 9 not in g
    # raise the floor: a 2-group no longer qualifies
    assert _union_groups([(5, 6)], min_size=3) == {}


def test_separate_components_stay_separate():
    g = _union_groups([(1, 2), (10, 11)])
    assert g[1] == g[2] == "OG-1"
    assert g[10] == g[11] == "OG-10"
    assert g[1] != g[10]


def test_curated_style_bridge_unions_two_clusters():
    # two model cliques {1,2},{3,4} bridged by a curated/LLC edge (2,3) -> one owner group.
    g = _union_groups([(1, 2), (3, 4), (2, 3)])
    assert len(set(g.values())) == 1
    assert set(g) == {1, 2, 3, 4}
    assert all(v == "OG-1" for v in g.values())
