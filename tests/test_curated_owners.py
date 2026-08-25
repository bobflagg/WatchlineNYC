"""Hermetic tests for the curated same-owner override matcher/clique logic.

Pure functions over a synthetic ``landlords_with_connections`` frame — no DB, no
Splink. Gated on the ``ingest`` extra (pandas/splink); skips cleanly without it, so the
default hermetic suite still collects. Run under: ``uv run --extra ingest pytest``.
"""
from __future__ import annotations

import pytest

pytest.importorskip("splink")  # ingest extra present ⟹ pandas/psycopg2 present too
import pandas as pd

from watchline.discovery.ingest.portfolio import curated_owners as co
from watchline.discovery.ingest.portfolio.curated_owners import CuratedOwner


def _lwc(rows):
    return pd.DataFrame(rows, columns=["nodeid", "name", "bbls"])


def test_matches_exact_name_variants_and_normalizes():
    owners = (CuratedOwner("croman", "Croman", ("STEVEN CROMAN", "STEVE CROMAN"), "x"),)
    lwc = _lwc([
        (1, "steven croman", ["1a"]),     # lowercase -> normalized match
        (2, "STEVE  CROMAN", ["1b"]),      # extra whitespace -> normalized match
        (3, "STEVEN CROMANO", ["1c"]),     # different surname -> NO match
        (4, "DIVYA RASHAD", ["1d"]),       # unrelated -> NO match
    ])
    groups = co._match_groups(lwc, owners)
    assert groups == {"croman": {1, 2}}


def test_owners_are_isolated_from_each_other():
    owners = (
        CuratedOwner("croman", "Croman", ("STEVEN CROMAN",), "x"),
        CuratedOwner("rashad", "Rashad", ("DIVYA RASHAD",), "x"),
    )
    lwc = _lwc([(1, "STEVEN CROMAN", ["a"]), (2, "DIVYA RASHAD", ["b"]),
                (3, "STEVEN CROMAN", ["c"])])
    assert co._match_groups(lwc, owners) == {"croman": {1, 3}, "rashad": {2}}


def test_bbl_allow_scopes_to_matching_buildings():
    owners = (CuratedOwner("j", "J", ("JOHN DOE",), "x", bbl_allow=("keep1", "keep2")),)
    lwc = _lwc([
        (1, "JOHN DOE", ["keep1", "other"]),   # touches an allowed bbl -> in
        (2, "JOHN DOE", ["nope"]),             # name matches but no allowed bbl -> out
        (3, "JOHN DOE", None),                 # null bbls -> out (no crash)
    ])
    assert co._match_groups(lwc, owners) == {"j": {1}}


def test_single_node_group_yields_no_edges():
    # A curated owner with only one matching node can't form an edge.
    assert co._clique_rows({7}, star_above=150) == []
    assert co._clique_rows(set(), star_above=150) == []


def test_clique_is_full_below_star_threshold():
    rows = co._clique_rows({3, 1, 2}, star_above=150)
    assert sorted(rows) == [(1, 2), (1, 3), (2, 3)]           # sorted, all pairs


def test_star_shape_above_threshold_bounds_edges():
    rows = co._clique_rows({10, 20, 30, 40}, star_above=3)   # 4 > 3 -> star
    assert sorted(rows) == [(10, 20), (10, 30), (10, 40)]     # hub = min id, n-1 edges


def test_seed_table_is_well_formed():
    ids = [o.owner_id for o in co.CURATED_OWNERS]
    assert len(ids) == len(set(ids)), "owner_id must be unique"
    for o in co.CURATED_OWNERS:
        assert o.names and all(n.strip() for n in o.names), f"{o.owner_id} needs names"
        assert o.evidence.strip(), f"{o.owner_id} needs verifying evidence"
