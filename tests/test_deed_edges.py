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
    assert "partytype = 2" in sql and "HDFC" in sql    # institutional-grantee exclusion


def test_hub_nodes_drops_serial_co_investors():
    # node 1 is on 3 deeds, nodes 2/3/4 each on 1 -> with cap 2, only node 1 is a hub.
    groups = {"D1": {1, 2}, "D2": {1, 3}, "D3": {1, 4}}
    assert de._hub_nodes(groups, hub_cap=2) == {1}
    assert de._hub_nodes(groups, hub_cap=3) == set()   # nobody exceeds the cap


# --- linked-successor guard (branch B) ---------------------------------------------------------
def test_retained_keeps_held_and_restructured_drops_sales_and_strangers():
    # joint deed D, grantee G = LIBERTY. Four parcels, four fates:
    G = {de._norm("LIBERTY 162 HOLDINGS LLC")}
    latest = {
        # held: latest deed IS the joint deed
        "held":  ("D", {de._norm("SELLER")}, de._norm("LIBERTY 162 HOLDINGS LLC")),
        # restructured: latest grantor == G, successor is a shell (size 1)
        "restr": ("d_bbgt", G, de._norm("BBGT PROPERTY LLC")),
        # sale: latest grantor == G BUT successor is a big independent portfolio -> stale, drop
        "sold":  ("d_sale", G, de._norm("MEGA REALTY")),
        # stranger: latest grantor is someone else entirely -> drop
        "other": ("d_x", {de._norm("UNRELATED CORP")}, de._norm("UNRELATED CORP")),
    }
    succ = {de._norm("BBGT PROPERTY LLC"): 1, de._norm("MEGA REALTY"): 40}
    keep = de._retained("D", ["held", "restr", "sold", "other"], G, latest, succ, successor_max=3)
    assert set(keep) == {"held", "restr"}


def test_retained_needs_two_to_matter():
    G = {de._norm("G LLC")}
    latest = {"a": ("D", set(), de._norm("G LLC")), "b": ("later", G, de._norm("SHELL"))}
    # both retained (a held, b restructured into a shell) -> caller requires >=2; here exactly 2
    assert len(de._retained("D", ["a", "b"], G, latest, {de._norm("SHELL"): 1}, 3)) == 2


def test_joint_sql_carries_the_restructuring_scope():
    sql = de._JOINT_SQL.format(max_parcels=de.MAX_PARCELS)
    assert "partytype = 2" in sql                        # grantee of the joint purchase
    assert de.RESTRUCT_MIN_DATE in sql                   # recency floor on the joint deed
    assert "partytype = 1" in de._LATEST_SQL             # grantor of the successor deed (the chain)
