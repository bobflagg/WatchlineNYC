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


def test_s1_cross_boundary_registered_llc_is_same_llc_review():
    # CUT-0029: co-principals of ONE operation split across nodes — pervasive overlap (multiple shared owning
    # LLCs) keeps it promoted for review. Note the shortestPath is 2 hops; the cross-boundary flag catches it.
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["splink-fellegi-sunter", "registered-llc"], "path_hops": 2,
                    "cross_registered_llc": True, "shared_office": False,
                    "shared_llc_owners": ["FRONTIER REALTY, LLC", "212-214 REALTY CO. LLC",
                                          "EAST WEST RENOVATING CO, LLC"]})
    assert out["bucket"] == "same_llc_split" and out["priority"] == 2   # >1 shared LLC -> not a JV
    assert out["flags"] == ["same-registered-llc-direct"]


def test_s1_single_small_llc_no_office_is_jv_routine():
    # A single small owner LLC (deg<=4) with NO shared office across two separate portfolios = a two-party JV
    # (common control, not identity) -> demoted to routine.
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc"], "path_hops": 1, "cross_registered_llc": True,
                    "shared_office": False, "shared_llc_owners": ["BATHGATE LLC"],
                    "shared_owner_degrees": {"BATHGATE LLC": 2}})
    assert out["bucket"] == "routine_blob_split" and out["flags"] == ["same-llc-jv-no-office"]


def test_s1_single_small_llc_with_shared_office_stays_promoted():
    # Same single small LLC but WITH a shared office = one operation, not a JV -> stays same_llc_split.
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc"], "path_hops": 1, "cross_registered_llc": True,
                    "shared_office": True, "shared_llc_owners": ["405-409 GV LLC"],
                    "shared_owner_degrees": {"405-409 GV LLC": 2}})
    assert out["bucket"] == "same_llc_split"


def test_s1_single_large_holder_no_office_stays_promoted():
    # A single shared owner above the JV degree cap (a bigger holder / servicer, e.g. OLIT trust) is NOT an
    # isolated small JV -> stays promoted for the reviewer to judge, even without a shared office.
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc"], "path_hops": 1, "cross_registered_llc": True,
                    "shared_office": False, "shared_llc_owners": ["MTEK NYC LLC"],
                    "shared_owner_degrees": {"MTEK NYC LLC": 11}})
    assert out["bucket"] == "same_llc_split"


def test_s1_eponymous_small_llc_no_office_is_reclaimed():
    # CUT-0052: shared owner "PARLANTI GROUP LLC" carries anchor A's surname -> it's Parlanti's own entity, an
    # identity link, NOT a stranger JV. Reclaimed from the JV demotion (kept as same_llc_split), even though a
    # single small LLC with no shared office would otherwise be demoted.
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "a_name": "JOSEPHINE PARLANTI", "b_name": "MARIA SANTOMAURO",
                    "path_methods": ["registered-llc"], "path_hops": 1, "cross_registered_llc": True,
                    "shared_office": False, "shared_llc_owners": ["PARLANTI GROUP LLC"],
                    "shared_owner_degrees": {"PARLANTI GROUP LLC": 2}})
    assert out["bucket"] == "same_llc_split" and "eponymous-owner" in out["flags"]


def test_s1_noneponymous_small_llc_no_office_still_jv():
    # Guard: a same-length owner name that does NOT carry either surname is still a JV (no false reclaim).
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "a_name": "JOSH HUBI", "b_name": "SEFIK GUNES",
                    "path_methods": ["registered-llc"], "path_hops": 1, "cross_registered_llc": True,
                    "shared_office": False, "shared_llc_owners": ["SHALOM ALEICHEM LLC"],
                    "shared_owner_degrees": {"SHALOM ALEICHEM LLC": 3}})
    assert out["bucket"] == "routine_blob_split" and out["flags"] == ["same-llc-jv-no-office"]


def test_s1_placeholder_only_owner_is_noise():
    # A DOF placeholder ("UNAVAILABLE OWNER") is not a real shared owner -> routine (same-llc-noise).
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc"], "path_hops": 1, "cross_registered_llc": True,
                    "shared_office": False, "shared_llc_owners": ["UNAVAILABLE OWNER"]})
    assert out["bucket"] == "routine_blob_split" and out["flags"] == ["same-llc-noise"]


def test_s1_transitive_llc_chain_without_cross_edge_stays_routine():
    # OG-110 blob: registered-llc on the path but NO direct A<->B edge (chained through a third entity) —
    # cross_registered_llc is False, so it correctly stays routine_blob_split.
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc", "registered-llc"], "path_hops": 2,
                    "cross_registered_llc": False})
    assert out["bucket"] == "routine_blob_split" and out["priority"] == 0


def test_s1_cross_boundary_llc_same_surname_still_name_similar():
    # Same/typo surname takes precedence — a same-surname pair is name_similar_split even with a cross LLC edge.
    out = classify({"stratum": "S1_split", "surname_relation": "same",
                    "path_methods": ["registered-llc"], "path_hops": 1, "cross_registered_llc": True})
    assert out["bucket"] == "name_similar_split"


def test_s1_cross_boundary_llc_financier_only_owner_is_dropped():
    # CUT-0002/0003: the only shared registered owner is a City-finance vehicle (NYC HDC) — co-occurrence
    # noise, not a private same-owner. Dropped to routine with the financier-noise flag (the F5 discount).
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc"], "path_hops": 1,
                    "cross_registered_llc": True, "shared_llc_owners": ["NYC HOUSING DEVELOPMENT CORP."]})
    assert out["bucket"] == "routine_blob_split" and out["flags"] == ["same-llc-noise"]


def test_s1_cross_boundary_llc_shared_hdfc_is_kept():
    # CUT-0001: a shared HDFC is a genuine nonprofit owner (F5 keeps it substantive), NOT a financier — stays
    # promoted for review even though its name contains HOUSING DEVELOPMENT (FUND, not the HDC finance agency).
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc"], "path_hops": 1, "cross_registered_llc": True,
                    "shared_llc_owners": ["BROOKLYN NEIGHBORHOOD HOUSING DEV FUND CORPORATION"]})
    assert out["bucket"] == "same_llc_split"


def test_s1_cross_boundary_llc_mixed_owners_is_kept():
    # A private LLC shared alongside a financier owner still flags — not EVERY shared owner is noise.
    out = classify({"stratum": "S1_split", "surname_relation": "different",
                    "path_methods": ["registered-llc"], "path_hops": 1, "cross_registered_llc": True,
                    "shared_llc_owners": ["CITY OF NEW YORK", "212-214 REALTY CO. LLC"]})
    assert out["bucket"] == "same_llc_split"


def test_financier_classifier_hdc_yes_hdfc_no_equityfund_yes():
    from watchline.discovery.ingest.portfolio.eval.frame_qa import _financier
    assert _financier("NYC HOUSING DEVELOPMENT CORP.") is True
    assert _financier("NEW YORK EQUITY FUND 2005 LLC") is True
    assert _financier("BROOKLYN NEIGHBORHOOD HOUSING DEV FUND CORPORATION") is False   # HDFC, not HDC
    assert _financier("212-214 REALTY CO. LLC") is False
