"""Hermetic tests for sister_buildings, control_network, shared_address_landlords."""

from __future__ import annotations

import pytest

from watchline.discovery.agent import cypher_guard
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import RELIABILITY_KEY, ReliabilityType
from watchline.discovery.agent.tools import network


class _Reads:
    def __init__(self, *record_sets):
        self.queue = list(record_sets)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, cypher, params=None, **kwargs):
        self.calls.append((cypher, params or {}))
        records = self.queue.pop(0) if self.queue else []
        return ReadResult(records=list(records), truncated=False, row_cap=1000)


@pytest.fixture
def patch(monkeypatch):
    def _install(*record_sets):
        reads = _Reads(*record_sets)
        monkeypatch.setattr(network, "read", reads)
        return reads

    return _install


# -- sister_buildings ------------------------------------------------------


def test_sister_buildings_summary_and_cap(patch):
    controller = [{"bbl": f"1{i:09d}", "address": "X", "borough": "M",
                   "via_actor_id": "ACT-LL-90202", "via_name": "P"} for i in range(96)]
    patch([{"bbl": "1000050010", "address": "115 BROAD STREET",
            "by_controller": controller, "by_portfolio": []}])
    out = network.sister_buildings("1000050010")
    assert out["summary"]["same_controller_count"] == 96
    assert len(out["same_controller"]) == 50  # capped
    assert out["truncated"] is True
    assert out[RELIABILITY_KEY]["type"] == ReliabilityType.TYPE_II.value


def test_sister_buildings_not_found(patch):
    patch([])
    assert network.sister_buildings("1000050010")["found"] is False


# -- control_network -------------------------------------------------------


def test_control_network_summary(patch):
    members = [{"actor_id": f"ACT-LL-{i}", "name": "L", "controlled_buildings": i,
                "connections": i} for i in range(60)]
    patch([{"portfolio_id": "PF-1", "run_id": "R", "method": "M", "generated_at": "T",
            "member_count": 111, "building_count": 297, "connection_edges": 12650,
            "members": members}])
    out = network.control_network(portfolio_id="PF-1")
    assert out["summary"]["member_count"] == 111
    assert out["summary"]["building_count"] == 297
    assert len(out["members"]) == 50 and out["truncated"] is True
    assert out["provenance"]["run_id"] == "R"


def test_control_network_requires_one_scope(patch):
    patch()
    assert network.control_network()["error"] == "scope_required"
    assert network.control_network(portfolio_id="P", actor_id="A")["error"] == "scope_required"


def test_control_network_actor_resolves_to_portfolio(patch):
    reads = patch(
        [{"pid": "PF-9"}],
        [{"portfolio_id": "PF-9", "run_id": "R", "method": "M", "generated_at": "T",
          "member_count": 3, "building_count": 5, "connection_edges": 2, "members": []}])
    out = network.control_network(actor_id="ACT-LL-42357")
    assert out["portfolio_id"] == "PF-9"
    assert reads.calls[0][1]["aid"] == "ACT-LL-42357"  # first read resolved the portfolio


# -- shared_address_landlords ----------------------------------------------


def test_shared_address_discloses_under_connection(patch):
    patch([{"actor_id": "ACT-LL-1", "name": ",MARIA CROSS", "bizaddr": "X",
            "connected": [{"actor_id": "ACT-LL-91593", "name": "PROPERTY PRESERVATION",
                           "bizaddr": "X", "weight": 2.0}]}])
    out = network.shared_address_landlords("ACT-LL-1")
    assert out["connected"][0]["actor_id"] == "ACT-LL-91593"
    assert "network_limitation" in out  # D11 under-connection disclosure
    # Type II with the CONNECTED_BY_ADDRESS caveat.
    elements = {c["element"] for c in out[RELIABILITY_KEY]["caveats"]}
    assert "CONNECTED_BY_ADDRESS" in elements


def test_shared_address_invalid(patch):
    patch([])
    assert network.shared_address_landlords("")["found"] is False


def test_guards(patch):
    reads = patch([{"actor_id": "A", "name": "n", "bizaddr": "x", "connected": []}])
    network.shared_address_landlords("ACT-LL-1")
    cypher_guard.assert_read_only(reads.calls[0][0])


# -- trace_actor_to_landlord (the known gap) -------------------------------


def test_trace_actor_never_returns_a_confident_match(patch):
    # A raw ACRIS party: actor row (not a landlord), then fulltext candidates.
    patch(
        [{"name": "LEVIEN HENRY", "is_landlord": False}],
        [{"actor_id": "ACT-LL-63872", "name": "KEITH HENRY HENRY", "building_count": 3},
         {"actor_id": "ACT-LL-4509", "name": "ALLAN HENRY", "building_count": 1}])
    out = network.trace_actor_to_landlord("ACT-ACRIS-abc")
    assert out["is_landlord"] is False
    # The whole point: no confident resolution, ever.
    assert out["resolved_landlord"] is None
    assert out["possibly_related_count"] == 2
    assert "no edge" in out["note"].lower()
    # Candidates carry match evidence, not a proven link.
    assert all("match" in c for c in out["possibly_related"])


def test_trace_actor_reports_an_already_landlord_directly(patch):
    patch([{"name": "GLEN BROWN", "is_landlord": True}])
    out = network.trace_actor_to_landlord("ACT-LL-42357")
    assert out["is_landlord"] is True and "resolved landlord" in out["note"].lower()


def test_trace_actor_not_found(patch):
    patch([])
    assert network.trace_actor_to_landlord("ACT-X")["found"] is False
