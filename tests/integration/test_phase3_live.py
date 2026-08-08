"""Phase 3 Tier 1-2 tools against the live discovery graph.

Run with ``pytest -m integration``. Needs a populated ``.env``. No sidecar —
none of these tools geocode. Values are pulled from fixture anchors so the
assertions track the graph, not hardcoded literals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.reliability import ReliabilityType
from watchline.discovery.agent.tools.building import (
    aggregate_building_events,
    lookup_building,
    lookup_building_events,
)
from watchline.discovery.agent.tools.geo_time import aggregate_events_by_geo_time
from watchline.discovery.agent.tools.landlord_portfolio import (
    aggregate_landlord_portfolio_events,
    landlord_portfolio_membership,
    lookup_landlord,
    portfolio_buildings_by_borough,
    portfolio_summary,
)

pytestmark = pytest.mark.integration

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def anchors(fixtures) -> dict:
    return fixtures["anchors"]


@pytest.fixture(scope="module")
def edge_cases(fixtures) -> dict:
    return {name: case["entity"] for name, case in fixtures["edge_cases"].items()}


# -- Tier 1 ----------------------------------------------------------------


def test_lookup_building_fields(anchors):
    a = anchors["building_with_apparent_control"]
    out = lookup_building(a["bbl"])
    assert out["found"] is True
    assert out["residential_units"] == a["residential_units"]
    assert out["year_built"] == a["year_built"]
    assert out["zoning"] == a["zoning"]  # dof_zonedist1 surfaced as zoning


def test_last_sold_is_a_deed_transfer_date(anchors):
    a = anchors["building_with_deed_transfer"]
    out = lookup_building_events(a["bbl"], "ACRIS", "DeedTransfer", most_recent=True)
    assert out["most_recent"]["event_date"] == a["last_sold"]
    assert out["date_anomaly"] is False


def test_latest_complaint(anchors):
    a = anchors["building_with_recent_complaints"]
    out = lookup_building_events(a["bbl"], "HPD", "Complaint", most_recent=True)
    assert out["most_recent"]["event_date"] == a["event_date"]


def test_active_vacate_order(anchors):
    a = anchors["building_with_active_vacate_order"]
    out = lookup_building_events(a["bbl"], "HPD", "VacateOrder")
    assert out["found"] is True and out["total"] >= 1


def test_open_hpd_violations_present(anchors):
    a = anchors["building_open_hpd_class_c"]
    out = lookup_building_events(a["bbl"], "HPD", "Violation", status="open")
    assert out["found"] is True and out["total"] > 0


def test_lookup_landlord(anchors):
    a = anchors["landlord_with_portfolio"]
    out = lookup_landlord(a["actor_id"])
    assert out["name"] == a["name"]
    assert out["building_count"] == a["bbl_count"]
    assert out["reliability"]["type"] == ReliabilityType.TYPE_II.value


def test_landlord_portfolio_membership(anchors):
    a = anchors["landlord_with_portfolio"]
    out = landlord_portfolio_membership(a["actor_id"])
    ids = {p["portfolio_id"] for p in out["portfolios"]}
    assert a["portfolio_id"] in ids


# -- Tier 2 ----------------------------------------------------------------


def test_aggregate_building_events_percent_open(anchors):
    a = anchors["building_open_hpd_class_c"]
    out = aggregate_building_events(a["bbl"], "HPD", "Violation")
    assert 0 <= out["percent_open"] <= 100
    assert out["by_class"]["C"]["is_hazard"] is True


def test_portfolio_summary_reads_precomputed(anchors):
    a = anchors["portfolio_multi_member"]
    out = portfolio_summary(a["portfolio_id"])
    assert out["building_count"] == a["building_count"]
    assert out["residential_units"] == a["residential_units"]
    assert out["member_count"] == a["member_count"]


def test_portfolio_buildings_by_borough_sums(anchors):
    a = anchors["portfolio_multi_member"]
    out = portfolio_buildings_by_borough(a["portfolio_id"])
    assert out["total_buildings"] == a["building_count"]


def test_aggregate_portfolio_class_breakdown(anchors):
    a = anchors["landlord_with_portfolio"]
    out = aggregate_landlord_portfolio_events(
        portfolio_id=a["portfolio_id"], source_name="HPD", event_type="Violation")
    assert out["total"] > 0
    # All four HPD classes appear across a real portfolio, each labelled.
    assert {"A", "B", "C", "I"} <= set(out["by_class"])


def test_geo_time_bronx_evictions_2025(edge_cases, fixtures):
    expected = fixtures["anchors"]["eviction_scope_bronx"]["eviction_count"]
    out = aggregate_events_by_geo_time("Marshal", "Eviction", "2025-01-01", "2026-01-01", "Bronx")
    assert out["total"] == expected
