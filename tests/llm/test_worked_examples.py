"""Worked-example threads from CLAUDE.md — end-to-end, cheap (Phase 6, Group 2).

Two multi-turn threads run over the *wired* agent on the cheap model. Assertions
are structural — tool routing, resolved-reference metadata, caveat presence —
never model prose (CLAUDE.md §Testing). State is threaded manually across turns
as a checkpointer would, matching the existing multi-turn llm tests
(``test_phase2_behaviour``): each turn passes the prior turn's session slots, and
the ``SessionStateMiddleware`` re-injects the resolved reference as context.

* The routing turns are ``llm`` (Haiku) — cheap, since they only check which tool
  is called and what metadata travels.
* The one Tier-4 escalation turn is ``llm_deep`` (Sonnet) and excluded from a
  routine ``-m llm`` run — it drives a full investigation, so it is opt-in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.graph import build_agent

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"

#: Session slots a checkpointer would persist across turns of one thread.
_CARRY_KEYS = ("focus_entities", "last_result", "slot_touched_at", "disambiguation_history")


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def agent():
    return build_agent()


def _config(thread: str, trust: str = "public") -> dict:
    return {"configurable": {"trust_level": trust, "thread_id": thread}}


def _run(agent, text, thread, carry=None, trust="public"):
    state = {"messages": [{"role": "user", "content": text}]}
    if carry:
        state.update(carry)
    return agent.invoke(state, config=_config(thread, trust))


def _carry(state) -> dict:
    return {k: state[k] for k in _CARRY_KEYS if state.get(k) is not None}


def _tool_calls(state) -> list[str]:
    return [c["name"] for m in state["messages"] for c in (getattr(m, "tool_calls", None) or [])]


def _payload(state, tool):
    """The last payload for ``tool`` in this turn's messages, or ``None``."""
    found = None
    for m in state["messages"]:
        if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == tool:
            found = json.loads(m.content) if isinstance(m.content, str) else m.content
    return found


@pytest.mark.llm
def test_tier_escalation_thread_carries_reference_and_caveats(agent, fixtures):
    """CLAUDE.md worked example: a derived control finding (which must ship its
    caveat and establishes the building focus), escalate to its sister buildings
    via a demonstrative, then a source-constrained event count — the reference
    carries across every turn."""
    b = fixtures["anchors"]["building_with_apparent_control"]

    # Turn 1 (Tier 1, Type II) — the derived control answer carries its caveat
    # and establishes the building focus.
    t1 = _run(agent, f"Who owns the building at BBL {b['bbl']}, and how confident is that?", "wx-a")
    assert "lookup_building_ownership" in _tool_calls(t1)
    payload = _payload(t1, "lookup_building_ownership")
    assert payload is not None
    assert payload["reliability"]["type"] == "II"
    assert payload["reliability"]["caveats"], "the derived control answer must carry its caveat"
    if not (t1.get("focus_entities") or {}).get("building"):
        pytest.skip("turn 1 did not establish a building focus in this data")

    # Turn 2 (Tier 3) — escalate via "that building"; the reference must resolve.
    t2 = _run(agent, "What are the sister buildings of that building?", "wx-a", carry=_carry(t1))
    assert "sister_buildings" in _tool_calls(t2)
    ref = t2.get("resolved_reference")
    assert ref is not None, "the demonstrative turn should carry resolved-reference metadata"
    assert ref["type"] == "building"
    assert ref["id"] == b["bbl"]

    # Turn 3 (Tier 2) — a source-constrained event count on the same referent.
    t3 = _run(agent, "How many open HPD violations does that building have?", "wx-a", carry=_carry(t2))
    event_calls = {"lookup_building_events", "aggregate_building_events"}
    assert event_calls & set(_tool_calls(t3))
    for m in t3["messages"]:
        for c in (getattr(m, "tool_calls", None) or []):
            if c["name"] in event_calls:
                assert c["args"].get("source_name") == "HPD"  # never an unscoped query


@pytest.mark.llm_deep
def test_tier_escalation_reaches_the_deep_agent_when_vetted(agent, fixtures):
    """The same thread's investigative escalation: on a vetted config the model
    reaches ``deep_investigation`` (Sonnet; opt-in — this drives a full run)."""
    ll = fixtures["anchors"]["landlord_with_portfolio"]
    state = _run(
        agent,
        f"Open a referral-ready deep investigation into landlord {ll['actor_id']} "
        f"({ll['name']}): patterns of neglect across their portfolio.",
        "wx-a-deep", trust="vetted")
    assert "deep_investigation" in _tool_calls(state)


@pytest.mark.llm
def test_indexed_reference_pivot_resolves_to_the_second_candidate(agent, fixtures):
    """CLAUDE.md indexed-reference pivot: a disambiguation list, then 'the second
    one' resolves deterministically to ``last_result.items[1]``."""
    name = fixtures["anchors"]["landlord_connected_by_name"]["name"]

    t1 = _run(agent, f"Find the landlord named {name}.", "wx-b")
    assert "resolve_landlord_name" in _tool_calls(t1)
    last = t1.get("last_result") or {}
    if last.get("kind") != "landlord_candidates" or len(last.get("items") or []) < 2:
        pytest.skip("this name did not disambiguate into >=2 candidates in this data")

    t2 = _run(agent, "Tell me about the second one.", "wx-b", carry=_carry(t1))
    ref = t2.get("resolved_reference")
    assert ref is not None, "the indexed turn should carry resolved-reference metadata"
    assert ref["via"] == "indexed"
    assert ref["type"] == "landlord"
    assert ref["id"] == last["items"][1]["actor_id"]
