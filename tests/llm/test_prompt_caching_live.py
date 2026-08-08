"""Live proof that prompt caching lands (Lever 1). Costs a small amount.

The hermetic tests (``tests/test_prompt_caching.py``) prove the middleware is
*wired* and tags the request; this proves the cache is actually *read* on a real
call. Two turns run on one checkpointed thread: turn 1 writes the system+tools
prefix, turn 2 re-sends it and must read it back.

**Pinned to Sonnet 5, deliberately.** The rest of the ``llm`` tier runs on Haiku
4.5, but Haiku's minimum cacheable prefix is 4096 tokens — larger than this
agent's system+tools prefix, so a cache read is not guaranteed there and the proof
would be flaky. Sonnet 5's minimum is 1024 tokens, which the prefix clears
comfortably, making the read deterministic. This test is about the wire, not
routing or reasoning, so the model choice only needs a small-enough cache floor.
"""

from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from watchline.discovery.agent.graph import build_agent

pytestmark = pytest.mark.llm


def _cache_read(messages: list) -> int:
    """Total cache-read input tokens across the AI messages in ``messages``."""
    total = 0
    for m in messages:
        details = (getattr(m, "usage_metadata", None) or {}).get("input_token_details") or {}
        total += details.get("cache_read", 0) or 0
    return total


def test_second_turn_reads_the_cached_prefix(monkeypatch):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("no ANTHROPIC_API_KEY")

    # Pin Sonnet 5 (see module docstring). Overrides the llm conftest's Haiku,
    # which build_model() would otherwise pick up.
    monkeypatch.setenv("WATCHLINE_MODEL", "claude-sonnet-5")

    agent = build_agent(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "cache-proof", "trust_level": "public"}}

    # Turn 1 writes the system+tools prefix to the cache.
    t1 = agent.invoke(
        {"messages": [{"role": "user", "content": "In one sentence, what can you help me with?"}]},
        config=config,
    )
    n1 = len(t1["messages"])

    # Turn 2, same thread, re-sends system + tools + turn-1 history — the prefix is
    # now warm, so this call must read it back rather than pay full input price.
    t2 = agent.invoke(
        {"messages": [{"role": "user", "content": "And what public records do you draw on?"}]},
        config=config,
    )
    new_messages = t2["messages"][n1:]

    read = _cache_read(new_messages)
    assert read > 0, (
        "turn 2 read no cached tokens — caching did not land. "
        f"turn-2 AI usage: {[getattr(m, 'usage_metadata', None) for m in new_messages]}"
    )
