"""The discovery agent graph — the entrypoint ``langgraph dev`` loads.

A tool-calling agent over the shared Tier 1-3 library, with capability gating
and persona policy applied as middleware. A **session is a LangGraph thread**:
there is no separate session object, and a new conversation is a new
``thread_id``.

What this module deliberately does *not* do:

* **Enforce anything in the prompt.** Capability gating lives in
  :func:`~watchline.discovery.agent.middleware.trust_gate`, which removes tools
  from the request before the model sees them. Caveats are attached structurally
  by :mod:`~watchline.discovery.agent.reliability`. The system prompt describes
  how to *present* what the tools return; it is not what makes any of it true.
* **Summarize away the structured payload.** This module is a library whose
  product is structured, cited data. The model's prose is a presentation layer,
  and a calling application reads the tool messages directly.

**Model parameters (P1-1).** The Claude 5 family (the default ``claude-sonnet-5``,
and ``claude-opus-5``) rejects ``temperature``,
``top_p``, ``top_k`` and ``budget_tokens`` with a 400. None are set here, and
:mod:`tests.test_graph_agent` asserts that stays true — a 400 from a rejected
parameter would surface as an outage rather than as a configuration error.
Thinking is on by default on this model and ``effort`` defaults to ``high``;
both are left at their defaults, because tuning effort without measuring it is
guesswork. Phase 6's eval harness is where that sweep belongs.

**Prompt caching.** :data:`prompt_caching` attaches Anthropic ``cache_control``
breakpoints to the stable request prefix (system prompt + tool block) and the
message tail, so that prefix is written once and read at ~0.1x input cost
thereafter — the largest per-call saving, biggest on the Tier-4 investigator's
bursty loop and on multi-turn conversations. It is behaviour-neutral: only the
wire payload changes, never the model output.
"""

from __future__ import annotations

import os

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

from .middleware import persona_prompt, tool_call_guard, trust_gate
from .state import session_state

# Re-exported so existing imports and the Phase 0 test suite keep working. The
# definitions moved to `.session` so that `.middleware` can read session context
# without importing this module, which imports the middleware.
from .session import (  # noqa: F401
    DEFAULT_PERSONA,
    DEFAULT_TRUST_LEVEL,
    VALID_PERSONAS,
    VALID_TRUST_LEVELS,
    DiscoveryContext,
    TrustLevel,
    resolve_persona,
    resolve_trust_level,
)
from .tools.registry import all_tools

__all__ = [
    "MODEL_ID",
    "MAX_TOKENS",
    "CACHE_TTL",
    "prompt_caching",
    "build_model",
    "build_agent",
    "graph",
    "DiscoveryContext",
    # Re-exports from .session
    "TrustLevel",
    "resolve_trust_level",
    "resolve_persona",
    "DEFAULT_PERSONA",
    "DEFAULT_TRUST_LEVEL",
    "VALID_PERSONAS",
    "VALID_TRUST_LEVELS",
]

#: Decision P1-1 (revised). One model across the whole stack keeps prompt caching
#: and behaviour consistent. Defaults to **Sonnet 5** — Opus is avoided until a
#: demonstrated need for it (Tier-4 deep investigations complete on Sonnet). The
#: ``WATCHLINE_MODEL`` env var overrides this, which the ``llm`` test tier uses to
#: run tool-routing checks on a cheaper model (they assert on tool invocation, not
#: prose). Production sets nothing → Sonnet 5. To restore Opus, set MODEL_ID (or
#: ``WATCHLINE_MODEL``) to ``claude-opus-5``.
MODEL_ID = "claude-sonnet-5"

#: Set explicitly rather than relying on a library default. Generous enough that
#: a dual-answer response with caveats is never truncated mid-sentence, and low
#: enough to stay well inside HTTP timeouts on a non-streaming call.
MAX_TOKENS = 16_000

#: Prompt-cache TTL (P?-caching). ``"5m"`` covers the Tier-4 investigator's bursty
#: internal loop and active multi-turn conversations; the system+tools prefix is
#: identical across sessions of the same (persona, trust), so it stays read-warm.
#: ``"1h"`` is a one-line change if sparse traffic argues for keeping the prefix
#: warm longer, at a higher write cost.
CACHE_TTL = "5m"

#: One shared caching middleware for the top-level agent *and* the Tier-4
#: investigator (imported by :mod:`.investigator`). It tags the system prompt's
#: last block, the last tool (a single breakpoint caching the whole contiguous
#: tool block), and the message tail — a **behaviour-neutral** cost/latency win:
#: the wire payload gains ``cache_control`` breakpoints, the model output is
#: identical. A non-Anthropic model degrades silently (caching is an optimization,
#: not a correctness control), which matters only if ``WATCHLINE_MODEL`` is ever
#: pointed off Anthropic.
prompt_caching = AnthropicPromptCachingMiddleware(
    ttl=CACHE_TTL, unsupported_model_behavior="ignore"
)


def build_model() -> ChatAnthropic:
    """The chat model, with no parameter this model rejects.

    Bound through ``langchain-anthropic`` rather than the raw Anthropic SDK —
    that is the correct integration for a LangChain/LangGraph stack, and it is
    what carries tool schemas and message history for us.

    The model id is read at call time from ``WATCHLINE_MODEL`` (defaulting to
    :data:`MODEL_ID`), so tests can route the whole stack — the top-level agent
    and the Tier-4 investigator — onto a cheaper model without touching the
    production default.
    """
    return ChatAnthropic(model=os.environ.get("WATCHLINE_MODEL", MODEL_ID), max_tokens=MAX_TOKENS)


def build_agent(checkpointer=None):
    """Build the compiled agent.

    Middleware order is meaningful, and follows the turn order CLAUDE.md
    mandates: ``session_state`` runs first so references resolve and stale slots
    expire before anything else; then ``trust_gate`` filters the tool list and
    ``persona_prompt`` sets the register; ``tool_call_guard`` is the second,
    normally-unreachable layer that refuses a gated tool at execution time.
    ``session_state`` also captures each turn's tool results on the way out.

    ``prompt_caching`` sits **after** ``trust_gate`` and ``persona_prompt`` on
    purpose. Middleware composes *first-in-list = outermost*, so a middleware
    placed later sees the more-modified request; caching must run last among the
    model-call hooks to tag the *final* trust-filtered tool list and *persona-set*
    system prompt. It only annotates the payload with ``cache_control`` — output
    is unchanged.

    ``checkpointer`` is optional and defaults to ``None``. In production and under
    ``langgraph dev`` the server supplies its own, so callers pass nothing and
    ``thread_id`` remains the session identifier. An in-process caller that wants
    multi-turn memory without a server (e.g. the Streamlit UI) passes one, such as
    ``langgraph.checkpoint.memory.InMemorySaver``. Either way the session state
    lives in the graph's checkpointed state, not a separate store.
    """
    return create_agent(
        model=build_model(),
        tools=all_tools(),
        middleware=[session_state, trust_gate, persona_prompt, prompt_caching, tool_call_guard],
        # Typed run context so LangGraph Studio renders trust_level/persona fields.
        # Values set as context are read by the middleware alongside the classic
        # config["configurable"] form (which wins); see .middleware.
        context_schema=DiscoveryContext,
        checkpointer=checkpointer,
    )


#: `langgraph dev` / Studio load this symbol; the name must match langgraph.json.
graph = build_agent()
