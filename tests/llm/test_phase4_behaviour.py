"""Phase 4 agent behaviour with a real model — Tier 3 traversals + compare.

Run with ``pytest -m llm``. Asserts on tool invocation and payload, never prose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.graph import build_agent

pytestmark = pytest.mark.llm

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def agent():
    return build_agent()


def _run(agent, text, thread):
    return agent.invoke({"messages": [{"role": "user", "content": text}]},
                        config={"configurable": {"trust_level": "public", "thread_id": thread}})


def _tool_calls(state) -> list[str]:
    return [c["name"] for m in state["messages"] for c in (getattr(m, "tool_calls", None) or [])]


def test_mortgage_history_calls_trace_ownership_chain(agent, fixtures):
    bbl = fixtures["anchors"]["building_with_mortgage_chain"]["bbl"]
    state = _run(agent, f"Trace the deed and mortgage history of BBL {bbl}.", "p4-1")
    assert "trace_ownership_chain" in _tool_calls(state)


def test_registered_vs_owner_calls_the_diff(agent, fixtures):
    bbl = fixtures["anchors"]["building_registered_and_controlled"]["bbl"]
    state = _run(agent, f"Does the registered landlord match the recorded owner for BBL {bbl}?", "p4-2")
    assert "ownership_vs_registration_diff" in _tool_calls(state)


def test_control_network_question(agent, fixtures):
    pid = fixtures["anchors"]["portfolio_multi_member"]["portfolio_id"]
    state = _run(agent, f"Show the apparent-control network for portfolio {pid}.", "p4-3")
    assert "control_network" in _tool_calls(state)


def test_compare_question_aligns_without_summing(agent, fixtures):
    a = fixtures["anchors"]["building_with_apparent_control"]["bbl"]
    b = fixtures["anchors"]["building_open_hpd_class_c"]["bbl"]
    state = _run(agent, f"Compare the HPD violation counts of BBL {a} and BBL {b}.", "p4-4")
    assert "compare_entities" in _tool_calls(state)
    for m in state["messages"]:
        if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "compare_entities":
            payload = json.loads(m.content) if isinstance(m.content, str) else m.content
            assert payload["count"] == 2
            assert "total" not in payload  # aligned per entity, never summed
