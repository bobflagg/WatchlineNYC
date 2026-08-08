"""Hermetic tests for aggregate_events_by_geo_time."""

from __future__ import annotations

import pytest

from watchline.discovery.agent import cypher_guard
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import ReliabilityType
from watchline.discovery.agent.tools import geo_time


@pytest.fixture
def patch(monkeypatch):
    def _install(rows):
        captured: dict[str, object] = {}

        def fake_read(cypher, params=None, **kwargs):
            captured["cypher"] = cypher
            captured["params"] = params
            return ReadResult(records=list(rows), truncated=False, row_cap=1000)

        monkeypatch.setattr(geo_time, "read", fake_read)
        return captured

    return _install


def test_borough_scoped_total(patch):
    cap = patch([{"borough": "Bronx", "c": 4577}])
    out = geo_time.aggregate_events_by_geo_time("Marshal", "Eviction", "2025-01-01", "2026-01-01", "Bronx")
    assert out["total"] == 4577
    assert out["by_borough"] == {"Bronx": 4577}
    assert cap["params"]["borough"] == "Bronx"
    assert "b.borough = $borough" in cap["cypher"]


def test_citywide_has_no_borough_predicate(patch):
    cap = patch([{"borough": "Manhattan", "c": 3}, {"borough": "Bronx", "c": 7}])
    out = geo_time.aggregate_events_by_geo_time("DOB", "Violation", "2026-07-01")
    assert out["total"] == 10
    assert out["borough"] is None
    assert "b.borough = $borough" not in cap["cypher"]


def test_date_from_required(patch):
    patch([])
    out = geo_time.aggregate_events_by_geo_time("DOB", "Violation", "")
    assert out["error"] == "date_range_required"


def test_invalid_pair(patch):
    patch([])
    out = geo_time.aggregate_events_by_geo_time("DOB", "Complaint", "2025-01-01")
    assert out["error"] == "invalid_event_filter"


def test_invalid_borough(patch):
    patch([])
    out = geo_time.aggregate_events_by_geo_time("Marshal", "Eviction", "2025-01-01", borough="Gotham")
    assert out["error"] == "invalid_borough"


def test_default_upper_bound_is_today(patch):
    cap = patch([])
    geo_time.aggregate_events_by_geo_time("DOB", "Violation", "2026-07-01")
    # No explicit date_to → coalesce to date() as the exclusive upper bound.
    assert "coalesce(date($date_to), date())" in cap["cypher"]


def test_type_i_and_guard(patch):
    cap = patch([{"borough": "Bronx", "c": 1}])
    out = geo_time.aggregate_events_by_geo_time("Marshal", "Eviction", "2025-01-01", "2026-01-01", "Bronx")
    assert out  # smoke
    cypher_guard.assert_read_only(cap["cypher"])
    assert geo_time.aggregate_events_by_geo_time.reliability.type is ReliabilityType.TYPE_I
