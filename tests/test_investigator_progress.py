"""Hermetic tests for investigator progress streaming — no model, no graph.

Covers the config-threading + custom progress channel: sanitized events fire, the
report contract is unchanged, `recursion_limit` is forced, the writer no-ops
outside a stream, truncation is preserved, and the tool injects `config` without
exposing it. See ``specs/2026-08-04-investigator-progress``.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from watchline.discovery.agent import investigator
from watchline.discovery.agent.investigator import PROGRESS_EVENT


class _FakeAgent:
    """A sub-agent whose ``stream`` replays scripted ``(namespace, values)`` chunks."""

    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self, inputs, config=None, stream_mode=None, subgraphs=None):
        return iter(self._chunks)


class _FakeAsyncAgent:
    """Async twin — replays the same chunks through ``astream``."""

    def __init__(self, chunks):
        self._chunks = chunks

    async def astream(self, inputs, config=None, stream_mode=None, subgraphs=None):
        for chunk in self._chunks:
            yield chunk


def _transcript_chunks():
    call = AIMessage(
        "", tool_calls=[{"name": "lookup_building_events",
                         "args": {"bbl": "2028100045", "source_name": "HPD"}, "id": "1"}])
    result = ToolMessage(
        content=json.dumps({"found": True, "source_name": "HPD", "events": [1, 2, 3]}),
        name="lookup_building_events", tool_call_id="1")
    final = AIMessage('Conditions are concentrated.\n'
                      '{"findings": ["3 open"], "priority": "high", "suggested_focus": "AEP"}')
    # values mode accumulates the message list each step; the last is the final state.
    return [
        ((), {"messages": [HumanMessage("investigate")]}),
        ((), {"messages": [HumanMessage("investigate"), call]}),
        ((), {"messages": [HumanMessage("investigate"), call, result]}),
        ((), {"messages": [HumanMessage("investigate"), call, result, final]}),
    ]


@pytest.fixture
def captured_events(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(investigator, "_progress_writer", lambda: events.append)
    return events


def test_progress_events_fire_sanitized(captured_events, monkeypatch):
    monkeypatch.setattr(investigator, "build_investigator", lambda: _FakeAgent(_transcript_chunks()))

    investigator.run_investigation("q", {})

    kinds = [e["kind"] for e in captured_events]
    assert "tool_call" in kinds and "tool_result" in kinds
    call_event = next(e for e in captured_events if e["kind"] == "tool_call")
    assert call_event["type"] == PROGRESS_EVENT
    assert call_event["tool"] == "lookup_building_events"
    assert "2028100045" in call_event["summary"] and "HPD" in call_event["summary"]
    # No raw result body ever leaves the tool — only names, summaries, and sizes.
    result_event = next(e for e in captured_events if e["kind"] == "tool_result")
    assert result_event["row_count"] == 3
    assert not any(k in e for e in captured_events for k in ("result", "content", "rows", "events"))


def test_async_path_emits_progress_and_extracts_report(captured_events, monkeypatch):
    """The async twin (used by the server) shares the isolation + emit path."""
    import asyncio

    monkeypatch.setattr(investigator, "build_investigator",
                        lambda: _FakeAsyncAgent(_transcript_chunks()))

    report = asyncio.run(investigator.arun_investigation("q", {}))

    assert report["narrative"] == "Conditions are concentrated."
    assert {e["kind"] for e in captured_events} & {"tool_call", "tool_result"}


def test_report_contract_unchanged_when_streaming(monkeypatch):
    monkeypatch.setattr(investigator, "build_investigator", lambda: _FakeAgent(_transcript_chunks()))

    report = investigator.run_investigation("q", {})

    assert report["narrative"] == "Conditions are concentrated."
    assert report["findings"] == ["3 open"]
    assert report["priority"] == "high"
    assert {c["tool"] for c in report["citations"]} == {"lookup_building_events"}


def test_sub_config_forces_recursion_limit_and_keeps_callbacks():
    merged = investigator._sub_config(
        {"callbacks": ["cb"], "recursion_limit": 999, "configurable": {"thread_id": "t"}})
    assert merged["recursion_limit"] == investigator.RECURSION_LIMIT
    assert merged["callbacks"] == ["cb"]
    assert merged["configurable"] == {"thread_id": "t"}
    assert investigator._sub_config(None)["recursion_limit"] == investigator.RECURSION_LIMIT


def test_progress_writer_noops_outside_a_stream():
    writer = investigator._progress_writer()
    assert callable(writer)
    writer({"type": PROGRESS_EVENT, "kind": "tool_call"})  # must not raise


def test_truncation_emits_event_and_returns_truncated_report(captured_events, monkeypatch):
    class _Boom:
        def stream(self, *a, **k):
            raise GraphRecursionError("too deep")

    monkeypatch.setattr(investigator, "build_investigator", lambda: _Boom())
    out = investigator.run_investigation("q", {})

    assert out["truncated"] is True and out["narrative"]
    assert any(e["kind"] == "truncated" for e in captured_events)


def test_tool_exposes_no_config_arg():
    """The model never sees a config knob — the run context propagates via
    contextvars, not a tool parameter."""
    from watchline.discovery.agent.tools.registry import tool_by_name

    tool = tool_by_name("deep_investigation")
    assert "config" not in tool.args
    assert set(tool.args) >= {"question", "bbl", "actor_id", "portfolio_id", "borough"}


def test_sub_config_is_clean_not_ambient():
    """The sub-agent gets a clean config — only ``recursion_limit`` — so it never
    inherits the parent's checkpoint/step accounting (which would truncate it
    early). Callbacks/trace still nest via contextvars, not via this config."""
    assert investigator._sub_config(None) == {"recursion_limit": investigator.RECURSION_LIMIT}
    # An explicit config (tests only) is preserved, with recursion_limit forced.
    pinned = investigator._sub_config({"tags": ["t"], "recursion_limit": 999})
    assert pinned["tags"] == ["t"]
    assert pinned["recursion_limit"] == investigator.RECURSION_LIMIT


def test_threaded_config_cannot_change_the_investigator_tool_set():
    """Isolation (IP-5): the sub-agent's tools are built independently of any
    threaded config, so config can never add a tool or reach the gated one."""
    tools = {t.name for t in investigator._investigator_tools()}
    assert "deep_investigation" not in tools
    assert tools == {t.name for t in investigator._investigator_tools()}
