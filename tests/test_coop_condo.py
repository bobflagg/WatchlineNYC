"""Hermetic test for the co-op/condo classifier SQL shape (portfolio/coop_condo.py)."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio import coop_condo as cc


def test_coop_condo_sql_carries_the_classifier():
    sql = cc._COOP_CONDO_SQL
    assert "contactdescription" in sql
    assert "'CO-OP'" in sql and "'CONDO'" in sql
    assert "HeadOfficer" in sql and "IndividualOwner" in sql   # owner roles only
    assert "> 0.5" in sql                                       # majority rule


def test_set_matches_building_by_bbl():
    assert "MATCH (b:Building {bbl: bbl})" in cc._SET
    assert "SET b.coop_condo = true" in cc._SET
