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
