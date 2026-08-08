"""Hermetic tests for the eval harness (Phase 6, Group 1).

The code evaluators are pure functions, so their correctness is pinned here with
canned ``run``/``example`` dicts — a compliant trajectory scores 1, a violating
one scores 0 — at zero API cost. This is the roadmap's "verifiers assert
citation/caveat/resolved-reference presence" made concrete, and the core
confidence signal for the eval harness (the live LangSmith run only exercises the
same functions against real trajectories).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from evals import evaluators as ev
from evals.dataset import build_examples
from evals.run import run_agent


def _run(**outputs) -> dict:
    return {"outputs": outputs}


def _example(**metadata) -> dict:
    return {"metadata": metadata}


# --------------------------------------------------------------------------- #
# called_expected_tool
# --------------------------------------------------------------------------- #

def test_called_expected_tool_scores_1_when_present():
    run = _run(tool_calls=["resolve_address", "lookup_building"])
    assert ev.called_expected_tool(run, _example(tool="lookup_building"))["score"] == 1


def test_called_expected_tool_scores_0_when_absent():
    run = _run(tool_calls=["lookup_building"])
    assert ev.called_expected_tool(run, _example(tool="lookup_building_events"))["score"] == 0


def test_called_expected_tool_reads_runtree_attribute_shape():
    """Local ``evaluate()`` passes a RunTree (``.outputs`` attribute), not a dict."""
    run = SimpleNamespace(outputs={"tool_calls": ["lookup_building"]})
    example = SimpleNamespace(metadata={"tool": "lookup_building"})
    assert ev.called_expected_tool(run, example)["score"] == 1


# --------------------------------------------------------------------------- #
# event_query_constrains_source
# --------------------------------------------------------------------------- #

def test_event_query_with_source_scores_1():
    run = _run(tool_payloads={"lookup_building_events": [{"source_name": "HPD"}]})
    assert ev.event_query_constrains_source(run, _example(tool="lookup_building_events"))["score"] == 1


def test_event_query_without_source_scores_0():
    run = _run(tool_payloads={"aggregate_building_events": [{"found": True}]})
    assert ev.event_query_constrains_source(run, _example(tool="aggregate_building_events"))["score"] == 0


def test_non_event_query_is_not_applicable():
    run = _run(tool_payloads={"lookup_building": [{"found": True}]})
    assert ev.event_query_constrains_source(run, _example(tool="lookup_building"))["score"] == 1


# --------------------------------------------------------------------------- #
# type_ii_answer_ships_caveats
# --------------------------------------------------------------------------- #

def test_type_ii_with_caveats_scores_1():
    run = _run(tool_payloads={"lookup_building_ownership": [
        {"reliability": {"type": "II", "caveats": [{"text": "apparent control"}]}}]})
    assert ev.type_ii_answer_ships_caveats(run, _example())["score"] == 1


def test_type_ii_without_caveats_scores_0():
    run = _run(tool_payloads={"lookup_building_ownership": [
        {"reliability": {"type": "II", "caveats": []}}]})
    assert ev.type_ii_answer_ships_caveats(run, _example())["score"] == 0


def test_type_i_needs_no_caveats():
    run = _run(tool_payloads={"resolve_address": [{"reliability": {"type": "I", "caveats": []}}]})
    assert ev.type_ii_answer_ships_caveats(run, _example())["score"] == 1


# --------------------------------------------------------------------------- #
# derived_answer_carries_provenance
# --------------------------------------------------------------------------- #

def test_ownership_with_run_id_scores_1():
    run = _run(tool_payloads={"lookup_building_ownership": [
        {"apparent_controllers": [{"provenance": {"method": "m", "run_id": "run-7"}}]}]})
    assert ev.derived_answer_carries_provenance(
        run, _example(tool="lookup_building_ownership"))["score"] == 1


def test_ownership_missing_run_id_scores_0():
    run = _run(tool_payloads={"lookup_building_ownership": [
        {"apparent_controllers": [{"provenance": {"method": "m", "run_id": None}}]}]})
    assert ev.derived_answer_carries_provenance(
        run, _example(tool="lookup_building_ownership"))["score"] == 0


def test_ownership_with_no_controller_is_vacuously_ok():
    """The ~80% no-apparent-control path has nothing to attribute — not a failure."""
    run = _run(tool_payloads={"lookup_building_ownership": [{"apparent_controllers": []}]})
    assert ev.derived_answer_carries_provenance(
        run, _example(tool="lookup_building_ownership"))["score"] == 1


def test_portfolio_summary_provenance():
    ok = _run(tool_payloads={"portfolio_summary": [{"run_id": "run-9"}]})
    bad = _run(tool_payloads={"portfolio_summary": [{"found": True}]})
    assert ev.derived_answer_carries_provenance(ok, _example(tool="portfolio_summary"))["score"] == 1
    assert ev.derived_answer_carries_provenance(bad, _example(tool="portfolio_summary"))["score"] == 0


def test_control_network_provenance():
    ok = _run(tool_payloads={"control_network": [{"provenance": {"run_id": "run-3"}}]})
    bad = _run(tool_payloads={"control_network": [{"provenance": {}}]})
    assert ev.derived_answer_carries_provenance(ok, _example(tool="control_network"))["score"] == 1
    assert ev.derived_answer_carries_provenance(bad, _example(tool="control_network"))["score"] == 0


def test_non_provenance_tool_is_not_applicable():
    run = _run(tool_payloads={"lookup_building": [{"found": True}]})
    assert ev.derived_answer_carries_provenance(run, _example(tool="lookup_building"))["score"] == 1


# --------------------------------------------------------------------------- #
# reference_turn_reports_resolution
# --------------------------------------------------------------------------- #

def test_reference_turn_with_resolution_scores_1():
    run = _run(resolved_reference={"kind": "indexed", "index": 1})
    assert ev.reference_turn_reports_resolution(run, _example(is_reference_turn=True))["score"] == 1


def test_reference_turn_without_resolution_scores_0():
    run = _run(resolved_reference=None)
    assert ev.reference_turn_reports_resolution(run, _example(is_reference_turn=True))["score"] == 0


def test_non_reference_turn_is_not_applicable():
    run = _run(resolved_reference=None)
    assert ev.reference_turn_reports_resolution(run, _example())["score"] == 1


# --------------------------------------------------------------------------- #
# run function shape (validation 1.4) — agent faked, no model call
# --------------------------------------------------------------------------- #

def test_run_agent_returns_the_evaluator_shape(monkeypatch):
    """``run_agent`` must return the trajectory shape the evaluators read."""
    ai_call = SimpleNamespace(
        type="ai", content="",
        tool_calls=[{"name": "lookup_building_events", "args": {"source_name": "HPD"}}])
    tool_msg = SimpleNamespace(
        type="tool", name="lookup_building_events",
        content='{"found": true, "source_name": "HPD"}')
    final = SimpleNamespace(type="ai", content="Here is the answer.", tool_calls=[])
    fake_state = {
        "messages": [ai_call, tool_msg, final],
        "resolved_reference": {"kind": "indexed", "index": 1},
    }
    fake_agent = SimpleNamespace(invoke=lambda state, config: fake_state)
    monkeypatch.setattr(
        "watchline.discovery.agent.graph.build_agent", lambda: fake_agent)

    out = run_agent({"text": "How many open HPD violations?", "params": {}})

    assert out["tool_calls"] == ["lookup_building_events"]
    assert out["tool_payloads"]["lookup_building_events"][0]["source_name"] == "HPD"
    assert out["output"] == "Here is the answer."
    assert out["resolved_reference"] == {"kind": "indexed", "index": 1}
    # The captured trajectory scores 1 on the source-constraint evaluator.
    run = {"outputs": out}
    assert ev.event_query_constrains_source(
        run, _example(tool="lookup_building_events"))["score"] == 1


# --------------------------------------------------------------------------- #
# dataset builder — Tier gating (P6-3)
# --------------------------------------------------------------------------- #

def test_dataset_excludes_tier4_by_default():
    rows = build_examples(include_tier4=False)
    assert rows, "expected Tier 1-3 examples"
    assert all(r["metadata"]["tier"] != 4 for r in rows)
    # Tier-1-3 rows default to public trust.
    assert all(r["inputs"]["trust_level"] == "public" for r in rows)


def test_dataset_concretizes_templates_into_standalone_prompts():
    """No ``<placeholder>`` survives, and demonstrative queries gain an anchor."""
    import re

    rows = build_examples(include_tier4=False)
    texts = [r["inputs"]["text"] for r in rows]
    assert not any(re.search(r"<[a-z_]+>", t) for t in texts), "unfilled placeholder"
    # A "this portfolio/building/landlord" query is given a concrete identifier.
    demonstratives = [t for t in texts if "this " in t.lower()]
    assert demonstratives, "expected demonstrative queries in the fixture"
    assert all("For a specific record" in t for t in demonstratives)


def test_dataset_context_does_not_leak_answer_fields():
    """The appended anchor names only identifiers, never answer values."""
    rows = build_examples(include_tier4=False)
    leaky = {"residential_units", "recorded_owner", "bizaddr", "year_built",
             "eviction_count", "last_sold", "member_count", "building_count"}
    for r in rows:
        _, _, context = r["inputs"]["text"].partition("For a specific record")
        assert not any(k in context for k in leaky)


def test_dataset_includes_tier4_when_opted_in():
    without = build_examples(include_tier4=False)
    with_t4 = build_examples(include_tier4=True)
    assert len(with_t4) > len(without)
    tier4 = [r for r in with_t4 if r["metadata"]["tier"] == 4]
    assert tier4, "expected Tier-4 examples when opted in"
    # Tier-4 rows seed vetted trust (the deep agent is trust-gated).
    assert all(r["inputs"]["trust_level"] == "vetted" for r in tier4)
