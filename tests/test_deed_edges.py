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
    sql = de._deed_sql(de.DEFAULT_MIN_DATE, de.MAX_PARCELS)
    assert "DEED" in sql                               # doctype scope
    assert de.DEFAULT_MIN_DATE in sql                  # recent-only date filter
    assert f"<= {de.MAX_PARCELS}" in sql               # parcel cap (mega-deed exclusion)
    assert "partytype = 2" in sql and "HDFC" in sql    # institutional-grantee exclusion
