"""Phase 3 agent behaviour with a real model — breadth tools + re-query.

Run with ``pytest -m llm``. Asserts on tool invocation and payload, never prose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.graph import build_agent

pytestmark = pytest.mark.llm

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"

#: Tools that answer "how many events / which events" for a building — the model
#: may reasonably pick either the lookup or the aggregate.
_EVENT_TOOLS = {"lookup_building_events", "aggregate_building_events"}


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def agent():
    return build_agent()


def _config(thread: str) -> dict:
    return {"configurable": {"trust_level": "public", "thread_id": thread}}


def _run(agent, text, thread, carry=None):
    state = {"messages": [{"role": "user", "content": text}]}
    if carry:
        state.update(carry)
    return agent.invoke(state, config=_config(thread))


def _tool_calls(state) -> list[str]:
    return [c["name"] for m in state["messages"] for c in (getattr(m, "tool_calls", None) or [])]


def test_units_question_calls_lookup_building(agent, fixtures):
    a = fixtures["anchors"]["building_with_apparent_control"]
    state = _run(agent, f"How many residential units are in the building at BBL {a['bbl']}?", "u1")
    assert "lookup_building" in _tool_calls(state)


def test_borough_time_question_calls_geo_time(agent):
    state = _run(agent, "How many eviction filings were there in the Bronx in 2025?", "g1")
    assert "aggregate_events_by_geo_time" in _tool_calls(state)


def test_violation_question_constrains_source(agent, fixtures):
    a = fixtures["anchors"]["building_open_hpd_class_c"]
    state = _run(agent, f"How many open HPD violations does BBL {a['bbl']} have?", "v1")
    calls = _tool_calls(state)
    assert _EVENT_TOOLS & set(calls)
    # Whichever event tool it called, it must have passed the HPD source.
    for m in state["messages"]:
        for c in (getattr(m, "tool_calls", None) or []):
            if c["name"] in _EVENT_TOOLS:
                assert c["args"].get("source_name") == "HPD"


def test_deterministic_requery_on_new_filter(agent, fixtures):
    """A refinement whose answer is NOT in the prior result issues a fresh,
    source-constrained tool call rather than a fabricated number (CLAUDE.md
    re-query discipline). Asking about DOB after HPD cannot be read off the HPD
    payload, so a new call with the DOB source is the correct behaviour.
    """
    a = fixtures["anchors"]["building_open_hpd_class_c"]
    turn1 = _run(agent, f"How many HPD violations does BBL {a['bbl']} have in total?", "rq1")
    assert _EVENT_TOOLS & set(_tool_calls(turn1))

    # Thread the full conversation (as a checkpointer would) so "it" has a
    # referent, then ask for a source the HPD payload cannot answer.
    carry = {k: turn1[k] for k in ("focus_entities", "last_result", "slot_touched_at")
             if turn1.get(k) is not None}
    turn2 = agent.invoke(
        {**carry, "messages": turn1["messages"] + [
            {"role": "user", "content": "And how many DOB violations does it have?"}]},
        config=_config("rq1"))
    # A fresh event-tool call, constrained to the DOB source, in turn 2.
    dob_call = False
    for m in turn2["messages"]:
        for c in (getattr(m, "tool_calls", None) or []):
            if c["name"] in _EVENT_TOOLS and c["args"].get("source_name") == "DOB":
                dob_call = True
    assert dob_call
