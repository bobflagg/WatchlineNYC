"""Hermetic tests for ownership_vs_registration_diff and compare_entities."""

from __future__ import annotations

import json

import pytest

from watchline.discovery.agent import cypher_guard
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import RELIABILITY_KEY, ReliabilityType
from watchline.discovery.agent.tools import compare


# -- ownership_vs_registration_diff ----------------------------------------


@pytest.fixture
def patch_read(monkeypatch):
    def _install(row):
        captured: dict[str, object] = {}

        def fake_read(cypher, params=None, **kwargs):
            captured["cypher"] = cypher
            captured["params"] = params
            return ReadResult(records=[] if row is None else [row], truncated=False, row_cap=1000)

        monkeypatch.setattr(compare, "read", fake_read)
        return captured

    return _install


def test_diff_aligns_three_parties(patch_read):
    patch_read({"bbl": "1000050010", "recorded_owner": "25 WATER OWNER, LLC",
                "registered": [{"actor_id": "ACT-LL-15987", "name": "BRIAN STEINWURTZEL", "role": None}],
                "controllers": [{"actor_id": "ACT-LL-90202", "name": "PETER HUNGERFORD"}]})
    out = compare.ownership_vs_registration_diff("1000050010")
    assert out["recorded_owner"]["name"] == "25 WATER OWNER, LLC"
    assert out["registered"][0]["role"] == "role not recorded"  # null role
    assert out["apparent_controllers"][0]["name"] == "PETER HUNGERFORD"
    # Three genuinely different names → differs on every pair.
    assert out["comparisons"]["recorded_vs_registered"]["verdict"] == "differs"
    assert out["comparisons"]["registered_vs_controller"]["verdict"] == "differs"
    assert out[RELIABILITY_KEY]["type"] == ReliabilityType.TYPE_II.value


def test_diff_registration_query_starts_from_actor(patch_read):
    cap = patch_read({"bbl": "1000050010", "recorded_owner": "X", "registered": [], "controllers": []})
    compare.ownership_vs_registration_diff("1000050010")
    # REGISTERED_FOR originates on :Actor, not :Landlord.
    assert "(reg:Actor)-[r:REGISTERED_FOR]->(b)" in cap["cypher"]
    cypher_guard.assert_read_only(cap["cypher"])


def test_diff_invalid_and_not_found(patch_read):
    patch_read(None)
    assert compare.ownership_vs_registration_diff("nope")["found"] is False
    assert compare.ownership_vs_registration_diff("1000050010")["found"] is False


# -- compare_entities ------------------------------------------------------


@pytest.fixture
def fake_aggs(monkeypatch):
    """Replace the underlying aggregations so we test the orchestration only."""
    calls: list[tuple] = []

    def fake_building(bbl, source_name, event_type, since_months=None):
        calls.append(("building", bbl, source_name, event_type))
        return {"found": True, "bbl": bbl, "total": 10, "percent_open": 5.0,
                "reliability": {"type": "I"}}

    def fake_portfolio(actor_id=None, portfolio_id=None, source_name=None,
                       event_type=None, since_years=None):
        calls.append(("portfolio", portfolio_id or actor_id, source_name, event_type))
        return {"found": True, "total": 20, "percent_open": 15.0,
                "reliability": {"type": "II"}}

    monkeypatch.setattr(compare, "aggregate_building_events", fake_building)
    monkeypatch.setattr(compare, "aggregate_landlord_portfolio_events", fake_portfolio)
    return calls


def test_compare_aligns_per_entity_never_sums(fake_aggs):
    out = compare.compare_entities(["1000050010", "2028100045"], "building", "HPD", "Violation")
    assert out["count"] == 2
    assert [r["entity_id"] for r in out["results"]] == ["1000050010", "2028100045"]
    # Each entity keeps its own aggregate + reliability; no cross-entity total.
    assert all("aggregate" in r for r in out["results"])
    assert "total" not in out  # never summed across entities


def test_compare_runs_one_aggregation_per_entity(fake_aggs):
    compare.compare_entities(["A", "B", "C"], "portfolio", "HPD", "Violation")
    assert len(fake_aggs) == 3
    assert all(c[0] == "portfolio" for c in fake_aggs)


def test_compare_rejects_bad_counts(fake_aggs):
    assert compare.compare_entities(["only-one"], "building", "HPD", "Violation")["error"] == "invalid_comparison"
    assert compare.compare_entities([str(i) for i in range(9)], "building", "HPD", "Violation")["error"] == "invalid_comparison"


def test_compare_rejects_bad_kind(fake_aggs):
    assert compare.compare_entities(["A", "B"], "spaceship", "HPD", "Violation")["error"] == "invalid_entity_kind"


def test_compare_entities_is_orchestrator_type_i(fake_aggs):
    # The wrapper itself runs no Cypher; per-entity reliability is authoritative.
    assert compare.compare_entities.reliability.type is ReliabilityType.TYPE_I
    out = compare.compare_entities(["A", "B"], "portfolio", "HPD", "Violation")
    assert out["results"][0]["aggregate"]["reliability"]["type"] == "II"
