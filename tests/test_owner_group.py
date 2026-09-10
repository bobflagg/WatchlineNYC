"""Hermetic tests for the owner-identity (OwnerGroup) tools.

No Neo4j: ``db.read`` is replaced with canned rows whose shapes mirror the live
graph. The behaviour worth pinning: a landlord in no group is a *successful*
answer (a singleton is its own owner), and the unified-owner view reads its
counts from the node while capping the member/building samples.
"""

from __future__ import annotations

import pytest

from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import RELIABILITY_KEY
from watchline.discovery.agent.tools import owner_group
from watchline.discovery.agent.tools.owner_group import (
    owner_group_for_landlord,
    owner_group_portfolio,
)

# A Croman fragment resolving into the unified owner group.
LANDLORD_WITH_GROUP = {
    "actor_id": "ACT-LL-105462",
    "name": "STEVE CROMAN",
    "owner_group": {
        "owner_group_id": "OG-105462",
        "name": "STEVEN CROMAN",
        "member_count": 12,
        "building_count": 127,
        "composition": "identity",
        "method": "splink-identity+curated+llc",
        "generated_at": "2026-09-10T10:12:08.806Z",
    },
}

LANDLORD_SINGLETON = {
    "actor_id": "ACT-LL-1",
    "name": "JANE DOE",
    "owner_group": None,
}

GROUP_MAIN = {
    "owner_group_id": "OG-105462",
    "name": "STEVEN CROMAN",
    "member_count": 12,
    "building_count": 127,
    "composition": "identity",
    "method": "splink-identity+curated+llc",
    "generated_at": "2026-09-10T10:12:08.806Z",
    "member_names": ["STEVE CROMAN", "STEVEN CROMAN"],
    "member_ids": ["ACT-LL-105462", "ACT-LL-105463"],
}

GROUP_SAMPLE = {
    "sample": [
        {"bbl": "1005930008", "address": "17 GAY STREET", "borough": "Manhattan"},
        {"bbl": "1003440046", "address": "124 RIDGE STREET", "borough": "Manhattan"},
    ]
}


@pytest.fixture
def fake_read(monkeypatch):
    """Replace owner_group.read with a queue of canned rows, one per read call.

    Pass a list of rows (or ``None`` for an empty result); each read pops the next.
    """

    def _set(rows):
        queue = list(rows)

        def _read(cypher, parameters=None, **kwargs):
            row = queue.pop(0) if queue else None
            records = [] if row is None else [row]
            return ReadResult(records=records, truncated=False, row_cap=1)

        monkeypatch.setattr(owner_group, "read", _read)

    return _set


class TestOwnerGroupForLandlord:
    def test_landlord_in_a_group(self, fake_read):
        fake_read([LANDLORD_WITH_GROUP])
        result = owner_group_for_landlord("ACT-LL-105462")
        assert result["found"] is True
        assert result["owner_group"]["owner_group_id"] == "OG-105462"
        assert result["owner_group"]["member_count"] == 12
        assert result["owner_group"]["building_count"] == 127
        assert result["note"] is None

    def test_singleton_is_a_successful_answer(self, fake_read):
        """A landlord in no multi-member group is its own owner — found, with a
        null group and an explanatory note, never an error."""
        fake_read([LANDLORD_SINGLETON])
        result = owner_group_for_landlord("ACT-LL-1")
        assert result["found"] is True
        assert result["owner_group"] is None
        assert result["note"] and "stands alone" in result["note"]

    def test_landlord_not_found(self, fake_read):
        fake_read([None])
        result = owner_group_for_landlord("ACT-LL-999999")
        assert result["found"] is False
        assert result["reason"]

    def test_blank_actor_id_rejected(self, fake_read):
        fake_read([])
        result = owner_group_for_landlord("   ")
        assert result["found"] is False

    def test_type_ii_with_owner_group_caveat(self, fake_read):
        fake_read([LANDLORD_WITH_GROUP])
        result = owner_group_for_landlord("ACT-LL-105462")
        assert result[RELIABILITY_KEY]["type"] == "II"
        elements = {c["element"] for c in result[RELIABILITY_KEY]["caveats"]}
        assert "OwnerGroup" in elements


class TestOwnerGroupPortfolio:
    def test_unified_owner_view(self, fake_read):
        fake_read([GROUP_MAIN, GROUP_SAMPLE])
        result = owner_group_portfolio("OG-105462")
        assert result["found"] is True
        assert result["name"] == "STEVEN CROMAN"
        assert result["member_count"] == 12
        assert result["building_count"] == 127
        assert result["composition"] == "identity"
        assert result["member_names"] == ["STEVE CROMAN", "STEVEN CROMAN"]
        assert result["member_names_truncated"] is False
        assert len(result["buildings_sample"]) == 2
        assert result["provenance"]["method"] == "splink-identity+curated+llc"

    def test_member_names_are_capped(self, fake_read):
        many = dict(GROUP_MAIN, member_names=[f"NAME {i}" for i in range(40)])
        fake_read([many, GROUP_SAMPLE])
        result = owner_group_portfolio("OG-105462")
        assert len(result["member_names"]) == owner_group._SAMPLE_CAP
        assert result["member_names_truncated"] is True

    def test_group_not_found(self, fake_read):
        fake_read([None])
        result = owner_group_portfolio("OG-nope")
        assert result["found"] is False
        assert result["reason"]

    def test_type_ii_with_owner_group_caveat(self, fake_read):
        fake_read([GROUP_MAIN, GROUP_SAMPLE])
        result = owner_group_portfolio("OG-105462")
        assert result[RELIABILITY_KEY]["type"] == "II"
        elements = {c["element"] for c in result[RELIABILITY_KEY]["caveats"]}
        assert "OwnerGroup" in elements
