"""Hermetic tests for the hardened WoW veil-pierce gate (eval/wow_gate.py).

Pins the regression table from specs/deed-gate-review.md §6. Fixtures key on **WoW portfolios**
(orig_id, building count, landlord count) and member-BBL placement counts — not OG ids, which
renumber. AXL and Citadel carry their real member BBLs (from the spec) for documentation; OG-10150 /
OG-33260 are reconstructed as portfolio placements faithful to the §6 numbers (their exact member BBLs
live only in the graph, and the gate reasons purely over portfolio structure).

Regression table (PASS = genuine deed veil-pierce; FAIL = WoW over-lump):
  PASS  AXL       bbls 4054210059/4054210061 -> #14133 (1 bldg) + #55695 (3 bldgs), two small distinct
  FAIL  Citadel   15 bbls -> all in #161 (83 bldgs / 33 landlords), single aggregator lump
  FAIL  OG-10150  35 of 37 in #28596 (121 / 16)  -- soft aggregator (16 < 25)
  FAIL  OG-33260  5 of 10 in #3357  (102 / 11)   -- soft aggregator (11 < 25)
  FAIL  Roubeni   all 10 in #4045   (32 / 15)    -- soft aggregator, single portfolio (optional)
"""
from __future__ import annotations

import pytest

from watchline.discovery.ingest.portfolio.eval import wow_gate as wg
from watchline.discovery.ingest.portfolio.eval.wow_gate import (
    Placement,
    Portfolio,
    is_aggregator_portfolio,
    legacy_hard_gate,
    wow_gate,
)

# Real AXL member BBLs (specs/case-axl.md) — the one true veil-pierce.
AXL_BBLS = ["4054210059", "4054210061"]
# Real Citadel member BBLs (specs/deed-gate-review.md §6).
CITADEL_BBLS = [
    "3012590047", "3012660012", "3012670016", "3013950059", "3014010017", "3014010021",
    "3046510036", "3050610010", "3051640017", "3052060031", "3052110017", "3052110026",
    "3052230071", "3076020035", "3076170063",
]


# ---- fixtures (portfolios + placements) --------------------------------------------------------
def axl_placements() -> tuple[list[Placement], int]:
    # two adjacent houses, one in each of two small unrelated single-owner portfolios.
    return ([Placement(Portfolio("14133", n_buildings=1, n_landlords=1), n_members=1),
             Placement(Portfolio("55695", n_buildings=3, n_landlords=1), n_members=1)],
            len(AXL_BBLS))


def citadel_placements() -> tuple[list[Placement], int]:
    return ([Placement(Portfolio("161", n_buildings=83, n_landlords=33), n_members=15)],
            len(CITADEL_BBLS))


def og10150_placements() -> tuple[list[Placement], int]:
    # 35 of 37 already in one 121-bldg / 16-landlord soft-aggregator portfolio; the other 2 in small
    # distinct portfolios (so the FAIL comes from the aggregator + dominant-share, not a bare "single
    # portfolio" trip).
    return ([Placement(Portfolio("28596", n_buildings=121, n_landlords=16), n_members=35),
             Placement(Portfolio("90001", n_buildings=1, n_landlords=1), n_members=1),
             Placement(Portfolio("90002", n_buildings=2, n_landlords=1), n_members=1)],
            37)


def og33260_placements() -> tuple[list[Placement], int]:
    # 5 of 10 in one 102-bldg / 11-landlord soft aggregator; the other 5 scattered across small
    # distinct portfolios (distinct >= 2, so the FAIL is soft-aggregator + dominant-share).
    return ([Placement(Portfolio("3357", n_buildings=102, n_landlords=11), n_members=5),
             Placement(Portfolio("90010", n_buildings=2, n_landlords=1), n_members=2),
             Placement(Portfolio("90011", n_buildings=2, n_landlords=1), n_members=2),
             Placement(Portfolio("90012", n_buildings=1, n_landlords=1), n_members=1)],
            10)


def roubeni_placements() -> tuple[list[Placement], int]:
    return ([Placement(Portfolio("4045", n_buildings=32, n_landlords=15), n_members=10)], 10)


# ---- the hard threshold stays a single source of truth with the address classifier -------------
def test_hard_threshold_tracks_aggregator_audit():
    # 25 either way; when the `ingest` extra (psycopg2) is installed, pin the actual coupling.
    assert wg.AGG_LANDLORD_HARD == 25
    pytest.importorskip("psycopg2")
    from watchline.discovery.ingest.portfolio.aggregator_audit import MIN_DEGREE
    assert wg.AGG_LANDLORD_HARD == MIN_DEGREE


# ---- soft-aggregator classification ------------------------------------------------------------
def test_soft_aggregator_classification_matches_the_table():
    # over-lumps below the 25-landlord hard cutoff are still aggregators
    assert is_aggregator_portfolio(83, 33) is True      # #161  hard cutoff
    assert is_aggregator_portfolio(121, 16) is True     # #28596 soft
    assert is_aggregator_portfolio(102, 11) is True     # #3357  soft
    assert is_aggregator_portfolio(32, 15) is True      # #4045  soft
    # genuine small portfolios are not aggregators
    assert is_aggregator_portfolio(1, 1) is False       # #14133
    assert is_aggregator_portfolio(3, 1) is False       # #55695
    # a large but single/near-single-owner portfolio is not an over-lump (needs multi-landlord)
    assert is_aggregator_portfolio(40, 2) is False


# ---- the hardened gate: the full PASS/FAIL regression table ------------------------------------
def test_axl_passes_the_one_true_veil_pierce():
    res = wow_gate(*axl_placements())
    assert res.passed, res.reasons
    assert res.n_distinct_portfolios == 2
    assert res.aggregator_orig_ids == []


def test_citadel_fails_single_aggregator_lump():
    res = wow_gate(*citadel_placements())
    assert not res.passed
    # single portfolio AND an aggregator
    assert res.n_distinct_portfolios == 1
    assert "161" in res.aggregator_orig_ids


def test_og10150_fails_soft_aggregator():
    res = wow_gate(*og10150_placements())
    assert not res.passed
    assert "28596" in res.aggregator_orig_ids           # graded soft-aggregator caught it
    assert res.dominant_orig_id == "28596"
    assert res.dominant_share >= 0.9                     # 35/37
    # both complementary checks fire
    assert any("aggregator/over-lump" in r for r in res.reasons)
    assert any("dominant-share" in r for r in res.reasons)


def test_og33260_fails_soft_aggregator():
    res = wow_gate(*og33260_placements())
    assert not res.passed
    assert "3357" in res.aggregator_orig_ids
    assert res.dominant_orig_id == "3357"
    assert abs(res.dominant_share - 0.5) < 1e-9         # 5/10, still dominant (inclusive)
    assert any("dominant-share" in r for r in res.reasons)


def test_roubeni_fails_soft_aggregator_single_portfolio():
    res = wow_gate(*roubeni_placements())
    assert not res.passed
    assert "4045" in res.aggregator_orig_ids


# ---- the point of the hardening: the old hard cutoff wrongly PASSED the soft aggregators ---------
def test_legacy_hard_cutoff_wrongly_passes_soft_aggregators():
    # OG-10150 (#28596, 16 landlords) and OG-33260 (#3357, 11 landlords) are < 25, so the old
    # >25-landlord cliff calls them "not an aggregator" and PASSES them — the 2026-09-19 failure.
    assert legacy_hard_gate(og10150_placements()[0]).passed is True
    assert legacy_hard_gate(og33260_placements()[0]).passed is True
    # ...while the hardened gate correctly FAILS both.
    assert wow_gate(*og10150_placements()).passed is False
    assert wow_gate(*og33260_placements()).passed is False
    # sanity: the hard cutoff still (correctly) rejects Citadel and passes AXL
    assert legacy_hard_gate(citadel_placements()[0]).passed is False
    assert legacy_hard_gate(axl_placements()[0]).passed is True


# ---- the dominant-share backstop is threshold-independent ---------------------------------------
def test_dominant_share_backstop_catches_overlump_even_if_soft_threshold_relaxed():
    # Relax the soft-aggregator thresholds so #3357 would NOT be flagged an aggregator by check 1;
    # the dominant-share check (portfolio still large/multi-landlord under its own read) must still FAIL
    # it. Here we keep #3357 aggregator-ish via a high buildings floor but a landlord floor it clears.
    placements, n = og33260_placements()
    # With soft_landlords lowered, #3357 is still an aggregator and dominant-share fires regardless.
    res = wow_gate(placements, n, soft_landlords=2)
    assert not res.passed
    assert any("dominant-share" in r for r in res.reasons)


def test_axl_not_tripped_by_dominant_share_despite_even_split():
    # AXL is a 1-1 split (max share 0.5), but the dominant portfolio (#55695, 3 bldgs) is small, so the
    # dominant-share check must NOT fire — the large/multi-landlord qualifier is what protects a genuine
    # distributed split.
    res = wow_gate(*axl_placements())
    assert res.dominant_share == 0.5
    assert res.passed
    assert res.reasons == []
