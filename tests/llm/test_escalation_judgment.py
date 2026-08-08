"""Escalation judgment — does a vetted agent *reserve* the deep investigation for
genuinely investigative questions, without over-escalating simple lookups or
treating a "not found" as a failure to route around?

Run with ``pytest -m llm``. The deep investigation is **stubbed** to a trivial
report, so this measures the model's ROUTING decision cheaply — no real (slow,
costly) investigation runs. Structural assertions on tool calls, never prose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.graph import build_agent
from watchline.discovery.agent.tools import investigation

pytestmark = pytest.mark.llm

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"

_FAKE_REPORT = {
    "narrative": "stub", "findings": [], "priority": None, "suggested_focus": None,
    "citations": [], "web_sources": [], "tool_call_count": 1, "truncated": False,
}


@pytest.fixture(scope="module")
def anchors() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["anchors"]


@pytest.fixture(autouse=True)
def stub_deep(monkeypatch):
    """Make a deep_investigation call instant, so escalation is cheap to observe."""
    monkeypatch.setattr(investigation, "run_investigation", lambda *a, **k: dict(_FAKE_REPORT))

    async def _arun(*a, **k):
        return dict(_FAKE_REPORT)

    monkeypatch.setattr(investigation, "arun_investigation", _arun)


@pytest.fixture
def agent():
    return build_agent()


def _config(thread: str) -> dict:
    return {"configurable": {"trust_level": "vetted", "thread_id": thread}}


def _calls(state) -> list[str]:
    return [c["name"] for m in state["messages"] for c in (getattr(m, "tool_calls", None) or [])]


def _run(agent, text, thread):
    return agent.invoke({"messages": [{"role": "user", "content": text}]}, config=_config(thread))


def test_simple_lookup_does_not_escalate(agent, anchors):
    bbl = anchors["building_with_apparent_control"]["bbl"]
    calls = _calls(_run(agent, f"How many residential units are in the building at BBL {bbl}?", "ej-1"))
    assert "deep_investigation" not in calls
    assert "lookup_building" in calls


def test_aggregate_does_not_escalate(agent, anchors):
    bbl = anchors["building_open_hpd_class_c"]["bbl"]
    calls = _calls(_run(agent, f"How many open HPD violations does BBL {bbl} have?", "ej-2"))
    assert "deep_investigation" not in calls


def test_not_found_answer_does_not_escalate(agent, anchors):
    """A building with no apparent controller is a complete answer — the model
    must report it, not escalate hoping for a different result."""
    bbl = anchors["building_without_apparent_control"]["bbl"]
    calls = _calls(_run(agent, f"Who apparently controls the building at BBL {bbl}?", "ej-3"))
    assert "deep_investigation" not in calls
    assert "lookup_building_ownership" in calls


def test_investigative_query_escalates(agent, anchors):
    """A portfolio-wide pattern question is what the deep investigation is for."""
    a = anchors["landlord_with_portfolio"]
    calls = _calls(_run(
        agent,
        f"Investigate patterns of systemic neglect across landlord {a['actor_id']} "
        f"({a['name']})'s whole portfolio and rank the worst-condition buildings.",
        "ej-4"))
    assert "deep_investigation" in calls


# --- the gray zone: a Tier-3 tool already answers it — don't over-escalate ---

def test_portfolio_violations_use_tier3_not_deep(agent, anchors):
    """"Which portfolio buildings have open violations" is a single Tier-3 tool,
    not a reason to run a full investigation."""
    a = anchors["landlord_with_portfolio"]
    calls = _calls(_run(
        agent,
        f"Which buildings in landlord {a['actor_id']}'s portfolio have open "
        "violations, and how many does each have?", "ej-5"))
    assert "deep_investigation" not in calls
    assert "portfolio_buildings_with_violations" in calls


def test_control_network_uses_tier3_not_deep(agent, anchors):
    pid = anchors["portfolio_multi_member"]["portfolio_id"]
    calls = _calls(_run(
        agent, f"Show the apparent-control network for portfolio {pid}.", "ej-6"))
    assert "deep_investigation" not in calls
    assert "control_network" in calls
