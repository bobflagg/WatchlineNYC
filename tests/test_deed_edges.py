"""Hermetic tests for the ACRIS-deed edge builder (pure mapper + SQL shape).

Gated on the ingest extra (pandas/splink); skips cleanly without it.
"""
from __future__ import annotations

import pytest

pytest.importorskip("splink")
import pandas as pd

from watchline.discovery.ingest.portfolio import deed_edges as de


def _deeds(rows):
    return pd.DataFrame(rows, columns=["doc", "bbls"])


def _lwc(rows):
    return pd.DataFrame(rows, columns=["nodeid", "bbls"])


def test_maps_co_conveyed_buildings_to_their_landlord_nodes():
    # One deed conveying bbls a & b -> connect their landlord nodes (1 and 2).
    deeds = _deeds([("DOC1", ["a", "b"])])
    lwc = _lwc([(1, ["a"]), (2, ["b"]), (3, ["z"])])   # node 3 not on the deed
    assert de._groups_from(deeds, lwc) == {"DOC1": {1, 2}}


def test_deed_needs_two_distinct_nodes():
    # Both co-conveyed buildings resolve to the SAME landlord -> nothing to link.
    deeds = _deeds([("DOC1", ["a", "b"])])
    lwc = _lwc([(7, ["a", "b"])])
    assert de._groups_from(deeds, lwc) == {}


def test_null_bbls_do_not_crash():
    deeds = _deeds([("DOC1", ["a", "missing"])])
    lwc = _lwc([(1, ["a"]), (2, None)])
    assert de._groups_from(deeds, lwc) == {}          # only one node covers DOC1


def test_deed_sql_carries_the_scope_filters():
    sql = de._deed_sql(de.MAX_PARCELS)
    assert "DEED" in sql                               # doctype scope
    assert "DISTINCT ON (btrim(l.bbl))" in sql         # staleness guard: each building's LATEST deed
    assert "CURRENT_DATE" in sql                       # ignore future-dated bad deeds
    assert f"<= {de.MAX_PARCELS}" in sql               # parcel cap (mega-deed exclusion)
    assert "partytype IN (1, 2)" in sql and "HDFC" in sql   # public grantor/grantee exclusion (both sides)


def test_deed_sql_carries_the_held_since_precision_guard():
    # Held-since precision fix (specs/deed-gate-review.md): a shared latest deed must NOT prove
    # co-ownership when it is a public/affordable-housing conveyance or a co-op/condo building's deed
    # -- those fuse unrelated co-beneficiaries / co-shareholders, not co-owners.
    sql = de._deed_sql(de.MAX_PARCELS)
    # (1) public / affordable-housing GRANTOR OR GRANTEE (both party sides; broadened keyword list)
    assert "partytype IN (1, 2)" in sql
    for kw in ("HPD", "HOUSING PRESERVATION", "NEIGHBORHOOD PARTNERSHIP", "H.E.L.P"):
        assert kw in sql
    # (2) co-op/condo building-level exclusion: DOF/PLUTO class OR HPD contactdescription plurality,
    # dropping deeds whose parcels are MAJORITY co-op/condo (owner_groups.py's >50% convention).
    assert "pluto_latest" in sql and "bldgclass" in sql
    assert "'C6'" in sql and "LIKE 'R" in sql          # co-op classes (C6/C8/D0/D4) + condo (R*)
    assert "contactdescription" in sql                 # HPD co-op/condo plurality (coop_condo.py rule)
    assert "<= 0.5" in sql                              # drop deeds that are MAJORITY co-op/condo
    # the linked-successor $0 branch is untouched by this guard
    assert de._INST == ("HDFC", "HOUSING DEVELOPMENT FUND", "HOUSING AUTHORITY", "NYCHA",
                        "CITY OF NEW YORK")


def test_hub_nodes_drops_serial_co_investors():
    # node 1 is on 3 deeds, nodes 2/3/4 each on 1 -> with cap 2, only node 1 is a hub.
    groups = {"D1": {1, 2}, "D2": {1, 3}, "D3": {1, 4}}
    assert de._hub_nodes(groups, hub_cap=2) == {1}
    assert de._hub_nodes(groups, hub_cap=3) == set()   # nobody exceeds the cap


# --- linked-successor guard (branch B) ---------------------------------------------------------
def test_retained_keeps_held_and_restructured_drops_sales_and_strangers():
    # joint deed D, grantee G = LIBERTY. Five parcels, five fates. latest tuple is now
    # (latest_doc, {grantor_norm}, successor_norm, docamount).
    G = {de._norm("LIBERTY 162 HOLDINGS LLC")}
    latest = {
        # held: latest deed IS the joint deed (docamount irrelevant on the held branch)
        "held":  ("D", {de._norm("SELLER")}, de._norm("LIBERTY 162 HOLDINGS LLC"), 5_000_000),
        # restructured: latest grantor == G, successor is a shell (size 1), NOMINAL consideration
        "restr": ("d_bbgt", G, de._norm("BBGT PROPERTY LLC"), 0),
        # sale: latest grantor == G BUT successor is a big independent portfolio -> stale, drop
        "sold":  ("d_sale", G, de._norm("MEGA REALTY"), 2_000_000),
        # priced-sale-to-a-shell: grantor == G and buyer is small (size 1) so it PASSES the
        # successor guard, but the $1.1M price is a market SALE -> the nominal gate drops it
        "psale": ("d_psale", G, de._norm("SMALL BUYER LLC"), 1_100_000),
        # stranger: latest grantor is someone else entirely -> drop
        "other": ("d_x", {de._norm("UNRELATED CORP")}, de._norm("UNRELATED CORP"), 0),
    }
    succ = {de._norm("BBGT PROPERTY LLC"): 1, de._norm("MEGA REALTY"): 40,
            de._norm("SMALL BUYER LLC"): 1}
    keep = de._retained("D", ["held", "restr", "sold", "psale", "other"], G, latest, succ,
                        successor_max=3)
    assert set(keep) == {"held", "restr"}


def test_retained_needs_two_to_matter():
    G = {de._norm("G LLC")}
    latest = {"a": ("D", set(), de._norm("G LLC"), 3_000_000),
              "b": ("later", G, de._norm("SHELL"), 0)}
    # both retained (a held, b restructured into a shell at nominal $) -> caller requires >=2
    assert len(de._retained("D", ["a", "b"], G, latest, {de._norm("SHELL"): 1}, 3)) == 2


def test_retained_block3498_arms_length_sales_not_remerged():
    # REGRESSION (block 3498 / P0133, specs/eval-protocol.md §3.2): AMJAD ALI deeded an 8-lot
    # assemblage (lots 19-26) to LELAND PROPERTY LLC on joint deed 2013120600683001. In 2022-2025
    # four lots were SOLD arms-length (~$1.1M). Each sale deed's grantor is LELAND and each buyer
    # owns <= SUCCESSOR_MAX(3) buildings, so all four PASS the successor guard -- only the
    # nominal-consideration gate keeps them from being falsely re-merged into LELAND's clique.
    JOINT = "2013120600683001"
    G = {de._norm("LELAND PROPERTY LLC")}
    held = (JOINT, {de._norm("AMJAD ALI")}, de._norm("LELAND PROPERTY LLC"), 0)  # latest == joint
    latest = {
        "2034980021": held, "2034980023": held, "2034980025": held, "2034980026": held,
        "2034980020": ("d20", G, de._norm("SONG, GONG LIANG"), 1_100_000),
        "2034980022": ("2025111100447002", G, de._norm("NI, LONGCHENG"), 1_100_000),
        "2034980024": ("d24", G, de._norm("LIN'S DOUBLE WOOD LLC"), 1_150_000),
        "2034980019": ("d19", G, de._norm("427 SOUNDVIEW LLC"), 900_000),
    }
    succ = {de._norm("SONG, GONG LIANG"): 1, de._norm("NI, LONGCHENG"): 1,
            de._norm("LIN'S DOUBLE WOOD LLC"): 2, de._norm("427 SOUNDVIEW LLC"): 3}
    bbls = ["2034980019", "2034980020", "2034980021", "2034980022",
            "2034980023", "2034980024", "2034980025", "2034980026"]
    keep = de._retained(JOINT, bbls, G, latest, succ, successor_max=3)
    # only the still-held lots survive; the four ~$1.1M sales are dropped
    assert set(keep) == {"2034980021", "2034980023", "2034980025", "2034980026"}

    # Held behavior preserved: a genuine $0 re-deed of lot 20 into a controlled shell IS re-included.
    latest["2034980020"] = ("d20", G, de._norm("LELAND 20 LLC"), 0)
    succ[de._norm("LELAND 20 LLC")] = 1
    keep2 = de._retained(JOINT, bbls, G, latest, succ, successor_max=3)
    assert "2034980020" in set(keep2)


def test_is_nominal_thresholds():
    # nominal (restructuring) vs market sale, and the None/unparseable-safe default
    assert de._is_nominal(0) and de._is_nominal(10) and de._is_nominal(de.NOMINAL_MAX)
    assert not de._is_nominal(de.NOMINAL_MAX + 1)
    assert not de._is_nominal(1_100_000)
    assert not de._is_nominal(None)            # absent price -> not re-merged (precision-safe)


def test_joint_sql_carries_the_restructuring_scope():
    sql = de._JOINT_SQL.format(max_parcels=de.MAX_PARCELS)
    assert "partytype = 2" in sql                        # grantee of the joint purchase
    assert de.RESTRUCT_MIN_DATE in sql                   # recency floor on the joint deed
    assert "partytype = 1" in de._LATEST_SQL             # grantor of the successor deed (the chain)
    assert "docamount" in de._LATEST_SQL                 # consideration threaded for the nominal gate


def test_joint_sql_mirrors_the_held_since_guard():
    # Branch B (_JOINT_SQL / _restructured_groups) ALSO emits held-since parcels — _retained keeps a
    # parcel when `ldoc == doc` (the joint deed is its latest). So the held-since public/co-op guard
    # MUST be mirrored here, or a public/co-op held deed dropped from _deed_sql (branch A) re-enters
    # through this path for 2005+ joint deeds. Assert the guard is present AND literally shared.
    sql = de._JOINT_SQL.format(max_parcels=de.MAX_PARCELS)
    assert "partytype IN (1, 2)" in sql                        # public grantor OR grantee (both sides)
    for kw in ("HPD", "HOUSING PRESERVATION", "NEIGHBORHOOD PARTNERSHIP", "H.E.L.P"):
        assert kw in sql
    assert "coop AS" in sql and "contactdescription" in sql    # co-op/condo majority exclusion
    assert de._PUBLIC_LIKE in sql and de._COOP_CTE in sql       # single source of truth, shared w/ branch A
