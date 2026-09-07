"""Hermetic tests for the C4 relationship-layer projection (Option B Phase 2)."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.owner_relationships import (
    DEED_REL, LLC_REL, to_entity_relationships)


def test_endpoints_map_to_resolution_ids_and_dedupe():
    # two deed edges between the same two resolved entities collapse to one relationship.
    partition = {1: "RE-1", 2: "RE-1", 3: "RE-3", 4: "RE-3"}   # {1,2} one entity, {3,4} another
    edges = [{"a": 1, "b": 3, "rel_type": DEED_REL, "method": "acris-deed"},
             {"a": 2, "b": 4, "rel_type": DEED_REL, "method": "acris-deed-linked-successor"}]
    out = to_entity_relationships(edges, partition)
    assert len(out["relationships"]) == 1
    r = out["relationships"][0]
    assert (r["a"], r["b"], r["rel_type"]) == ("RE-1", "RE-3", DEED_REL)
    assert r["edges"] == 2
    assert r["methods"] == {"acris-deed": 1, "acris-deed-linked-successor": 1}   # held vs linked kept distinct


def test_intra_entity_edges_are_dropped():
    partition = {1: "RE-1", 2: "RE-1"}                         # both endpoints one entity
    out = to_entity_relationships([{"a": 1, "b": 2, "rel_type": DEED_REL}], partition)
    assert out["relationships"] == [] and out["self_dropped"] == 1


def test_singletons_default_to_own_entity():
    # nodes absent from the partition are their own singleton entities (RE-<nodeid>).
    out = to_entity_relationships([{"a": 7, "b": 9, "rel_type": LLC_REL, "method": "registered-llc"}], {})
    assert len(out["relationships"]) == 1
    assert (out["relationships"][0]["a"], out["relationships"][0]["b"]) == ("RE-7", "RE-9")


def test_relationship_types_are_kept_separate():
    partition = {1: "RE-1", 2: "RE-2"}
    edges = [{"a": 1, "b": 2, "rel_type": DEED_REL, "method": "acris-deed"},
             {"a": 1, "b": 2, "rel_type": LLC_REL, "method": "registered-llc"}]
    out = to_entity_relationships(edges, partition)
    assert {r["rel_type"] for r in out["relationships"]} == {DEED_REL, LLC_REL}
    assert len(out["relationships"]) == 2                      # same pair, two typed relationships
