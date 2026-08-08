"""Hermetic tests for portfolio_buildings_with_violations and portfolio_litigation."""

from __future__ import annotations

import pytest

from watchline.discovery.agent import cypher_guard
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import ReliabilityType
from watchline.discovery.agent.tools import portfolio_detail as pd


@pytest.fixture
def patch(monkeypatch):
    def _install(row):
        captured: dict[str, object] = {}

        def fake_read(cypher, params=None, **kwargs):
            captured["cypher"] = cypher
            captured["params"] = params
            return ReadResult(records=[] if row is None else [row], truncated=False, row_cap=1000)

        monkeypatch.setattr(pd, "read", fake_read)
        return captured

    return _install


# -- portfolio_buildings_with_violations -----------------------------------


def test_violations_uses_vocab_open_and_hazard(patch):
    cap = patch({"buildings": [
        {"bbl": "1", "address": "A", "borough": "M", "open_hazard_violations": 5},
        {"bbl": "2", "address": "B", "borough": "M", "open_hazard_violations": 0}]})
    out = pd.portfolio_buildings_with_violations(portfolio_id="PF-1")
    assert out["summary"]["building_count"] == 2
    assert out["summary"]["buildings_with_open_hazard_violations"] == 1
    assert out["summary"]["total_open_hazard_violations"] == 5
    # Vocab fragments, not raw equality; Class I excluded (hazard filter).
    assert "toUpper(e.status)" in cap["cypher"]
    assert "toUpper(e.violation_class)" in cap["cypher"]


def test_violations_status_and_hazard_params_distinct(patch):
    # Regression: the open-status filter and the hazard-class filter both used
    # the default param 'vals', so $vals_exact collided and every count came back
    # 0. They must use distinct params (openv / hazv).
    cap = patch({"buildings": [{"bbl": "1", "address": "A", "borough": "M", "open_hazard_violations": 5}]})
    pd.portfolio_buildings_with_violations(portfolio_id="PF-1")
    assert cap["params"]["openv_exact"] == ["OPEN"]
    assert sorted(cap["params"]["hazv_exact"]) == ["A", "B", "C"]


def test_violations_requires_one_scope(patch):
    patch(None)
    assert pd.portfolio_buildings_with_violations()["error"] == "scope_required"


def test_violations_landlord_scope_unwinds_bbls(patch):
    cap = patch({"buildings": [{"bbl": "1", "address": "A", "borough": "M", "open_hazard_violations": 1}]})
    pd.portfolio_buildings_with_violations(actor_id="ACT-LL-42357")
    assert "UNWIND l.bbls" in cap["cypher"]
    assert cap["params"]["scope_id"] == "ACT-LL-42357"


# -- portfolio_litigation --------------------------------------------------


def test_litigation_canonicalizes_status_and_counts(patch):
    patch({"filings": [
        {"bbl": "3051210012", "address": "A", "event_id": "E1", "case_type": "Heat and Hot Water",
         "status_raw": "CLOSED - 02/08/2022", "date": "2022-02-08", "parties": ["X"]},
        {"bbl": "3051210012", "address": "A", "event_id": "E2", "case_type": "Tenant Action",
         "status_raw": "Pending", "date": "2023-01-01", "parties": ["Y"]}]})
    out = pd.portfolio_litigation(portfolio_id="PF-1")
    assert out["summary"]["filing_count"] == 2
    assert out["summary"]["building_count"] == 1  # both filings, one building
    statuses = {f["status"] for f in out["filings"]}
    assert statuses == {"CLOSED", "PENDING"}  # canonicalized, date stripped
    assert all("case_type_scheme" in f for f in out["filings"])


def test_litigation_empty_is_a_normal_answer(patch):
    patch({"filings": []})
    out = pd.portfolio_litigation(portfolio_id="PF-1")
    assert out["found"] is True and out["summary"]["filing_count"] == 0


def test_type_ii_and_guard(patch):
    cap = patch({"buildings": [{"bbl": "1", "address": "A", "borough": "M", "open_hazard_violations": 1}]})
    pd.portfolio_buildings_with_violations(portfolio_id="PF-1")
    cypher_guard.assert_read_only(cap["cypher"])
    assert pd.portfolio_buildings_with_violations.reliability.type is ReliabilityType.TYPE_II
    assert pd.portfolio_litigation.reliability.type is ReliabilityType.TYPE_II
