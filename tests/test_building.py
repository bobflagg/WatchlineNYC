"""Hermetic tests for the building lookup tools — ``db.read`` faked, no graph."""

from __future__ import annotations

import pytest

from watchline.discovery.agent import cypher_guard
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import RELIABILITY_KEY, ReliabilityType
from watchline.discovery.agent.tools import building


@pytest.fixture
def patch(monkeypatch):
    def _install(row):
        captured: dict[str, object] = {}

        def fake_read(cypher, params=None, **kwargs):
            captured["cypher"] = cypher
            captured["params"] = params
            records = [] if row is None else [row]
            return ReadResult(records=records, truncated=False, row_cap=1000)

        monkeypatch.setattr(building, "read", fake_read)
        return captured

    return _install


# -- lookup_building -------------------------------------------------------


def test_lookup_building_maps_zoning_alias(patch):
    patch({"bbl": "1000050010", "address": "115 BROAD STREET", "borough": "Manhattan",
           "residential_units": 1320, "year_built": 1969, "building_class": "D5",
           "zoning": "C5-5", "recorded_owner": "25 WATER OWNER, LLC", "bin": "1001026",
           "latitude": 40.7, "longitude": -74.0})
    out = building.lookup_building("1000050010")
    assert out["found"] is True
    # "zoning" is surfaced from dof_ownername's neighbour dof_zonedist1.
    assert out["zoning"] == "C5-5"
    assert out["year_built"] == 1969
    assert out[RELIABILITY_KEY]["type"] == ReliabilityType.TYPE_I.value


def test_lookup_building_invalid_bbl(patch):
    patch(None)
    assert building.lookup_building("garbage")["found"] is False


def test_lookup_building_not_found(patch):
    patch(None)
    out = building.lookup_building("1000050010")
    assert out["found"] is False and "No building" in out["reason"]


# -- lookup_building_events: vocab routing --------------------------------


def _events_row(bbl="2028100045", total=0, sample=None):
    return {"bbl": bbl, "total": total, "sample": sample or []}


def test_status_open_uses_vocab_fragment_not_raw_equality(patch):
    cap = patch(_events_row())
    building.lookup_building_events("2028100045", "HPD", "Violation", status="open")
    # The correctness trap this whole module exists to avoid: never `e.status =`.
    assert "toUpper(e.status)" in cap["cypher"]
    assert "e.status = 'Open'" not in cap["cypher"]


def test_violation_class_uses_vocab_fragment(patch):
    cap = patch(_events_row())
    building.lookup_building_events("2028100045", "HPD", "Violation", violation_class="C")
    assert "toUpper(e.violation_class)" in cap["cypher"]


def test_invalid_source_type_pair_is_rejected(patch):
    patch(_events_row())
    out = building.lookup_building_events("2028100045", "DOB", "Complaint")
    assert out["error"] == "invalid_event_filter"


def test_invalid_status_reports_valid_options(patch):
    patch(_events_row())
    out = building.lookup_building_events("2028100045", "HPD", "Violation", status="wibble")
    assert out["error"] == "invalid_event_filter"


def test_source_is_always_constrained(patch):
    cap = patch(_events_row())
    building.lookup_building_events("2028100045", "HPD", "Violation")
    assert cap["params"]["source"] == "HPD" and cap["params"]["type"] == "Violation"
    assert "e.source_name = $source" in cap["cypher"]


# -- most_recent + the future-date anomaly (P3-2) -------------------------


def test_most_recent_flags_future_date_anomaly(patch):
    patch(_events_row(total=1, sample=[{"event_id": "EVT-HPD-VACATE-2327",
        "event_date": "2040-08-20", "status": "Active", "violation_class": "Fire Damage"}]))
    out = building.lookup_building_events("4012700064", "HPD", "VacateOrder", most_recent=True)
    assert out["date_anomaly"] is True
    assert out["most_recent"]["event_date"] == "2040-08-20"
    assert "date_anomaly_note" in out


def test_most_recent_normal_date_no_anomaly(patch):
    patch(_events_row(total=1, sample=[{"event_id": "E1", "event_date": "2026-05-27",
        "status": None, "violation_class": "DEED"}]))
    out = building.lookup_building_events("3004610030", "ACRIS", "DeedTransfer", most_recent=True)
    assert out["date_anomaly"] is False
    assert out["most_recent"]["event_id"] == "E1"


def test_most_recent_excludes_null_dates_in_query(patch):
    cap = patch(_events_row())
    building.lookup_building_events("2028100045", "HPD", "Violation", most_recent=True)
    assert "e.event_date IS NOT NULL" in cap["cypher"]


# -- listing shape ---------------------------------------------------------


def test_listing_returns_events_and_total(patch):
    sample = [{"event_id": f"E{i}", "event_date": "2026-01-01", "status": "Open",
               "violation_class": "C"} for i in range(3)]
    patch(_events_row(total=75, sample=sample))
    out = building.lookup_building_events("2028100045", "HPD", "Violation", status="open")
    assert out["total"] == 75
    assert len(out["events"]) == 3
    assert out["truncated"] is True
    # Canonical interpretation attached.
    assert out["events"][0]["status"] == "OPEN"
    assert out["events"][0]["class_scheme"] == "hpd_hazard"


def test_since_months_adds_date_bound(patch):
    cap = patch(_events_row())
    building.lookup_building_events("2025180028", "HPD", "Complaint", since_months=12)
    assert "duration({months: $since_months})" in cap["cypher"]
    assert cap["params"]["since_months"] == 12


def test_status_and_class_filters_use_distinct_params(patch):
    # Regression: both filters defaulted to the param name 'vals', so $vals_exact
    # collided and the status list was silently overwritten by the class list,
    # zeroing counts. They must use distinct params.
    cap = patch(_events_row())
    building.lookup_building_events("2028100045", "HPD", "Violation", status="open", violation_class="C")
    assert "statusv_exact" in cap["params"] and "classv_exact" in cap["params"]
    assert cap["params"]["statusv_exact"] == ["OPEN"]
    assert cap["params"]["classv_exact"] == ["C"]


def test_events_cypher_passes_guard(patch):
    cap = patch(_events_row())
    building.lookup_building_events("2028100045", "HPD", "Violation", status="open", violation_class="C")
    cypher_guard.assert_read_only(cap["cypher"])
