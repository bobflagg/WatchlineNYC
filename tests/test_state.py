"""Hermetic tests for session-state capture and the idle timeout.

Pure ``capture`` / ``expire_stale_slots`` with an explicit clock, plus the
middleware hooks — no graph, no model, no real time.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from watchline.discovery.agent import state as state_mod
from watchline.discovery.agent.session import DEFAULT_IDLE_TIMEOUT_SECONDS
from watchline.discovery.agent.state import (
    capture,
    expire_stale_slots,
    extract_from_payload,
    session_state,
)


def _tool(name, payload):
    return ToolMessage(content=json.dumps(payload), name=name, tool_call_id="t1")


def _turn(*tool_messages, human="who owns it?"):
    return {"messages": [HumanMessage(human), AIMessage(""), *tool_messages]}


# -- extraction ------------------------------------------------------------


def test_resolve_address_resolved_focuses_building():
    delta = extract_from_payload("resolve_address", {"status": "resolved", "bbl": "1000050010",
                                                     "address": "115 BROAD STREET"})
    assert delta["focus"]["building"]["bbl"] == "1000050010"


def test_resolve_address_unresolved_captures_nothing():
    assert extract_from_payload("resolve_address", {"status": "no_tax_lot"}) == {}


def test_landlord_resolved_focuses_landlord():
    delta = extract_from_payload("resolve_landlord_name", {"status": "resolved",
        "landlord": {"actor_id": "ACT-LL-42357", "name": "GLEN BROWN"}})
    assert delta["focus"]["landlord"]["actor_id"] == "ACT-LL-42357"


def test_landlord_disambiguation_becomes_last_result_and_history():
    cands = [{"actor_id": "ACT-LL-1"}, {"actor_id": "ACT-LL-2"}]
    delta = extract_from_payload("resolve_landlord_name",
        {"status": "needs_disambiguation", "query": "Sandro Catalic", "candidates": cands})
    assert delta["last_result"]["kind"] == "landlord_candidates"
    assert delta["last_result"]["items"] == cands
    assert delta["disambiguation"]["query"] == "Sandro Catalic"
    assert "focus" not in delta


def test_ownership_single_controller_focuses_both():
    delta = extract_from_payload("lookup_building_ownership", {"found": True, "bbl": "1000050010",
        "address": "X", "apparent_controllers": [{"actor_id": "ACT-LL-90202", "name": "PETER HUNGERFORD"}]})
    assert delta["focus"]["building"]["bbl"] == "1000050010"
    assert delta["focus"]["landlord"]["actor_id"] == "ACT-LL-90202"


def test_ownership_multiple_controllers_no_landlord_focus():
    delta = extract_from_payload("lookup_building_ownership", {"found": True, "bbl": "1", "address": "X",
        "apparent_controllers": [{"actor_id": "A"}, {"actor_id": "B"}]})
    assert "landlord" not in delta["focus"]
    assert delta["last_result"]["items"] == [{"actor_id": "A"}, {"actor_id": "B"}]


def test_null_identifier_is_not_focused():
    delta = extract_from_payload("resolve_address", {"status": "resolved", "bbl": None, "address": "X"})
    assert delta == {}


# -- capture over the message stream ---------------------------------------


def test_capture_sets_focus_and_stamps_clock():
    state = _turn(_tool("resolve_address", {"status": "resolved", "bbl": "1000050010", "address": "X"}))
    out = capture(state, now=100.0)
    assert out["focus_entities"]["building"]["bbl"] == "1000050010"
    assert out["slot_touched_at"]["building"] == 100.0
    assert out["slot_touched_at"]["focus_entities"] == 100.0


def test_capture_merges_rather_than_replaces():
    # A landlord already in focus must survive a new building capture.
    state = _turn(_tool("resolve_address", {"status": "resolved", "bbl": "1", "address": "X"}))
    state["focus_entities"] = {"landlord": {"actor_id": "ACT-LL-9"}}
    out = capture(state, now=100.0)
    assert out["focus_entities"]["landlord"] == {"actor_id": "ACT-LL-9"}
    assert out["focus_entities"]["building"]["bbl"] == "1"


def test_capture_only_reads_since_last_human():
    # A tool result before the last human turn must not be re-captured.
    state = {"messages": [
        HumanMessage("first"),
        _tool("resolve_address", {"status": "resolved", "bbl": "1", "address": "A"}),
        HumanMessage("second"),
        _tool("resolve_address", {"status": "resolved", "bbl": "2", "address": "B"}),
    ]}
    out = capture(state, now=100.0)
    assert out["focus_entities"]["building"]["bbl"] == "2"


def test_capture_empty_when_no_tool_results():
    assert capture({"messages": [HumanMessage("hi")]}, now=100.0) == {}


def test_capture_ignores_unparseable_content():
    state = {"messages": [HumanMessage("hi"), ToolMessage(content="not json", name="x", tool_call_id="t")]}
    assert capture(state, now=100.0) == {}


# -- idle timeout ----------------------------------------------------------


def test_expire_clears_short_term_after_timeout():
    state = {
        "focus_entities": {"building": {"bbl": "1"}},
        "last_result": {"items": []},
        "disambiguation_history": [{"query": "x"}],
        "slot_touched_at": {"focus_entities": 0.0, "last_result": 0.0, "building": 0.0},
    }
    out = expire_stale_slots(state, now=DEFAULT_IDLE_TIMEOUT_SECONDS + 1, timeout=DEFAULT_IDLE_TIMEOUT_SECONDS)
    assert out["focus_entities"] == {}
    assert out["last_result"] is None
    # History is not short-term and is never in the delta.
    assert "disambiguation_history" not in out


def test_expire_noop_within_timeout():
    state = {"slot_touched_at": {"focus_entities": 100.0}}
    assert expire_stale_slots(state, now=200.0, timeout=1800.0) == {}


def test_expire_noop_with_no_timestamps():
    assert expire_stale_slots({}, now=10_000.0, timeout=1800.0) == {}


# -- middleware ------------------------------------------------------------


def test_after_model_captures():
    state = _turn(_tool("resolve_landlord_name", {"status": "resolved",
        "landlord": {"actor_id": "ACT-LL-42357", "name": "GLEN BROWN"}}))
    out = session_state.after_model(state, None)
    assert out["focus_entities"]["landlord"]["actor_id"] == "ACT-LL-42357"


def test_both_hook_forms_exist():
    # The Phase 1 lesson: a sync-only hook is absent under the async server.
    for hook in ("before_model", "abefore_model", "after_model", "aafter_model"):
        assert callable(getattr(session_state, hook))
