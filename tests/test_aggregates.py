"""Hermetic tests for the Tier-2 aggregation tools and the shared rollup.

The source-collision regressions live here: the whole reason every event query
constrains ``source_name`` is that HPD and DOB reuse class codes A/B/C and HPD
casing differs by type. ``db.read`` is faked so no graph is touched.
"""

from __future__ import annotations

import pytest

from watchline.discovery.agent import cypher_guard
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import RELIABILITY_KEY, ReliabilityType
from watchline.discovery.agent.tools import building
from watchline.discovery.agent.tools import landlord_portfolio as lp
from watchline.discovery.agent.tools._events import rollup_events
from watchline.discovery.agent.vocab import EventType, Source


class _Reads:
    """A fake ``read`` that returns queued record-sets in call order, and
    captures each (cypher, params)."""

    def __init__(self, *record_sets):
        self.queue = list(record_sets)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, cypher, params=None, **kwargs):
        self.calls.append((cypher, params or {}))
        records = self.queue.pop(0) if self.queue else []
        return ReadResult(records=list(records), truncated=False, row_cap=1000)


# -- the shared rollup: source-aware canonicalization ----------------------


def test_rollup_open_casing_differs_by_type_but_both_count_as_open():
    # HPD Complaint stores 'OPEN'; HPD Violation stores 'Open'. Both are OPEN.
    complaints = rollup_events(Source.HPD, EventType.COMPLAINT,
        [{"status": "OPEN", "cls": None, "c": 5}, {"status": "CLOSE", "cls": None, "c": 15}])
    assert complaints["open_count"] == 5 and complaints["percent_open"] == 25.0
    violations = rollup_events(Source.HPD, EventType.VIOLATION,
        [{"status": "Open", "cls": "C", "c": 3}])
    assert violations["open_count"] == 3


def test_rollup_labels_hpd_hazard_classes():
    out = rollup_events(Source.HPD, EventType.VIOLATION, [
        {"status": "Open", "cls": "C", "c": 2},
        {"status": "Close", "cls": "I", "c": 7}])
    assert out["by_class"]["C"]["is_hazard"] is True
    assert out["by_class"]["C"]["label"] == "immediately hazardous"
    # Class I is administrative — present, but not a hazard.
    assert out["by_class"]["I"]["is_hazard"] is False
    assert out["hpd_hazard_classes"] == ["A", "B", "C"]


def test_rollup_does_not_label_dob_class_c_as_hpd_hazard():
    # DOB 'C' is an unrelated code; it must not borrow HPD's hazard label.
    out = rollup_events(Source.DOB, EventType.VIOLATION, [{"status": "Active", "cls": "C", "c": 9}])
    assert "is_hazard" not in out["by_class"]["C"]
    assert out["hpd_hazard_classes"] is None


# -- aggregate_building_events --------------------------------------------


@pytest.fixture
def patch_building(monkeypatch):
    def _install(*record_sets):
        reads = _Reads(*record_sets)
        monkeypatch.setattr(building, "read", reads)
        return reads

    return _install


def test_aggregate_building_events_rollup(patch_building):
    reads = patch_building([
        {"status": "Open", "cls": "C", "c": 30},
        {"status": "Close", "cls": "C", "c": 224},
        {"status": "Open", "cls": "A", "c": 10}])
    out = building.aggregate_building_events("2028100045", "HPD", "Violation")
    assert out["total"] == 264
    assert out["by_class"]["C"]["open_count"] == 30  # the "open Class C" answer
    assert out["percent_open"] == round(100 * 40 / 264, 1)
    assert out[RELIABILITY_KEY]["type"] == ReliabilityType.TYPE_I.value


def test_aggregate_building_events_source_is_constrained(patch_building):
    reads = patch_building([{"status": "Active", "cls": "C", "c": 5}])
    building.aggregate_building_events("2028100045", "DOB", "Violation")
    cypher, params = reads.calls[0]
    assert params["source"] == "DOB" and params["type"] == "Violation"
    assert "e.source_name = $source" in cypher


def test_aggregate_building_events_invalid_pair(patch_building):
    patch_building()
    out = building.aggregate_building_events("2028100045", "DOB", "Complaint")
    assert out["error"] == "invalid_event_filter"


def test_aggregate_building_events_guard(patch_building):
    reads = patch_building([{"status": "Open", "cls": "C", "c": 1}])
    building.aggregate_building_events("2028100045", "HPD", "Violation", violation_class="C", since_months=6)
    cypher_guard.assert_read_only(reads.calls[0][0])


# -- portfolio tools -------------------------------------------------------


@pytest.fixture
def patch_lp(monkeypatch):
    def _install(*record_sets):
        reads = _Reads(*record_sets)
        monkeypatch.setattr(lp, "read", reads)
        return reads

    return _install


def test_portfolio_summary_reads_precomputed_not_recomputed(patch_lp):
    reads = patch_lp([{"portfolio_id": "PF-1", "member_count": 111, "building_count": 297,
                       "residential_units": 22774, "method": "GDS WCC+Louvain",
                       "run_id": "R", "generated_at": "2026-07-29T00:00:00Z"}])
    out = lp.portfolio_summary("PF-1")
    assert out["building_count"] == 297 and out["residential_units"] == 22774
    # P3-6: it must READ the stored figure, never recompute from members.
    cypher = reads.calls[0][0]
    assert "IN_PORTFOLIO" not in cypher and "count(" not in cypher


def test_portfolio_summary_not_found(patch_lp):
    patch_lp()
    assert lp.portfolio_summary("PF-x")["found"] is False


def test_portfolio_by_borough_sums(patch_lp):
    patch_lp([{"portfolio_id": "PF-1", "building_count": 297, "by_borough": [
        {"borough": "Manhattan", "count": 282}, {"borough": "Brooklyn", "count": 14},
        {"borough": "Queens", "count": 1}]}])
    out = lp.portfolio_buildings_by_borough("PF-1")
    assert out["total_buildings"] == 297
    assert out["by_borough"]["Manhattan"] == 282


# -- aggregate_landlord_portfolio_events ----------------------------------


def test_agg_portfolio_requires_exactly_one_scope(patch_lp):
    patch_lp()
    assert lp.aggregate_landlord_portfolio_events(source_name="HPD")["error"] == "scope_required"
    assert lp.aggregate_landlord_portfolio_events(
        actor_id="A", portfolio_id="P", source_name="HPD")["error"] == "scope_required"


def test_agg_portfolio_infers_single_event_type(patch_lp):
    # ECB emits only Judgment — event_type may be omitted, and a coverage note
    # discloses the partial hazard-scheme coverage.
    reads = patch_lp([{"n": 384}], [{"status": "ACTIVE", "cls": "CLASS - 1", "c": 1739}])
    out = lp.aggregate_landlord_portfolio_events(actor_id="ACT-LL-42357", source_name="ECB")
    assert out["event_type"] == "Judgment"
    assert out["total"] == 1739
    assert "coverage_note" in out


def test_agg_portfolio_ambiguous_type_requires_it(patch_lp):
    # HPD emits several types; omitting event_type is an error.
    reads = patch_lp([{"n": 1}])
    out = lp.aggregate_landlord_portfolio_events(portfolio_id="P", source_name="HPD")
    assert out["error"] == "invalid_event_filter"


def test_agg_portfolio_scope_and_guard(patch_lp):
    reads = patch_lp([{"n": 297}], [{"status": "Open", "cls": "C", "c": 10}])
    out = lp.aggregate_landlord_portfolio_events(
        portfolio_id="PF-1", source_name="HPD", event_type="Violation", since_years=2)
    assert out["scope"] == "portfolio" and out["scope_building_count"] == 297
    # The aggregation query (second call) is guard-clean and scoped by IN_PORTFOLIO.
    agg_cypher = reads.calls[1][0]
    cypher_guard.assert_read_only(agg_cypher)
    assert "IN_PORTFOLIO" in agg_cypher
    assert out[RELIABILITY_KEY]["type"] == ReliabilityType.TYPE_II.value
