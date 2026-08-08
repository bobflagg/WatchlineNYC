"""Hermetic tests for lookup_landlord and landlord_portfolio_membership."""

from __future__ import annotations

import pytest

from watchline.discovery.agent import cypher_guard
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import RELIABILITY_KEY, ReliabilityType
from watchline.discovery.agent.tools import landlord_portfolio as lp


@pytest.fixture
def patch(monkeypatch):
    def _install(row):
        captured: dict[str, object] = {}

        def fake_read(cypher, params=None, **kwargs):
            captured["cypher"] = cypher
            captured["params"] = params
            return ReadResult(records=[] if row is None else [row], truncated=False, row_cap=1000)

        monkeypatch.setattr(lp, "read", fake_read)
        return captured

    return _install


# -- lookup_landlord -------------------------------------------------------


def test_lookup_landlord_type_ii_with_caveat(patch):
    patch({"actor_id": "ACT-LL-42357", "name": "GLEN BROWN",
           "bizaddr": "625 BROADWAY 11 FL, MANHATTAN NY", "building_count": 384})
    out = lp.lookup_landlord("ACT-LL-42357")
    assert out["found"] is True
    assert out["building_count"] == 384
    assert out[RELIABILITY_KEY]["type"] == ReliabilityType.TYPE_II.value
    elements = {c["element"] for c in out[RELIABILITY_KEY]["caveats"]}
    assert "Landlord" in elements


def test_lookup_landlord_not_found_mentions_unresolved_actor(patch):
    patch(None)
    out = lp.lookup_landlord("ACT-ACRIS-abc")
    assert out["found"] is False
    assert "raw ACRIS party" in out["reason"]


def test_lookup_landlord_invalid(patch):
    patch(None)
    assert lp.lookup_landlord("")["found"] is False


# -- landlord_portfolio_membership ----------------------------------------


def test_membership_returns_portfolios_with_provenance(patch):
    patch({"actor_id": "ACT-LL-42357", "name": "GLEN BROWN", "portfolios": [
        {"portfolio_id": "PF-20260729T002106Z-37051", "member_count": 3,
         "building_count": 424, "residential_units": 2057,
         "method": "GDS WCC+Louvain", "run_id": "20260729T002106Z",
         "generated_at": "2026-07-29T00:21:06Z"}]})
    out = lp.landlord_portfolio_membership("ACT-LL-42357")
    assert out["portfolio_count"] == 1
    p = out["portfolios"][0]
    assert p["portfolio_id"] == "PF-20260729T002106Z-37051"
    assert p["run_id"] == "20260729T002106Z" and p["method"] == "GDS WCC+Louvain"
    assert out[RELIABILITY_KEY]["type"] == ReliabilityType.TYPE_II.value


def test_membership_empty_is_a_normal_answer(patch):
    patch({"actor_id": "ACT-LL-1", "name": ",MARIA CROSS", "portfolios": []})
    out = lp.landlord_portfolio_membership("ACT-LL-1")
    assert out["found"] is True
    assert out["portfolios"] == [] and out["portfolio_count"] == 0


def test_membership_caveats_cover_portfolio(patch):
    patch({"actor_id": "ACT-LL-42357", "name": "X", "portfolios": []})
    out = lp.landlord_portfolio_membership("ACT-LL-42357")
    elements = {c["element"] for c in out[RELIABILITY_KEY]["caveats"]}
    # Touches Landlord + MEMBER_OF + Portfolio → identity + portfolio caveats.
    assert "Landlord" in elements and "Portfolio" in elements


def test_cypher_passes_guard(patch):
    cap = patch(None)
    lp.lookup_landlord("ACT-LL-42357")
    cypher_guard.assert_read_only(cap["cypher"])
    lp.landlord_portfolio_membership("ACT-LL-42357")
    cypher_guard.assert_read_only(cap["cypher"])
