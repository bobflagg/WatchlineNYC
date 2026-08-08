"""Agent behaviour with a real model — validation 6.4 to 6.6.

Run with ``pytest -m llm``. Calls Claude and the live graph, so it costs money
and is excluded from the default run.

**These assert on tool invocation and payload structure, never on model prose.**
Wording varies between runs and between model versions; a test that greps the
answer text would fail for reasons that have nothing to do with correctness, and
would then be muted — which is worse than not having it. What is asserted here
is what must be true regardless of phrasing: that a tool was called, which one,
and what the tool returned.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from watchline.discovery.agent.graph import build_agent
from watchline.discovery.agent.names import OwnershipVerdict

pytestmark = pytest.mark.llm

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures/example_queries.json"


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def agent():
    return build_agent()


def run(agent, text: str, *, trust_level: str = "public", persona: str | None = None) -> dict:
    """One turn. Returns the final state."""
    configurable: dict[str, object] = {"trust_level": trust_level, "thread_id": f"t-{hash(text)}"}
    if persona:
        configurable["persona"] = persona
    return agent.invoke(
        {"messages": [{"role": "user", "content": text}]},
        config={"configurable": configurable},
    )


def tool_calls(state: dict) -> list[str]:
    return [
        call["name"]
        for message in state["messages"]
        for call in (getattr(message, "tool_calls", None) or [])
    ]


def tool_payloads(state: dict, name: str) -> list[dict]:
    payloads = []
    for message in state["messages"]:
        if getattr(message, "type", None) == "tool" and getattr(message, "name", None) == name:
            content = message.content
            payloads.append(json.loads(content) if isinstance(content, str) else content)
    return payloads


class TestTheAgentGroundsItsAnswer:
    """Validation 6.4 — the failure mode that matters most here.

    A fluent, confident ownership answer produced without calling the tool is
    ungrounded, and indistinguishable to a reader from a cited one.
    """

    def test_ownership_question_calls_the_tool(self, agent, fixtures):
        bbl = fixtures["anchors"]["building_with_apparent_control"]["bbl"]
        state = run(agent, f"Who owns the building at BBL {bbl}?")
        assert "lookup_building_ownership" in tool_calls(state)

    def test_the_tool_receives_the_bbl_from_the_question(self, agent, fixtures):
        bbl = fixtures["anchors"]["building_with_apparent_control"]["bbl"]
        state = run(agent, f"Who owns the building at BBL {bbl}?")
        payload = tool_payloads(state, "lookup_building_ownership")[0]
        assert payload["bbl"] == bbl

    def test_both_answers_reach_the_caller_as_structured_data(self, agent, fixtures):
        """Validation 5.5 end to end: the payload is the product, and a calling
        application reads the tool message rather than parsing prose."""
        anchor = fixtures["anchors"]["building_with_apparent_control"]
        state = run(agent, f"Who owns BBL {anchor['bbl']}?")
        payload = tool_payloads(state, "lookup_building_ownership")[0]
        assert payload["recorded_owner"]["name"] == anchor["recorded_owner"]
        assert anchor["landlord_name"] in [c["name"] for c in payload["apparent_controllers"]]
        assert payload["verdict"] == OwnershipVerdict.DIFFERS.value

    def test_caveats_reach_the_caller(self, agent, fixtures):
        bbl = fixtures["anchors"]["building_with_apparent_control"]["bbl"]
        state = run(agent, f"Who owns BBL {bbl}?")
        payload = tool_payloads(state, "lookup_building_ownership")[0]
        elements = {c["element"] for c in payload["reliability"]["caveats"]}
        assert elements == {"Landlord", "APPARENT_CONTROL", "Building.dof_ownername"}

    def test_no_controller_building_still_answers(self, agent, fixtures):
        """The 80% path, driven by a real model rather than a direct call."""
        bbl = fixtures["edge_cases"]["building_without_apparent_control"]["entity"]["bbl"]
        state = run(agent, f"Who owns BBL {bbl}?")
        payload = tool_payloads(state, "lookup_building_ownership")[0]
        assert payload["found"] is True
        assert payload["apparent_controllers"] == []
        assert payload["verdict"] == OwnershipVerdict.NOT_COMPARABLE.value


class TestTierFourGating:
    """Validation 3.1/3.2 driven end to end, which is where the async-hook bug
    was found — a unit test on ``visible_tools`` cannot see it."""

    INVESTIGATIVE = (
        "Run a deep investigation into whether Bronx landlords show systemic "
        "patterns of neglect across their portfolios."
    )

    def test_not_called_on_a_public_thread(self, agent):
        state = run(agent, self.INVESTIGATIVE, trust_level="public")
        assert "deep_investigation" not in tool_calls(state)

    # The vetted-thread path — the tool visible *and* running a real
    # investigation — is covered by the ``llm_deep`` case-file eval in
    # test_phase5_behaviour. Asserting it here would run a full deep-agent
    # investigation on the routine (cheap) llm tier, so it lives there instead.

    def test_malformed_trust_hides_it(self, agent):
        """Fail-closed, exercised through the real agent rather than the
        resolver in isolation."""
        state = run(agent, self.INVESTIGATIVE, trust_level="admin")
        assert "deep_investigation" not in tool_calls(state)

    def test_persona_alone_does_not_unlock_it(self, agent):
        state = run(agent, self.INVESTIGATIVE, trust_level="public", persona="journalist")
        assert "deep_investigation" not in tool_calls(state)

# Removed: TestPlaceholderIsRelayedHonestly. It asserted deep_investigation
# returned a not-implemented stub — true through Phase 4, obsolete in Phase 5,
# where the tool runs a real Tier-4 investigation. The real behaviour is covered
# by the llm_deep case-file eval in test_phase5_behaviour.
