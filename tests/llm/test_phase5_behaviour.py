"""Phase 5 — the Tier-4 deep agent, with a real model. Run with ``pytest -m llm``.

The deep agent is slow and expensive, so this is deliberately small: the gate on
a public thread (cheap — the tool is invisible, nothing runs), and one full
case-file investigation asserted structurally (citations, caveats, real tool
calls), never on prose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.graph import build_agent
from watchline.discovery.agent.reliability import ReliabilityType
from watchline.discovery.agent.tools.investigation import deep_investigation

# No module-level marker: the cheap gate check is `llm`, the full deep-agent
# investigation is `llm_deep` (opt-in), so a routine `-m llm` run stays cheap.

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def agent():
    return build_agent()


def _tool_calls(state) -> list[str]:
    return [c["name"] for m in state["messages"] for c in (getattr(m, "tool_calls", None) or [])]


@pytest.mark.llm
def test_public_thread_cannot_invoke_the_deep_agent(agent):
    """End-to-end smoke over the *wired* agent: on a public thread the model
    cannot call ``deep_investigation`` — it is not in its tool list.

    The structural guarantee is proven for free in ``test_middleware.py`` and
    ``test_injection.py``; this only confirms the real build honours it. The
    prompt is deliberately **scoped** — it asks for the deep-investigation
    capability by name on a single entity, so when the tool is absent the model
    declines in one turn rather than fanning out into an expensive manual sweep
    (the old prompt's failure mode)."""
    state = agent.invoke(
        {"messages": [{"role": "user", "content":
                       "Use your deep_investigation capability to open a case file on "
                       "landlord ACT-LL-42357. If that capability isn't available to "
                       "me, just say so — do not investigate manually."}]},
        config={"configurable": {"trust_level": "public", "thread_id": "p5-public"}})
    assert "deep_investigation" not in _tool_calls(state)


@pytest.mark.llm_deep
def test_vetted_case_file_is_investigated_cited_and_caveated(fixtures):
    """A full case-file run (Tier-4 #4): a real investigation that calls tools and
    returns a cited narrative with long-form caveats. Called directly to bound the
    cost to a single deep-agent run. Marked llm_deep — the one opt-in expensive
    test, excluded from a routine `-m llm` run."""
    landlord = fixtures["anchors"]["landlord_with_portfolio"]
    out = deep_investigation(
        f"Build a referral-ready case file on landlord {landlord['actor_id']} "
        f"({landlord['name']}): the condition of their buildings and any patterns "
        "of neglect worth a regulator's attention.",
        actor_id=landlord["actor_id"])

    assert out["status"] == "complete"
    # It actually investigated — real tool calls, not a fabricated narrative.
    assert out["tool_call_count"] > 0
    assert out["citations"], "the report must be grounded in graph tool calls"
    assert out["narrative"]
    # Type IV with long-form caveats on the derived elements it relied on.
    assert out["reliability"]["type"] == ReliabilityType.TYPE_IV.value
    assert out["reliability"]["caveats"]
    # Graph-verified and web-sourced provenance are separate fields.
    assert "web_sources" in out
