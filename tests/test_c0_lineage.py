"""Hermetic tests for the C0 collapse summary (pure)."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.c0_lineage import collapse_summary


def test_collapse_summary_counts_nodes_and_distinct_buildings():
    collapses = {"PR-n1-a": [1, 2], "PR-n1-b": [3, 4, 5]}
    node_bbls = {1: ["b1", "b2"], 2: ["b2"], 3: ["b3"], 4: ["b3", "b4"], 5: []}
    out = collapse_summary(collapses, node_bbls)
    assert out == {"collapses": 2, "nodes": 5, "buildings_affected": 4}   # b1,b2,b3,b4 distinct


def test_empty():
    assert collapse_summary({}, {}) == {"collapses": 0, "nodes": 0, "buildings_affected": 0}
