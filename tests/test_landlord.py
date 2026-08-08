"""Hermetic tests for ``resolve_landlord_name`` — ``db.read`` faked, no graph.

Every result class, the disambiguation cap, the no-score guarantee, and the
Type II caveat are exercised without network. The live fulltext path (against
real dirty names like the two ``SANDRO CATALIC`` landlords) is the integration
tier (Group 6).
"""

from __future__ import annotations

import json

import pytest

from watchline.discovery.agent import cypher_guard
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import RELIABILITY_KEY, ReliabilityType
from watchline.discovery.agent.tools import landlord


def _row(actor_id, name, bizaddr="1 MAIN ST, BROOKLYN NY", building_count=1):
    return {"actor_id": actor_id, "name": name, "bizaddr": bizaddr,
            "building_count": building_count}


@pytest.fixture
def patch(monkeypatch):
    def _install(rows):
        captured: dict[str, object] = {}

        def fake_read(cypher, params=None, **kwargs):
            captured["cypher"] = cypher
            captured["params"] = params
            return ReadResult(records=list(rows), truncated=False, row_cap=25)

        monkeypatch.setattr(landlord, "read", fake_read)
        return captured

    return _install


def test_single_exact_match_resolves(patch):
    patch([
        _row("ACT-LL-42357", "GLEN BROWN", building_count=384),
        _row("ACT-LL-9", "JOHN BROWN"),  # shares 'brown' only → indeterminate
    ])
    out = landlord.resolve_landlord_name("Glen Brown")
    assert out["status"] == "resolved"
    assert out["landlord"]["actor_id"] == "ACT-LL-42357"
    assert out["landlord"]["building_count"] == 384


def test_multiple_exact_matches_disambiguate(patch):
    # The real SANDRO CATALIC case: several distinct landlords, same name.
    patch([
        _row("ACT-LL-100020", "SANDRO CATALIC"),
        _row("ACT-LL-100021", "SANDRO CATALIC"),
        _row("ACT-LL-100022", "SANDRO CATALIC"),
    ])
    out = landlord.resolve_landlord_name("Sandro Catalic")
    assert out["status"] == "needs_disambiguation"
    assert out["candidate_total"] == 3
    assert {c["actor_id"] for c in out["candidates"]} == {
        "ACT-LL-100020", "ACT-LL-100021", "ACT-LL-100022"
    }
    # Every candidate carries distinguishing detail.
    for c in out["candidates"]:
        assert "business_address" in c and "building_count" in c


def test_no_exact_match_disambiguates_the_weak_ones(patch):
    # Nothing matches the query's token set exactly; do not pick, disambiguate.
    patch([
        _row("ACT-LL-1", "MARIA BROWN"),
        _row("ACT-LL-2", "MARIA CROSS"),
    ])
    out = landlord.resolve_landlord_name("Maria Zzz")
    assert out["status"] == "needs_disambiguation"
    assert out["candidate_total"] == 2


def test_disambiguation_caps_and_reports_total(patch):
    patch([_row(f"ACT-LL-{i}", "SANDRO CATALIC") for i in range(7)])
    out = landlord.resolve_landlord_name("Sandro Catalic")
    assert out["status"] == "needs_disambiguation"
    assert len(out["candidates"]) == landlord.MAX_CANDIDATES  # 5
    assert out["candidate_total"] == 7
    assert out["candidates_truncated"] is True


def test_not_found(patch):
    patch([])
    out = landlord.resolve_landlord_name("Nobody At All")
    assert out["status"] == "not_found"
    assert out["candidates"] == []


@pytest.mark.parametrize("bad", ["", "   ", ",.()", None])
def test_invalid_input(patch, bad):
    patch([])
    out = landlord.resolve_landlord_name(bad)
    assert out["status"] == "invalid_input"


def test_query_is_normalized_tokens(patch):
    captured = patch([_row("ACT-LL-1", "LARS PETER LIBERT")])
    # Surname-first, punctuated input still queries on clean tokens.
    landlord.resolve_landlord_name("LIBERT, LARS PETER")
    # Tokens are sorted, lowercased, alphanumeric — injection-safe for Lucene.
    assert captured["params"]["query"] == "lars libert peter"


def test_no_similarity_score_is_exposed(patch):
    patch([_row("ACT-LL-42357", "GLEN BROWN")])
    out = landlord.resolve_landlord_name("Glen Brown")
    # A retrieval score must never surface as an identity claim (D2).
    assert "score" not in json.dumps(out).lower()


def test_type_ii_with_landlord_caveat(patch):
    declaration = landlord.resolve_landlord_name.reliability
    assert declaration.type is ReliabilityType.TYPE_II
    assert declaration.requires_tier_4 is False
    patch([_row("ACT-LL-1", "GLEN BROWN")])
    out = landlord.resolve_landlord_name("Glen Brown")
    elements = {c["element"] for c in out[RELIABILITY_KEY]["caveats"]}
    assert "Landlord" in elements


def test_search_cypher_passes_guard():
    cypher_guard.assert_read_only(landlord._SEARCH_CYPHER)
