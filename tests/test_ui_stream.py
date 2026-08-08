"""Hermetic tests for the UI stream glue (ui/stream.py) — no Streamlit, no agent.

Canned ``(mode, payload)`` chunks mimic the shapes verified against the live
agent, so the mapping and evidence extraction are pinned deterministically.
"""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace as NS

import pytest

from watchline.discovery.ui import stream
from watchline.discovery.ui.cost import Cost
from watchline.discovery.ui.stream import (
    Answer, Evidence, ToolResult, ToolStart, Token, display_safe, extract_evidence,
    run_turn, to_markdown,
)


class _FakeAgent:
    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self, inputs, config=None, stream_mode=None):
        return iter(self._chunks)


def _msg_chunk(text=None, block=None, node="model"):
    """A ('messages', (chunk, metadata)) tuple."""
    if text is not None:
        content = [{"type": "text", "text": text}]
    elif block is not None:
        content = [block]
    else:
        content = []
    return ("messages", (NS(content=content), {"langgraph_node": node}))


def _ownership_chunks():
    ai_call = NS(type="ai", content=[],
                 tool_calls=[{"name": "lookup_building_ownership",
                              "args": {"bbl": "1000050010"}, "id": "1"}])
    tool_msg = NS(type="tool", name="lookup_building_ownership", content=json.dumps({
        "found": True, "bbl": "1000050010",
        "apparent_controllers": [
            {"name": "PETER HUNGERFORD", "provenance": {"method": "network", "run_id": "run-7"}}],
        "reliability": {"type": "II", "caveats": [
            {"element": "apparent_control", "kind": "inference",
             "text": "Apparent control is inferred from the graph, not a legal finding."}]},
        "raw_record": "RAW BLOB THAT MUST NOT LEAK",
    }))
    final_ai = NS(type="ai", tool_calls=[],
                  content=[{"type": "text", "text": "Recorded owner is 25 WATER OWNER LLC; "
                            "apparent controller PETER HUNGERFORD."}])
    return [
        ("updates", {"SessionStateMiddleware.before_model": {"resolved_reference": None}}),
        _msg_chunk(text=""),                                    # empty content -> no Token
        _msg_chunk(block={"id": "x", "type": "tool_use"}),      # tool_use -> no Token
        ("updates", {"model": {"messages": [ai_call]}}),
        ("updates", {"tools": {"messages": [tool_msg]}}),
        _msg_chunk(text="Recorded owner"),
        _msg_chunk(text=" is 25 WATER OWNER LLC."),
        ("updates", {"model": {"messages": [final_ai]}}),
        ("updates", {"SessionStateMiddleware.after_model": {"last_result": None}}),
    ]


def _events(chunks):
    return list(run_turn(_FakeAgent(chunks), "q", {}))


def _answer(events):
    """The Answer event — no longer last, since a terminal Cost follows it."""
    return next(e for e in events if isinstance(e, Answer))


def test_stream_module_imports_no_streamlit():
    assert "streamlit" not in inspect.getsource(stream)


def test_tier1_turn_maps_to_events():
    events = _events(_ownership_chunks())

    tokens = [e for e in events if isinstance(e, Token)]
    assert [t.text for t in tokens] == ["Recorded owner", " is 25 WATER OWNER LLC."]

    starts = [e for e in events if isinstance(e, ToolStart)]
    assert len(starts) == 1 and starts[0].name == "lookup_building_ownership"
    assert "1000050010" in starts[0].summary and starts[0].depth == 0

    results = [e for e in events if isinstance(e, ToolResult)]
    assert len(results) == 1 and results[0].name == "lookup_building_ownership"

    answer = _answer(events)
    assert answer.text == ("Recorded owner is 25 WATER OWNER LLC; "
                           "apparent controller PETER HUNGERFORD.")


def test_tier1_evidence_is_extracted_and_sanitized():
    answer = _answer(_events(_ownership_chunks()))
    ev = answer.evidence

    assert [c["element"] for c in ev.caveats] == ["apparent_control"]
    assert ev.caveats[0]["text"].startswith("Apparent control is inferred")
    assert any(c["run_id"] == "run-7" for c in ev.citations)
    # The raw record never leaves the tool.
    assert "RAW BLOB THAT MUST NOT LEAK" not in repr(answer)
    assert all("raw_record" not in c for c in ev.citations + ev.caveats)


def test_custom_progress_nests_under_the_deep_call():
    chunks = [
        ("custom", {"type": "investigation_progress", "kind": "tool_call",
                    "step": 1, "tool": "run_cypher", "summary": "MATCH …", "depth": 0}),
        ("custom", {"type": "investigation_progress", "kind": "tool_result",
                    "step": 1, "tool": "run_cypher", "row_count": 41, "depth": 0}),
        ("custom", {"type": "investigation_progress", "kind": "truncated", "step": 2}),
    ]
    events = _events(chunks)
    start = next(e for e in events if isinstance(e, ToolStart))
    assert start.name == "run_cypher" and start.depth == 1        # 0 + 1: nested
    result = next(e for e in events if isinstance(e, ToolResult) and e.name == "run_cypher")
    assert result.detail == "41 row(s)" and result.depth == 1
    assert any(isinstance(e, ToolResult) and "step limit" in e.detail for e in events)


def test_deep_investigation_evidence_keeps_web_sources_separate():
    report = NS(type="tool", name="deep_investigation", content=json.dumps({
        "narrative": "…", "citations": [{"tool": "lookup_building_events", "args": {"bbl": "1"}}],
        "web_sources": [{"title": "ACME LLC filing", "url": "https://example.com/x"}],
        "reliability": {"type": "IV", "caveats": [
            {"element": "apparent_control", "kind": "inference", "text": "web-sourced, low confidence"}]},
    }))
    ev = extract_evidence([report], None)
    assert ev.web_sources == [{"title": "ACME LLC filing", "url": "https://example.com/x"}]
    assert any(c["tool"].startswith("deep_investigation →") for c in ev.citations)
    assert any(c["element"] == "apparent_control" for c in ev.caveats)


def test_web_searches_with_no_sources_surface_a_note():
    """A deep run that searched but found nothing carries a count, so the panel
    can say so instead of showing a bare, urless 'source'."""
    report = NS(type="tool", name="deep_investigation", content=json.dumps({
        "narrative": "…", "citations": [], "web_sources": [], "web_search_count": 2,
    }))
    ev = extract_evidence([report], None)
    assert ev.web_sources == []
    assert ev.web_searches == 2
    assert not ev.is_empty                     # the note makes the panel non-empty
    md = to_markdown("q", "a", ev)
    assert "Web searches performed: 2 (no sources returned)" in md


def test_same_caveat_from_two_tools_shows_once():
    """Caveat text is canonical per element; two tools carrying it dedupe to one."""
    caveat = {"element": "apparent_control", "kind": "inference", "text": "inferred, not legal"}
    rel = {"type": "II", "caveats": [caveat]}
    a = NS(type="tool", name="lookup_building_ownership", content=json.dumps({"reliability": rel}))
    b = NS(type="tool", name="ownership_vs_registration_diff", content=json.dumps({"reliability": rel}))
    ev = extract_evidence([a, b], None)
    assert len(ev.caveats) == 1
    assert ev.caveats[0]["element"] == "apparent_control"


def test_resolved_reference_is_surfaced():
    chunks = [
        ("updates", {"SessionStateMiddleware.before_model":
                     {"resolved_reference": {"via": "indexed", "type": "landlord", "id": "ACT-2"}}}),
        ("updates", {"model": {"messages": [NS(type="ai", tool_calls=[], content="ok")]}}),
    ]
    answer = _answer(_events(chunks))
    assert answer.evidence.resolved_reference == {"via": "indexed", "type": "landlord", "id": "ACT-2"}
    assert not answer.evidence.is_empty


def test_empty_evidence_reports_itself():
    chunks = [("updates", {"model": {"messages": [NS(type="ai", tool_calls=[], content="hi")]}})]
    answer = _answer(_events(chunks))
    assert answer.text == "hi" and answer.evidence.is_empty


def test_run_turn_emits_terminal_cost_from_usage():
    """A model message carrying usage_metadata yields a terminal Cost, strictly
    after the Answer, with the cache-aware estimate."""
    ai = NS(type="ai", tool_calls=[], content=[{"type": "text", "text": "hi"}],
            usage_metadata={"input_tokens": 1000, "output_tokens": 200,
                            "input_token_details": {"cache_read": 0}},
            response_metadata={"model": "claude-haiku-4-5"})
    events = _events([("updates", {"model": {"messages": [ai]}})])

    assert isinstance(events[-1], Cost)                     # strictly last
    assert isinstance(_answer(events), Answer)              # Answer precedes it
    # (1000 * $1/M input + 200 * $5/M output) = $0.002.
    assert events[-1].usd == pytest.approx((1000 * 1.0 + 200 * 5.0) / 1_000_000)
    assert events[-1].usage.input_tokens == 1000


def test_deep_investigation_usage_folds_into_cost():
    """A Tier-4 ``kind:"usage"`` custom event rolls into the turn Cost and
    populates ``deep_usd`` (the sub-agent's calls never reach the parent stream)."""
    top = NS(type="ai", tool_calls=[], content=[{"type": "text", "text": "done"}],
             usage_metadata={"input_tokens": 1000, "output_tokens": 100,
                             "input_token_details": {}},
             response_metadata={"model": "claude-haiku-4-5"})
    chunks = [
        ("updates", {"model": {"messages": [top]}}),
        ("custom", {"type": "investigation_progress", "kind": "usage",
                    "input": 9000, "output": 1200, "cache_read": 0,
                    "cache_creation_5m": 0, "cache_creation_1h": 0,
                    "model": "claude-haiku-4-5"}),
    ]
    cost = _events(chunks)[-1]
    assert isinstance(cost, Cost)
    assert cost.deep_usd == pytest.approx((9000 * 1.0 + 1200 * 5.0) / 1_000_000)
    top_usd = (1000 * 1.0 + 100 * 5.0) / 1_000_000
    assert cost.usd == pytest.approx(top_usd + cost.deep_usd)   # top + deep


def test_to_markdown_includes_question_answer_and_evidence():
    ev = Evidence(
        caveats=[{"tool": "lookup_building_ownership", "element": "apparent_control",
                  "text": "inferred, not legal"}],
        citations=[{"tool": "lookup_building_ownership", "source_name": None, "run_id": "run-9"}],
        web_sources=[{"title": "ACME filing", "url": "https://example.com/x"}],
        resolved_reference={"type": "landlord", "id": "ACT-2", "via": "indexed"})
    md = to_markdown("Who owns BBL 1000050010?", "PETER HUNGERFORD apparently controls it.", ev)

    assert md.startswith("# Watchline NYC — Discovery")
    assert "**Question:** Who owns BBL 1000050010?" in md
    assert "PETER HUNGERFORD apparently controls it." in md
    assert "## Evidence" in md
    assert "run `run-9`" in md
    assert "_apparent_control_ — inferred, not legal" in md
    assert "[ACME filing](https://example.com/x)" in md
    assert "Resolved reference:" in md


def test_to_markdown_without_evidence_is_still_valid():
    md = to_markdown("q?", "an answer", Evidence())
    assert "**Question:** q?" in md and "an answer" in md
    assert "## Evidence" not in md  # nothing to show


def test_display_safe_escapes_dollars_only():
    # $…$ would otherwise render as KaTeX math in Streamlit.
    assert display_safe("a $5M fine and $8M restitution") == "a \\$5M fine and \\$8M restitution"
    # Already-escaped dollars aren't doubled.
    assert display_safe("cost \\$5") == "cost \\$5"
    # Other markdown is untouched; empty/None is safe.
    assert display_safe("# Heading **bold** _x_") == "# Heading **bold** _x_"
    assert display_safe("") == "" and display_safe(None) == ""
