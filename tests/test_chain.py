"""Hermetic tests for trace_ownership_chain."""

from __future__ import annotations

import pytest

from watchline.discovery.agent import cypher_guard
from watchline.discovery.agent.db import ReadResult
from watchline.discovery.agent.reliability import ReliabilityType
from watchline.discovery.agent.tools import chain


@pytest.fixture
def patch(monkeypatch):
    def _install(row):
        captured: dict[str, object] = {}

        def fake_read(cypher, params=None, **kwargs):
            captured["cypher"] = cypher
            captured["params"] = params
            return ReadResult(records=[] if row is None else [row], truncated=False, row_cap=1000)

        monkeypatch.setattr(chain, "read", fake_read)
        return captured

    return _install


def _events():
    return [
        {"event_id": "D1", "event_type": "DeedTransfer", "event_date": "1974-10-01",
         "doc_type": "DEED", "refs": []},
        {"event_id": "M1", "event_type": "Mortgage", "event_date": "2002-12-20",
         "doc_type": "MTGE", "refs": [{"event_type": "MortgageSatisfaction", "event_id": "S1", "event_date": "2005-05-23"}]},
        {"event_id": "M2", "event_type": "Mortgage", "event_date": "2010-01-01",
         "doc_type": "MTGE", "refs": []},
    ]


def test_outstanding_derived_from_references(patch):
    patch({"bbl": "1018470015", "events": _events()})
    out = chain.trace_ownership_chain("1018470015")
    by_id = {m["event_id"]: m for m in out["mortgages"]}
    # M1 has a MortgageSatisfaction referencing it → satisfied.
    assert by_id["M1"]["outstanding"] is False and by_id["M1"]["status"] == "satisfied"
    # M2 has none → still outstanding.
    assert by_id["M2"]["outstanding"] is True and by_id["M2"]["status"] == "outstanding"


def test_summary_counts(patch):
    patch({"bbl": "1018470015", "events": _events()})
    out = chain.trace_ownership_chain("1018470015")
    assert out["summary"]["deed_count"] == 1
    assert out["summary"]["mortgage_count"] == 2
    assert out["summary"]["outstanding_mortgage_count"] == 1
    assert out["summary"]["latest_deed_date"] == "1974-10-01"


def test_deeds_and_mortgages_separated(patch):
    patch({"bbl": "1018470015", "events": _events()})
    out = chain.trace_ownership_chain("1018470015")
    assert all(d["event_type"] == "DeedTransfer" for d in out["deeds"])
    assert all(m["event_type"] == "Mortgage" for m in out["mortgages"])


def test_invalid_and_not_found(patch):
    patch(None)
    assert chain.trace_ownership_chain("nope")["found"] is False
    assert chain.trace_ownership_chain("1018470015")["found"] is False


def test_type_i_and_guard(patch):
    cap = patch({"bbl": "1018470015", "events": []})
    chain.trace_ownership_chain("1018470015")
    cypher_guard.assert_read_only(cap["cypher"])
    assert chain.trace_ownership_chain.reliability.type is ReliabilityType.TYPE_I
