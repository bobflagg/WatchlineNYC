"""Hermetic tests for the same-registered-LLC edge builder.

Pure functions over synthetic frames — no DB. Gated on the ``ingest`` extra
(pandas/splink); skips cleanly without it. Run under ``uv run --extra ingest pytest``.
"""
from __future__ import annotations

import pytest

pytest.importorskip("splink")
import pandas as pd

from watchline.discovery.ingest.portfolio import llc_edges as le


def _owners(rows):
    return pd.DataFrame(rows, columns=["llc", "bbls"])


def _lwc(rows):
    return pd.DataFrame(rows, columns=["nodeid", "bbls"])


def test_groups_map_shared_llc_to_its_landlord_nodes():
    owners = _owners([("BEACH 99TH LLC", ["a", "b"])])
    lwc = _lwc([(1, ["a"]), (2, ["b"]), (3, ["z"])])  # node 3 unrelated
    assert le._groups_from(owners, lwc) == {"BEACH 99TH LLC": {1, 2}}


def test_group_needs_two_distinct_nodes():
    # Both buildings resolve to the SAME landlord node -> nothing to link.
    owners = _owners([("ONE OWNER LLC", ["a", "b"])])
    lwc = _lwc([(7, ["a", "b"])])
    assert le._groups_from(owners, lwc) == {}


def test_building_without_lwc_node_is_dropped_no_crash():
    owners = _owners([("PARTIAL LLC", ["a", "missing"])])
    lwc = _lwc([(1, ["a"]), (2, None)])               # null bbls must not crash
    # only one node covers PARTIAL LLC's buildings -> below the 2-node floor
    assert le._groups_from(owners, lwc) == {}


def test_edges_are_a_weighted_clique():
    owners = _owners([("TRIO LLC", ["a", "b", "c"])])
    lwc = _lwc([(1, ["a"]), (2, ["b"]), (3, ["c"])])
    groups = le._groups_from(owners, lwc)
    rows = le._clique_rows(groups["TRIO LLC"], star_above=150)
    assert sorted(rows) == [(1, 2), (1, 3), (2, 3)]


def test_owner_sql_uses_word_boundaries_and_excludes_hdfc():
    # The Postgres marker regex is validated live; here just assert the SQL is well-formed:
    # word-boundary markers (not bare LIKE) and the HDFC/institutional exclusions are present.
    sql = le._owner_sql(le.DEFAULT_MAX_DEGREE)
    assert r"\y" in sql and "LLC" in sql and "CORP" in sql
    assert "HDFC" in sql and "HOUSING DEVELOPMENT FUND" in sql
    assert "<= 100" in sql  # degree cap inlined
