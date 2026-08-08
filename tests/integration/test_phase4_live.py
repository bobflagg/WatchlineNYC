"""Phase 4 Tier 3 tools against the live discovery graph.

Run with ``pytest -m integration``. Needs a populated ``.env``. No sidecar.
Params come from the Tier 3 fixture queries, so assertions track the graph.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.tools.chain import trace_ownership_chain
from watchline.discovery.agent.tools.compare import (
    compare_entities,
    ownership_vs_registration_diff,
)
from watchline.discovery.agent.tools.network import (
    control_network,
    shared_address_landlords,
    sister_buildings,
    trace_actor_to_landlord,
)
from watchline.discovery.agent.tools.portfolio_detail import (
    portfolio_buildings_with_violations,
    portfolio_litigation,
)

pytestmark = pytest.mark.integration

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def q(fixtures) -> dict:
    """Tier-3 query params keyed by tool name."""
    return {query["tool"]: query["params"] for query in fixtures["queries"] if query["tier"] == 3}


def test_trace_ownership_chain(q):
    p = q["trace_ownership_chain"]
    out = trace_ownership_chain(p["bbl"])
    assert out["found"] is True
    assert out["summary"]["mortgage_count"] >= 1
    # The fixture's mortgage is satisfied (has a referencing MortgageSatisfaction).
    target = next((m for m in out["mortgages"] if m["event_id"] == p["mortgage_event_id"]), None)
    if target is not None:
        assert target["outstanding"] is False


def test_sister_buildings(q):
    p = q["sister_buildings"]
    out = sister_buildings(p["bbl"])
    assert out["found"] is True
    assert out["summary"]["same_controller_count"] >= 1


def test_control_network(q):
    p = q["control_network"]
    out = control_network(portfolio_id=p["portfolio_id"])
    assert out["summary"]["member_count"] == p["member_count"]
    assert out["summary"]["building_count"] == p["building_count"]


def test_shared_address_landlords(q):
    p = q["shared_address_landlords"]
    out = shared_address_landlords(p["actor_id"])
    ids = {c["actor_id"] for c in out["connected"]}
    assert p["connected_actor_id"] in ids
    assert "network_limitation" in out  # D11 disclosure


def test_portfolio_buildings_with_violations(q):
    p = q["portfolio_buildings_with_violations"]
    out = portfolio_buildings_with_violations(portfolio_id=p["portfolio_id"])
    assert out["found"] is True
    assert out["summary"]["building_count"] >= 1


def test_portfolio_litigation(q):
    p = q["portfolio_litigation"]
    out = portfolio_litigation(portfolio_id=p["portfolio_id"])
    assert out["found"] is True
    assert out["summary"]["filing_count"] >= 1


def test_ownership_vs_registration_diff(q):
    p = q["ownership_vs_registration_diff"]
    out = ownership_vs_registration_diff(p["bbl"])
    assert out["recorded_owner"]["name"] == p["recorded_owner"]
    reg_ids = {r["actor_id"] for r in out["registered"]}
    assert p["registered_actor_id"] in reg_ids


def test_trace_actor_to_landlord_is_honest(q):
    p = q["trace_actor_to_landlord"]
    out = trace_actor_to_landlord(p["actor_id"])
    assert out["is_landlord"] is False
    # The known gap: never a confident resolution.
    assert out["resolved_landlord"] is None
    assert out["possibly_related_count"] >= 0


def test_compare_entities_aligns_two_portfolios(fixtures):
    a = fixtures["anchors"]["landlord_with_portfolio"]["portfolio_id"]
    b = fixtures["anchors"]["portfolio_multi_member"]["portfolio_id"]
    out = compare_entities([a, b], "portfolio", "HPD", "Violation")
    assert out["count"] == 2
    assert "total" not in out  # never summed across entities
    assert all(r["aggregate"]["found"] for r in out["results"])
