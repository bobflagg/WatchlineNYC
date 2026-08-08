"""Hermetic tests for the Tier-4 investigator core — no model, no graph."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from watchline.discovery.agent import investigator
from watchline.discovery.agent.db import ReadResult


# -- run_cypher: the Type III guarded path --------------------------------


@pytest.fixture
def fake_read(monkeypatch):
    captured: dict[str, object] = {}

    def _read(cypher, parameters=None, **kwargs):
        captured["cypher"] = cypher
        captured["row_cap"] = kwargs.get("row_cap")
        return ReadResult(records=[{"a": 1}], truncated=False, row_cap=kwargs.get("row_cap", 200))

    monkeypatch.setattr(investigator, "read", _read)
    return captured


@pytest.mark.parametrize("bad", [
    "MATCH (b:Building) SET b.x = 1 RETURN b",
    "MATCH (b:Building) DETACH DELETE b",
    "CREATE (n:Building) RETURN n",
    "CALL apoc.periodic.iterate('a','b',{}) YIELD x RETURN x",
    "MATCH (b) RETURN b; MATCH (c) DELETE c",
    "",
])
def test_run_cypher_refuses_unsafe(bad, fake_read):
    out = investigator.run_cypher.invoke({"cypher": bad})
    assert out["refused"] is True
    assert "cypher" not in fake_read  # db.read never reached


def test_run_cypher_allows_reads_and_caps(fake_read):
    out = investigator.run_cypher.invoke({"cypher": "MATCH (b:Building) RETURN b.bbl LIMIT 5"})
    assert out["row_count"] == 1 and out["truncated"] is False
    assert fake_read["row_cap"] == investigator.RUN_CYPHER_ROW_CAP


def test_run_cypher_returns_execution_errors_as_feedback(monkeypatch):
    # A timeout or syntax error must be handed back, not raised — one bad query
    # must not sink the whole investigation.
    from neo4j.exceptions import ClientError

    def _boom(cypher, parameters=None, **kwargs):
        raise ClientError("transaction timed out")

    monkeypatch.setattr(investigator, "read", _boom)
    out = investigator.run_cypher.invoke({"cypher": "MATCH (n) RETURN n"})
    assert out["error"] is True and "rewrite it" in out["reason"].lower()


def test_sanitize_stringifies_non_json():
    import datetime
    out = investigator._sanitize({"d": datetime.date(2026, 5, 27), "n": 3, "l": [datetime.date(2020, 1, 1)]})
    assert out["d"] == "2026-05-27" and out["n"] == 3 and out["l"] == ["2020-01-01"]


# -- investigator tool set -------------------------------------------------


def test_investigator_has_run_cypher_and_not_the_gated_tool():
    names = [t.name for t in investigator._investigator_tools()]
    assert "run_cypher" in names
    assert "deep_investigation" not in names  # never recurse into itself
    # The Tier 1-3 library is present (spot-check a couple).
    assert "lookup_building_ownership" in names and "control_network" in names


# -- report extraction -----------------------------------------------------


def _web_result(results):
    """A web_search tool-result message in the shape the tool returns."""
    return ToolMessage(
        json.dumps({"query": "x", "provenance": "web (...)", "results": {"results": results}}),
        name="web_search", tool_call_id="2")


def test_extract_report_parses_trailer_and_citations():
    messages = [
        HumanMessage("investigate"),
        AIMessage("", tool_calls=[{"name": "lookup_building_ownership", "args": {"bbl": "1"}, "id": "1"}]),
        AIMessage("", tool_calls=[{"name": "web_search", "args": {"query": "x"}, "id": "2"}]),
        _web_result([{"title": "ACME LLC filing", "url": "https://example.com/acme", "content": "…"},
                     {"title": "News", "url": "https://news.example/story", "content": "…"}]),
        AIMessage('The portfolio shows concentrated hazards.\n'
                  '{"findings": ["12 buildings carry open Class C"], "priority": "high", "suggested_focus": "AEP"}'),
    ]
    report = investigator.extract_report(messages)
    assert report["priority"] == "high"
    assert report["findings"] == ["12 buildings carry open Class C"]
    assert report["suggested_focus"] == "AEP"
    assert report["narrative"] == "The portfolio shows concentrated hazards."
    # Graph citations are the graph tool calls; web_search is not among them.
    assert {c["tool"] for c in report["citations"]} == {"lookup_building_ownership"}
    # Web sources carry the retrieved URLs (from the result), not the query (the call).
    assert [w["url"] for w in report["web_sources"]] == [
        "https://example.com/acme", "https://news.example/story"]
    assert report["web_sources"][0]["title"] == "ACME LLC filing"
    # tool_call_count counts invocations (1 graph + 1 web search), not pages returned.
    assert report["tool_call_count"] == 2
    assert report["web_search_count"] == 1


def test_web_search_with_no_hits_adds_no_phantom_source():
    """A search that returned nothing must not leave a bare, urless 'source' row."""
    messages = [
        AIMessage("", tool_calls=[{"name": "web_search", "args": {"query": "x"}, "id": "2"}]),
        _web_result([]),
        AIMessage("No corroborating web hits."),
    ]
    report = investigator.extract_report(messages)
    assert report["web_sources"] == []
    assert report["tool_call_count"] == 1  # the search still counts as an invocation
    assert report["web_search_count"] == 1  # so the UI can note "1 search, no sources"


def test_extract_report_dedupes_web_sources_by_url():
    messages = [
        _web_result([{"title": "A", "url": "https://example.com/x"}]),
        _web_result([{"title": "A again", "url": "https://example.com/x"},
                     {"title": "B", "url": "https://example.com/y"}]),
        AIMessage("done"),
    ]
    report = investigator.extract_report(messages)
    assert [w["url"] for w in report["web_sources"]] == [
        "https://example.com/x", "https://example.com/y"]


def test_investigation_truncates_gracefully_on_recursion(monkeypatch):
    # A deep loop that hits the step limit must not crash the tool — it returns
    # an honest truncated report.
    from langgraph.errors import GraphRecursionError

    class _Boom:
        def stream(self, *a, **k):  # run_investigation streams, not invokes
            raise GraphRecursionError("too deep")

    monkeypatch.setattr(investigator, "build_investigator", lambda: _Boom())
    out = investigator.run_investigation("q", {})
    assert out["truncated"] is True and out["narrative"]


def test_extract_report_falls_back_to_narrative_only():
    messages = [AIMessage("A plain narrative with no JSON trailer.")]
    report = investigator.extract_report(messages)
    assert report["narrative"] == "A plain narrative with no JSON trailer."
    assert report["findings"] == [] and report["priority"] is None


# -- web_search (Type IV): budget + provenance ----------------------------


class _FakeSearch:
    def invoke(self, payload):
        return {"results": [{"title": "ACME LLC filing", "url": "https://example.com/x"}]}


@pytest.fixture
def fake_search(monkeypatch):
    monkeypatch.setattr(investigator, "_searches_used", 0)
    monkeypatch.setattr(investigator, "_search_client", lambda: _FakeSearch())


def test_web_search_only_in_investigator_not_the_public_library():
    from watchline.discovery.agent.tools.registry import all_tools

    assert "web_search" not in {t.name for t in all_tools()}  # never in the shared library
    assert "web_search" in [t.name for t in investigator._investigator_tools()]


def test_web_search_is_labelled_web_sourced(fake_search):
    out = investigator.web_search.invoke({"query": "who owns ACME LLC"})
    assert "web" in out["provenance"] and "not apparent control" in out["provenance"]
    assert out["results"]  # sanitized


def test_web_search_budget_is_enforced(fake_search):
    for _ in range(investigator.WEB_SEARCH_BUDGET):
        assert "exhausted" not in investigator.web_search.invoke({"query": "q"})
    # One past the budget:
    assert investigator.web_search.invoke({"query": "q"})["exhausted"] is True


def test_web_search_unavailable_without_a_client(monkeypatch):
    monkeypatch.setattr(investigator, "_searches_used", 0)
    monkeypatch.setattr(investigator, "_search_client", lambda: None)
    assert investigator.web_search.invoke({"query": "q"})["unavailable"] is True
