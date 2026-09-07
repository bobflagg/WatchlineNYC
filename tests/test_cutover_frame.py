"""Hermetic tests for the cutover-frame pure stratum builders (Option B)."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.eval.cutover_frame import (
    split_stratum, split_pairs, select_retained, retained_pairs)


def test_split_stratum_finds_only_split_groups():
    # OG-1 splits into RE-1 {1,2} and RE-3 {3}; OG-9 stays whole (one v2 entity).
    legacy = {1: "OG-1", 2: "OG-1", 3: "OG-1", 8: "OG-9", 9: "OG-9"}
    v2 = {1: "RE-1", 2: "RE-1", 3: "RE-3", 8: "RE-8", 9: "RE-8"}
    groups = split_stratum(legacy, v2)
    assert len(groups) == 1 and groups[0][0] == "OG-1"
    pairs = split_pairs(groups)
    assert len(pairs) == 1
    p = pairs[0]
    assert p["decision_type"] == "split" and p["v2_decision"] == "DIFFERENT"
    assert {p["a_rid"], p["b_rid"]} == {"RE-1", "RE-3"}


def test_split_pairs_capped_per_group():
    legacy = {i: "OG-1" for i in range(6)}
    v2 = {0: "RE-0", 1: "RE-1", 2: "RE-2", 3: "RE-3", 4: "RE-4", 5: "RE-5"}  # 6 sub-entities
    pairs = split_pairs(split_stratum(legacy, v2), max_pairs=3)
    assert len(pairs) == 3                                   # capped


def test_select_retained_forces_curated_large_common():
    ent_members = {"RE-1": [1, 2], "RE-2": [3, 4], "RE-3": [5, 6], "RE-4": [7, 8]}
    ent_meta = {"RE-1": {"member_count": 2, "deterministic_core": True},    # curated -> forced
                "RE-2": {"member_count": 9, "deterministic_core": False},   # large -> forced
                "RE-3": {"member_count": 2, "deterministic_core": False},   # common surname -> forced
                "RE-4": {"member_count": 2, "deterministic_core": False}}   # eligible for random
    ent_surname = {"RE-1": "AAA", "RE-2": "BBB", "RE-3": "SMITH", "RE-4": "CCC"}
    surname_freq = {"SMITH": 30, "AAA": 1, "BBB": 1, "CCC": 1}
    sel = select_retained(ent_members, ent_meta, ent_surname, surname_freq, n_random=0, common_min=15)
    assert set(sel) == {"RE-1", "RE-2", "RE-3"}             # forced three; RE-4 not (n_random=0)


def test_retained_pairs_within_entity_deterministic():
    pairs = retained_pairs(["RE-1"], {"RE-1": [5, 2, 9]})
    assert pairs == [{"stratum": "S2_retained_merge", "decision_type": "merge", "v2_decision": "SAME",
                      "resolution_id": "RE-1", "a_nodes": [2], "b_nodes": [5]}]   # two lowest nodeids


def test_permutation_invariance_of_selection():
    ent_members = {f"RE-{i}": [i, i + 100] for i in range(50)}
    ent_meta = {r: {"member_count": 2, "deterministic_core": False} for r in ent_members}
    ent_surname = {r: "X" for r in ent_members}
    freq = {"X": 1}
    a = select_retained(dict(ent_members), ent_meta, ent_surname, freq, seed=42, n_random=10)
    b = select_retained(dict(ent_members), ent_meta, ent_surname, freq, seed=42, n_random=10)
    assert a == b                                           # deterministic given seed
