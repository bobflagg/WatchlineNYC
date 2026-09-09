"""Hermetic tests for the pure core of the cutover frame-QA triage (classification only; no graph)."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.eval.frame_qa import surname_relation, classify


def test_surname_relation_same_typo_different():
    assert surname_relation("SAM WURTZBERGER", "SAM WURTZBERGER") == "same"
    assert surname_relation("SAM WURTZBERGER", "SAM WURZBERGER") == "typo"      # one-letter drop
    assert surname_relation("LARRY HIRSCHFIELD", "LARRY HIRSCFIELD") == "typo"
    assert surname_relation("ERIC MOORE", "SHIMON SABAH") == "different"
    assert surname_relation("ALEX LASZLO", "EPHRAIM FRUCHTHANDLER") == "different"


def test_redundant_nonidentity_edge_is_NOT_a_breach():
    # A registered-llc edge co-existing with an identity edge is redundant, not the binding mechanism.
    out = classify({"stratum": "S2_retained_merge", "surname_relation": "same", "entity_member_count": 2,
                    "entity_surname_count": 1, "entity_methods": ["splink-fellegi-sunter", "registered-llc"]})
    assert out["bucket"] == "routine_merge" and out["flags"] == []


def test_s2_entity_with_no_identity_edge_is_red_flag():
    # The real canary: a multi-member entity held together ONLY by a non-identity edge (invariant breach).
    out = classify({"stratum": "S2_retained_merge", "surname_relation": "same", "entity_member_count": 2,
                    "entity_surname_count": 1, "entity_methods": ["registered-llc"]})
    assert out["bucket"] == "RED_FLAG_MERGE" and out["priority"] == 3
    assert out["flags"] == ["merge-not-identity-connected:registered-llc"]


def test_s2_merge_dissimilar_names_is_review_not_breach():
    out = classify({"stratum": "S2_retained_merge", "surname_relation": "different", "entity_member_count": 2,
                    "entity_surname_count": 2, "entity_methods": ["splink-fellegi-sunter"]})
    assert out["bucket"] == "review_merge" and out["priority"] == 2
    assert "merge-dissimilar-anchor-names" in out["flags"] and "merge-spans-surnames" in out["flags"]


def test_s2_common_surname_alone_is_NOT_flagged():
    # Common surname is the norm in this population (median freq ~268), so a small merge is not flagged
    # on common-surname alone — only member count discriminates.
    out = classify({"stratum": "S2_retained_merge", "surname_relation": "same", "entity_member_count": 3,
                    "entity_surname_count": 1, "entity_methods": ["splink-fellegi-sunter"],
                    "common_surname": True, "surname_freq": 268})
    assert out["bucket"] == "routine_merge" and out["flags"] == []


def test_s2_large_merge_is_fm_candidate():
    out = classify({"stratum": "S2_retained_merge", "surname_relation": "same", "entity_member_count": 9,
                    "entity_surname_count": 1, "entity_methods": ["splink-fellegi-sunter"],
                    "common_surname": True, "surname_freq": 500})
    assert out["bucket"] == "review_merge" and out["priority"] == 2
    assert any(fl.startswith("large-merge") for fl in out["flags"])
    assert "common-surname:500" in out["flags"][0]           # common-surname rides along as context


def test_curated_common_surname_merge_is_exempt():
    # Curated (audited) merges are exempt from the FM-candidate flags even if large/common.
    out = classify({"stratum": "S2_retained_merge", "surname_relation": "same", "entity_member_count": 12,
                    "entity_surname_count": 1, "entity_methods": ["splink-fellegi-sunter", "curated-same-owner"],
                    "common_surname": True, "surname_freq": 300})
    assert out["bucket"] == "routine_merge" and out["flags"] == []


def test_s2_clean_merge_is_routine():
    out = classify({"stratum": "S2_retained_merge", "surname_relation": "same", "entity_member_count": 2,
                    "entity_surname_count": 1, "entity_methods": ["splink-fellegi-sunter"]})
    assert out["bucket"] == "routine_merge" and out["flags"] == []


def test_curated_multi_surname_merge_not_flagged_for_surnames():
    # curated seeds may span surnames by design -> the surname flag must not fire when curated is present.
    out = classify({"stratum": "S2_retained_merge", "surname_relation": "different", "entity_member_count": 3,
                    "entity_surname_count": 3, "entity_methods": ["curated-same-owner"]})
    assert "merge-spans-surnames" not in out["flags"]        # curated present -> surname span allowed
    assert out["bucket"] == "review_merge"                   # still worth a look via dissimilar anchor names


def test_s1_name_similar_split_is_priority_2():
    out = classify({"stratum": "S1_split", "surname_relation": "typo",
                    "path_methods": ["registered-llc"], "path_hops": 2})
    assert out["bucket"] == "name_similar_split" and out["priority"] == 2
    assert out["flags"] == ["split-of-typo-surname"]


def test_s1_relationship_transitive_split_is_routine():
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc", "acris-deed"], "path_hops": 2})
    assert out["bucket"] == "routine_blob_split" and out["priority"] == 0
    assert out["flags"] == ["transitive-bridge"]


def test_s1_all_identity_path_but_split_is_red_flag():
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["splink-fellegi-sunter"], "path_hops": 1})
    assert out["bucket"] == "RED_FLAG_SPLIT" and out["priority"] == 3
    assert out["flags"] == ["direct-identity-path-but-split"]


def test_s1_direct_registered_llc_split_is_same_llc_review():
    # CUT-0029: dissimilar-surnamed co-principals of ONE owning LLC, joined by a DIRECT registered-llc edge —
    # a likely SAME false-split promoted out of routine_blob_split for review.
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc"], "path_hops": 1})
    assert out["bucket"] == "same_llc_split" and out["priority"] == 2
    assert out["flags"] == ["same-registered-llc-direct"]


def test_s1_transitive_registered_llc_stays_routine():
    # A MULTI-hop registered-llc path is transitive over-connection (OG-110 blob), NOT a same-LLC pair.
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc"], "path_hops": 2})
    assert out["bucket"] == "routine_blob_split" and out["priority"] == 0


def test_s1_direct_deed_edge_does_not_trigger_llc_override():
    # A 1-hop deed edge is co-conveyance (possible partition/co-investment), NOT same-registered-owner —
    # it must NOT be promoted by the same-LLC override; it stays routine.
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["acris-deed"], "path_hops": 1})
    assert out["bucket"] == "routine_blob_split"


def test_s1_direct_registered_llc_same_surname_still_name_similar():
    # Same/typo surname takes precedence — a same-surname direct-LLC split is name_similar_split, not same_llc.
    out = classify({"stratum": "S1_split", "surname_relation": "same",
                    "path_methods": ["registered-llc"], "path_hops": 1})
    assert out["bucket"] == "name_similar_split"
