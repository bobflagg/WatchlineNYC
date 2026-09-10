"""Hermetic tests for the management-layer (Manager / MANAGED_BY) tools.

No Neo4j: ``db.read`` is replaced with canned rows. The behaviour worth pinning:
a building with no managing agent is a *successful* answer, and the Manager
caveat ("a manager is not an owner") ships on every result.
"""

from __future__ import annotations

import pytest

from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import RELIABILITY_KEY
from watchline.discovery.agent.tools import manager
from watchline.discovery.agent.tools.manager import building_manager, manager_portfolio

BUILDING_WITH_MANAGER = {
    "bbl": "1005930008",
    "address": "17 GAY STREET",
    "manager": {
        "manager_id": "CENTENNIAL PROPERTIES NY",
        "name": "CENTENNIAL PROPERTIES NY",
        "building_count": 114,
        "method": "hpd-managing-agent",
        "generated_at": "2026-09-01T17:05:26.321Z",
    },
}

BUILDING_NO_MANAGER = {
    "bbl": "1000010010",
    "address": "140 CARDER ROAD",
    "manager": None,
}

MANAGER_ROW = {
    "manager_id": "CENTENNIAL PROPERTIES NY",
    "name": "CENTENNIAL PROPERTIES NY",
    "building_count": 114,
    "method": "hpd-managing-agent",
    "generated_at": "2026-09-01T17:05:26.321Z",
    "buildings_sample": [
        {"bbl": "1005930008", "address": "17 GAY STREET", "borough": "Manhattan"},
    ],
}


@pytest.fixture
def fake_read(monkeypatch):
    def _set(row):
        def _read(cypher, parameters=None, **kwargs):
            records = [] if row is None else [row]
            return ReadResult(records=records, truncated=False, row_cap=1)

        monkeypatch.setattr(manager, "read", _read)

    return _set


class TestBuildingManager:
    def test_building_with_manager(self, fake_read):
        fake_read(BUILDING_WITH_MANAGER)
        result = building_manager("1005930008")
        assert result["found"] is True
        assert result["manager"]["manager_id"] == "CENTENNIAL PROPERTIES NY"
        assert result["manager"]["building_count"] == 114
        assert result["note"] is None

    def test_no_manager_is_a_successful_answer(self, fake_read):
        fake_read(BUILDING_NO_MANAGER)
        result = building_manager("1000010010")
        assert result["found"] is True
        assert result["manager"] is None
        assert result["note"]

    def test_building_not_found(self, fake_read):
        fake_read(None)
        result = building_manager("1099999999")
        assert result["found"] is False

    def test_non_bbl_rejected(self, fake_read):
        fake_read(BUILDING_WITH_MANAGER)  # never reached
        result = building_manager("17 Gay Street")
        assert result["found"] is False
        assert "BBL" in result["reason"]

    def test_type_ii_with_manager_caveat(self, fake_read):
        fake_read(BUILDING_WITH_MANAGER)
        result = building_manager("1005930008")
        assert result[RELIABILITY_KEY]["type"] == "II"
        elements = {c["element"] for c in result[RELIABILITY_KEY]["caveats"]}
        assert "Manager" in elements


class TestManagerPortfolio:
    def test_manager_footprint(self, fake_read):
        fake_read(MANAGER_ROW)
        result = manager_portfolio("CENTENNIAL PROPERTIES NY")
        assert result["found"] is True
        assert result["building_count"] == 114
        assert len(result["buildings_sample"]) == 1
        assert result["provenance"]["method"] == "hpd-managing-agent"

    def test_manager_not_found(self, fake_read):
        fake_read(None)
        result = manager_portfolio("NOBODY")
        assert result["found"] is False

    def test_type_ii_with_manager_caveat(self, fake_read):
        fake_read(MANAGER_ROW)
        result = manager_portfolio("CENTENNIAL PROPERTIES NY")
        assert result[RELIABILITY_KEY]["type"] == "II"
        elements = {c["element"] for c in result[RELIABILITY_KEY]["caveats"]}
        assert "Manager" in elements
