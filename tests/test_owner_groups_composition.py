"""Hermetic tests for the identity-vs-relationship composition classifier."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.owner_groups import classify_composition


def test_identity_only_group():
    # {1,2,3} all joined by identity edges, one deed edge inside -> one resolved entity.
    out = classify_composition([(1, 2), (2, 3)], [(1, 3)])
    assert out == {"OG-1": "identity"}


def test_pure_deed_group_is_veil_pierce():
    # {5,6} joined only by a deed edge, no identity edge -> deed_only (the intended veil-pierce).
    out = classify_composition([], [(5, 6)])
    assert out == {"OG-5": "deed_only"}


def test_deed_extends_one_identity_entity_stays_identity():
    # identity entity {1,2}; a deed edge pulls in singleton 3 -> still one identity entity involved.
    out = classify_composition([(1, 2)], [(2, 3)])
    assert out == {"OG-1": "identity"}


def test_deed_bridges_two_identity_entities():
    # two resolved entities {1,2} and {3,4}; a deed edge (2,3) fuses them -> the transitivity risk.
    out = classify_composition([(1, 2), (3, 4)], [(2, 3)])
    assert out == {"OG-1": "deed_bridged"}


def test_singletons_below_min_size_excluded():
    # a lone deed pair is size 2 (kept); nothing smaller survives.
    assert classify_composition([], [(9, 10)]) == {"OG-9": "deed_only"}
    assert classify_composition([(1, 2)], [], min_size=3) == {}


def test_gids_match_union_find_min_root():
    # gid keys on the min nodeid of the component, matching _union_groups.
    out = classify_composition([(7, 3), (3, 5)], [])
    assert set(out) == {"OG-3"}
