"""Hermetic tests for deterministic reference resolution and turn order.

``resolve_references`` is pure; the ``before_model`` hook is driven with canned
state. No model, no graph.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from watchline.discovery.agent import graph as graph_module
from watchline.discovery.agent.state import _find_index, resolve_references, session_state


LANDLORD_FOCUS = {"landlord": {"actor_id": "ACT-LL-47644", "name": "IAN LAGOWITZ"}}
BUILDING_FOCUS = {"building": {"bbl": "1000050010", "address": "115 BROAD STREET"}}
CANDIDATES = {
    "kind": "landlord_candidates",
    "items": [
        {"actor_id": "ACT-LL-100020", "name": "SANDRO CATALIC"},
        {"actor_id": "ACT-LL-100021", "name": "SANDRO CATALIC"},
        {"actor_id": "ACT-LL-100022", "name": "SANDRO CATALIC"},
    ],
}


# -- indexed reference -----------------------------------------------------


def test_index_word_detection():
    assert _find_index("the second one") == 1
    assert _find_index("give me the 3rd") == 2
    assert _find_index("number 2 please") == 1
    assert _find_index("#4") == 3


def test_bare_number_is_not_an_index():
    # The whole reason for requiring an ordinal marker.
    assert _find_index("who owns 115 Broad Street") is None
    assert _find_index("the 2 buildings") is None


def test_indexed_reference_resolves_and_overwrites_focus():
    out = resolve_references("the second one", {}, CANDIDATES)
    assert out["resolved_reference"]["id"] == "ACT-LL-100021"
    assert out["resolved_reference"]["via"] == "indexed"
    # It also becomes the focus landlord, so a later "he" resolves to it.
    assert out["focus"]["landlord"]["actor_id"] == "ACT-LL-100021"


def test_out_of_range_index_does_not_resolve():
    assert resolve_references("the ninth one", {}, CANDIDATES) == {}


# -- pronoun / demonstrative ----------------------------------------------


def test_pronoun_resolves_to_focus_landlord():
    out = resolve_references("what about his other buildings?", LANDLORD_FOCUS, None)
    assert out["resolved_reference"]["type"] == "landlord"
    assert out["resolved_reference"]["id"] == "ACT-LL-47644"
    assert out["resolved_reference"]["via"] == "reference"


def test_demonstrative_type_word_resolves():
    out = resolve_references("tell me about that landlord", LANDLORD_FOCUS, None)
    assert out["resolved_reference"]["id"] == "ACT-LL-47644"


def test_this_building_resolves_to_building_focus():
    out = resolve_references("how many violations does this building have?", BUILDING_FOCUS, None)
    assert out["resolved_reference"]["type"] == "building"
    assert out["resolved_reference"]["id"] == "1000050010"


def test_no_reference_resolves_nothing():
    assert resolve_references("who owns 115 Broad Street?", {}, None) == {}


def test_pronoun_with_empty_focus_resolves_nothing():
    assert resolve_references("his buildings", {}, None) == {}


# -- correction ------------------------------------------------------------


def test_correction_is_flagged_and_overwrites():
    out = resolve_references("no, I meant the third one", {}, CANDIDATES)
    assert out["resolved_reference"]["correction"] is True
    assert out["resolved_reference"]["id"] == "ACT-LL-100022"
    assert out["focus"]["landlord"]["actor_id"] == "ACT-LL-100022"


# -- middleware integration -----------------------------------------------


def _turn_start(text, **state):
    return {"messages": [HumanMessage(text)], **state}


def test_before_model_injects_resolution_note():
    out = session_state.before_model(_turn_start("his buildings", focus_entities=LANDLORD_FOCUS), None)
    assert out["resolved_reference"]["id"] == "ACT-LL-47644"
    injected = out["messages"]
    # A HumanMessage, not a SystemMessage: a second non-consecutive system
    # message is rejected by the Anthropic API (found only by running the model).
    assert len(injected) == 1 and isinstance(injected[0], HumanMessage)
    assert "ACT-LL-47644" in injected[0].content


def test_before_model_sets_resolved_reference_none_when_nothing_matches():
    out = session_state.before_model(_turn_start("who owns 115 Broad Street?"), None)
    assert out["resolved_reference"] is None
    assert "messages" not in out  # nothing injected


def test_before_model_skips_mid_loop_calls():
    # Last message is a tool result, not a human turn — do not resolve.
    state = {"messages": [HumanMessage("his buildings"), AIMessage(""),
                          ToolMessage(content="{}", name="x", tool_call_id="t")],
             "focus_entities": LANDLORD_FOCUS}
    out = session_state.before_model(state, None)
    assert (out or {}).get("resolved_reference") is None


def test_turn_order_session_state_runs_first():
    # References must resolve before gating/persona — session_state is first.
    # prompt_caching sits after persona so it tags the final request; it does not
    # touch the resolve→gate→persona order this test guards.
    import inspect
    source = inspect.getsource(graph_module.build_agent)
    assert "session_state, trust_gate, persona_prompt, prompt_caching, tool_call_guard" in source
