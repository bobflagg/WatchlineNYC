"""Hermetic tests for the C3 constrained-clustering resolver (ResolvedEntityV2 core, Option B Phase 2).

Covers each hard constraint, the deterministic-conflict → adjudication path, probabilistic → dropped,
singletons, the allowlist (no deed/unknown methods), and the required permutation-invariance property.
"""
from __future__ import annotations

import random

import pytest

from watchline.discovery.ingest.portfolio.resolved_entity import resolve, entity_type, surname


def _ref(i, entity_type=None, surname=None, identifier=None):
    return {"id": i, "entity_type": entity_type, "surname": surname, "identifier": identifier}


def test_merges_transitively_and_ids_by_min_member():
    refs = [_ref("a"), _ref("b"), _ref("c")]
    edges = [{"a": "a", "b": "b", "method": "curated-same-owner"},
             {"a": "b", "b": "c", "method": "registered-llc-id"}]
    out = resolve(refs, edges)
    assert out["partition"] == {"a": "RE-a", "b": "RE-a", "c": "RE-a"}
    assert out["deterministic_core"]["RE-a"] is True        # formed via deterministic edges


def test_singletons_included_with_own_resolution_id():
    out = resolve([_ref("x"), _ref("y")], [])
    assert out["partition"] == {"x": "RE-x", "y": "RE-y"}
    assert out["deterministic_core"] == {"RE-x": False, "RE-y": False}   # no edge ⇒ no durable core


def test_entity_type_cannot_link_blocks_probabilistic_merge():
    refs = [_ref("p", entity_type="person"), _ref("e", entity_type="entity")]
    edges = [{"a": "p", "b": "e", "method": "splink-fellegi-sunter", "score": 0.99}]
    out = resolve(refs, edges)
    assert out["partition"]["p"] != out["partition"]["e"]              # not merged
    assert out["dropped"] == [{"a": "p", "b": "e", "method": "splink-fellegi-sunter",
                               "conflict": "entity_type"}]
    assert out["adjudication"] == []                                    # probabilistic ⇒ dropped, not adjudicated


def test_surname_disagreement_blocks_persons():
    refs = [_ref("s", entity_type="person", surname="SMITH"),
            _ref("j", entity_type="person", surname="JONES")]
    out = resolve(refs, [{"a": "s", "b": "j", "method": "registered-llc-name"}])
    assert out["partition"]["s"] != out["partition"]["j"]
    assert out["dropped"][0]["conflict"] == "surname"


def test_conflicting_identifier_blocks_and_deterministic_goes_to_adjudication():
    # two registered-llc-id edges imply merging A,B,C, but A and C carry different DOS ids.
    refs = [_ref("A", identifier="DOS-1"), _ref("B"), _ref("C", identifier="DOS-2")]
    edges = [{"a": "A", "b": "B", "method": "registered-llc-id"},
             {"a": "B", "b": "C", "method": "registered-llc-id"}]
    out = resolve(refs, edges)
    # A-B merges first (canonical order by endpoints); B-C then conflicts on identifier.
    assert out["partition"]["A"] == out["partition"]["B"]
    assert out["partition"]["C"] != out["partition"]["A"]
    assert out["adjudication"] == [{"a": "B", "b": "C", "method": "registered-llc-id",
                                    "conflict": "identifier"}]
    assert out["dropped"] == []


def test_unknown_value_is_permissive():
    # a typed person merges with an untyped reference (unknown attrs don't constrain).
    refs = [_ref("p", entity_type="person", surname="LEE"), _ref("u")]
    out = resolve(refs, [{"a": "p", "b": "u", "method": "curated-same-owner"}])
    assert out["partition"]["p"] == out["partition"]["u"]


def test_deed_and_unknown_methods_are_rejected():
    refs = [_ref("a"), _ref("b")]
    for bad in ("acris-deed", "acris-deed-linked-successor", "connected-by-address", "whatever"):
        with pytest.raises(ValueError):
            resolve(refs, [{"a": "a", "b": "b", "method": bad}])


def test_deterministic_edge_not_preempted_by_probabilistic():
    # curated says A=C; a fellegi edge A=B would pull in B(conflicting surname). Precedence processes
    # curated first, so A=C forms cleanly and the fellegi edge is the one that gets dropped.
    refs = [_ref("A", entity_type="person", surname="NG"),
            _ref("C", entity_type="person", surname="NG"),
            _ref("B", entity_type="person", surname="OTHER")]
    edges = [{"a": "A", "b": "C", "method": "curated-same-owner"},
             {"a": "A", "b": "B", "method": "splink-fellegi-sunter", "score": 0.99}]
    out = resolve(refs, edges)
    assert out["partition"]["A"] == out["partition"]["C"]
    assert out["partition"]["B"] != out["partition"]["A"]
    assert out["adjudication"] == []                        # no deterministic edge was blocked
    assert out["dropped"][0]["method"] == "splink-fellegi-sunter"


def test_entity_type_and_surname_classification():
    assert entity_type("STEVEN CROMAN") == "person"
    assert entity_type("BEACH 99TH LLC") == "entity"
    assert entity_type("2432 GRAND CONCOURSE REALTY CORP") == "entity"
    assert entity_type("NEIGHBORHOOD PARTNERSHIP HOUSING DEVELOPMENT FUND") == "institution"
    assert entity_type("COLUMBIA UNIVERSITY") == "institution"
    assert entity_type(None) is None and entity_type("  ") is None
    # surname only for persons
    assert surname("STEVEN CROMAN", "person") == "CROMAN"
    assert surname("BEACH 99TH LLC", "entity") is None
    assert surname(None, "person") is None


def test_permutation_invariance():
    refs = [_ref(c, entity_type="person", surname={"a": "X", "b": "X", "c": "Y", "d": "X"}[c])
            for c in ("a", "b", "c", "d")]
    edges = [
        {"a": "a", "b": "b", "method": "registered-llc-name", "score": 0.9},
        {"a": "b", "b": "d", "method": "curated-same-owner"},
        {"a": "b", "b": "c", "method": "splink-fellegi-sunter", "score": 0.8},  # X vs Y surname → blocked
        {"a": "a", "b": "d", "method": "splink-fellegi-sunter", "score": 0.7},
    ]
    base = resolve(refs, edges)
    for seed in range(20):
        r = random.Random(seed)
        e2 = edges[:]; r.shuffle(e2)
        refs2 = refs[:]; r.shuffle(refs2)
        out = resolve(refs2, e2)
        assert out["partition"] == base["partition"]
        # adjudication/dropped identical as sets (order-independent)
        key = lambda d: (d["a"], d["b"], d["method"], d["conflict"])
        assert {key(x) for x in out["dropped"]} == {key(x) for x in base["dropped"]}
        assert {key(x) for x in out["adjudication"]} == {key(x) for x in base["adjudication"]}
