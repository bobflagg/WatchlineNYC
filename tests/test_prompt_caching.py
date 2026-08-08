"""Hermetic tests for prompt-caching wiring (Lever 1). No network.

Caching is a **behaviour-neutral** payload annotation, so the proof that it is
*wired correctly* is hermetic; the proof that it *lands* (a real cache read) needs
one live call and lives in ``tests/llm/test_prompt_caching_live.py``.

These pin three things:

* the caching middleware is our configured instance (TTL, silent-degrade);
* it is positioned **after** ``trust_gate`` / ``persona_prompt`` in ``build_agent``
  (and passed to the investigator), so it tags the *final* request; and
* handed a canned ``ModelRequest``, it tags the system prompt's last block, the
  last tool, and ``model_settings`` with our TTL.
"""

from __future__ import annotations

import inspect

from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import HumanMessage

from watchline.discovery.agent import investigator
from watchline.discovery.agent.graph import (
    CACHE_TTL,
    build_agent,  # noqa: F401 - imported for source introspection below
    build_model,
    prompt_caching,
)
from watchline.discovery.agent.tools.registry import all_tools


def test_prompt_caching_instance_is_our_configuration():
    assert isinstance(prompt_caching, AnthropicPromptCachingMiddleware)
    assert prompt_caching.ttl == CACHE_TTL == "5m"
    # Caching is an optimization, not a correctness control: a non-Anthropic model
    # degrades silently rather than warning or raising.
    assert prompt_caching.unsupported_model_behavior == "ignore"


def test_caching_is_positioned_after_the_gate_and_persona():
    """Composition is first-in-list = outermost, so caching must come *after*
    ``trust_gate`` and ``persona_prompt`` to tag the trust-filtered tools and the
    persona-set system prompt. Asserted on the ``middleware=[...]`` line itself,
    not the docstring (which also names these)."""
    source = inspect.getsource(build_agent)
    line = next(ln for ln in source.splitlines() if "middleware=[" in ln)
    assert line.index("trust_gate") < line.index("prompt_caching")
    assert line.index("persona_prompt") < line.index("prompt_caching")
    assert line.index("prompt_caching") < line.index("tool_call_guard")


def test_investigator_wires_the_shared_caching_middleware():
    source = inspect.getsource(investigator.build_investigator)
    assert "prompt_caching" in source
    assert "middleware=[prompt_caching]" in source


def _capture(request: ModelRequest) -> ModelRequest:
    """Run our middleware over ``request`` and return the request it forwards."""
    captured: dict = {}

    def handler(req: ModelRequest):
        captured["req"] = req
        return "ok"  # return value is irrelevant; we assert on the captured request

    prompt_caching.wrap_model_call(request, handler)
    return captured["req"]


def test_middleware_tags_system_tools_and_model_settings():
    tools = all_tools()[:2]
    request = ModelRequest(
        model=build_model(),  # a real ChatAnthropic — the isinstance gate passes
        messages=[HumanMessage(content="hi")],
        system_prompt="SYSTEM RULES",
        tools=tools,
        model_settings={},
    )

    out = _capture(request)
    cc = {"type": "ephemeral", "ttl": "5m"}

    # System prompt: a str body becomes a single text block carrying cache_control.
    assert out.system_message.content[-1]["cache_control"] == cc
    # Last tool: one breakpoint caches the whole contiguous tool block.
    assert out.tools[-1].extras["cache_control"] == cc
    # Message tail: passed through model settings for ChatAnthropic to place.
    assert out.model_settings["cache_control"] == cc
