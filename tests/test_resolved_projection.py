"""Hermetic tests for the C5 co-op/condo projection (pure)."""
from __future__ import annotations

from watchline.discovery.ingest.portfolio.resolved_projection import project


def test_all_rental():
    assert project(5, 5) == {"total_building_count": 5, "building_count": 5,
                             "coop_condo_count": 0, "coop_condo_dominated": False}


def test_majority_coop_condo_is_dominated():
    # 4 of 5 co-op/condo -> rental 1, dominated (ownership artifact), but entity is NOT dropped here.
    out = project(5, 1)
    assert out["coop_condo_count"] == 4 and out["coop_condo_dominated"] is True
    assert out["building_count"] == 1                     # rental-only attribution


def test_exactly_half_is_not_dominated():
    # 2 rental of 4 -> not >50% co-op/condo (tie is not dominated)
    assert project(4, 2)["coop_condo_dominated"] is False


def test_empty_footprint():
    assert project(0, 0)["coop_condo_dominated"] is False
