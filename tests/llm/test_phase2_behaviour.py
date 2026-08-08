"""Phase 2 agent behaviour with a real model — entity resolution + references.

Run with ``pytest -m llm``. Calls Claude and the live graph/sidecar. Asserts on
tool invocation, payload structure, and resolved-reference metadata — never on
model prose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.geocode import GeosupportClient, GeosupportUnavailable
from watchline.discovery.agent.graph import build_agent

pytestmark = pytest.mark.llm

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"


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


def test_address_question_calls_resolve_address(agent, fixtures):
    try:
        GeosupportClient().health()
    except GeosupportUnavailable as exc:
        pytest.skip(f"Geosupport sidecar unavailable: {exc}")
    params = next(q["params"] for q in fixtures["queries"] if q["tool"] == "resolve_address")
    state = _run(agent, f"Who owns the building at {params['address']} in {params['borough']}?", "addr-1")
    assert "resolve_address" in _tool_calls(state)


def test_name_question_calls_resolve_landlord_name(agent, fixtures):
    name = fixtures["anchors"]["landlord_connected_by_name"]["name"]
    state = _run(agent, f"Which buildings does the landlord {name} control?", "name-1")
    assert "resolve_landlord_name" in _tool_calls(state)


def test_multi_turn_pronoun_resolves_to_the_focus_landlord(agent, fixtures):
    """The flagship Phase 2 thread: resolve a landlord, then refer to it as
    'he' and confirm the middleware resolves the reference to that entity."""
    params = next(q["params"] for q in fixtures["queries"] if q["tool"] == "resolve_landlord_name")

    turn1 = _run(agent, f"Resolve the landlord named {params['name']}.", "multi-1")
    assert "resolve_landlord_name" in _tool_calls(turn1)
    focus = (turn1.get("focus_entities") or {}).get("landlord")
    if not focus:
        pytest.skip("turn 1 did not resolve to a single landlord in this data")

    carry = {
        k: turn1[k]
        for k in ("focus_entities", "last_result", "slot_touched_at", "disambiguation_history")
        if turn1.get(k) is not None
    }
    turn2 = _run(agent, "What is his business address?", "multi-1", carry=carry)

    resolved = turn2.get("resolved_reference")
    assert resolved is not None, "the pronoun turn should carry resolved-reference metadata"
    assert resolved["type"] == "landlord"
    assert resolved["id"] == focus["actor_id"]
