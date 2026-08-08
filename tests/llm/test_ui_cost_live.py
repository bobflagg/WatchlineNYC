"""Live confirmation that streamed messages carry usage, so cost lands (Lever-1
cost reporting, G2). Cheap — one Haiku turn.

The hermetic tests prove the accounting; this proves the *source*: an `AIMessage`
streamed off `run_turn`'s `updates` channel actually carries `usage_metadata`, so
the terminal `Cost` is non-zero on a real turn. If this ever fails, apply the
requirements §4 fallback (add `"values"` to `run_turn`'s stream_mode).
"""

from __future__ import annotations

import os

import pytest

from watchline.discovery.agent.graph import build_agent
from watchline.discovery.ui.cost import Cost
from watchline.discovery.ui.stream import run_turn

pytestmark = pytest.mark.llm


def test_real_turn_produces_a_nonzero_cost():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("no ANTHROPIC_API_KEY")

    agent = build_agent()
    config = {"configurable": {"thread_id": "cost-live", "trust_level": "public"}}
    events = list(run_turn(agent, "In one short sentence, what can you help me with?", config))

    cost = events[-1]
    assert isinstance(cost, Cost)                 # terminal event
    assert cost.usage.input_tokens > 0, "streamed AIMessage carried no usage_metadata"
    assert cost.usd > 0
