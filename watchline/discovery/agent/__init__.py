"""Conversational query/agent layer over the ``watchline-discovery`` graph.

This package is a **library**, not an application: a calling application
creates a session (a LangGraph thread), passes turns in, and gets back
structured, cited answers. It does not own authentication, a UI, or the
evidentiary graph.

Graph access here is **read-only, always** — including the Tier-4 deep agent's
self-generated Cypher. See :mod:`watchline.discovery.agent.db`.

Using the library
------------------
Build the agent once, then drive one session per thread id. Trust and persona
travel in the run config, never in the message content::

    from watchline.discovery.agent import build_agent

    agent = build_agent()
    config = {"configurable": {
        "thread_id": "session-1",    # a session is a thread
        "trust_level": "public",     # "public" | "vetted" — gates the Tier-4 tool
        "persona": "general_public", # tone only; never confers trust
    }}
    state = agent.invoke(
        {"messages": [{"role": "user", "content": "Who owns BBL 1000050010?"}]},
        config=config)

The final message is the prose answer; the ``tool`` messages carry the
structured, cited payloads (reliability caveats, run provenance, resolved
references) behind it. See ``main.py`` for a runnable end-to-end example.

Public API
----------
:func:`build_agent` is imported lazily, so importing this package does not build
the agent. The trust/persona resolvers, the :class:`DiscoveryState` schema, and
the tool registry (:func:`all_tools`) are exported eagerly. The compiled
singleton the LangGraph server serves is
:data:`watchline.discovery.agent.graph.graph` (referenced by module path in
``langgraph.json``); library callers build their own with :func:`build_agent`.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .session import (
    DEFAULT_PERSONA,
    DEFAULT_TRUST_LEVEL,
    VALID_PERSONAS,
    VALID_TRUST_LEVELS,
    DiscoveryContext,
    DiscoveryState,
    TrustLevel,
    resolve_persona,
    resolve_trust_level,
)
from .tools.registry import all_tools

if TYPE_CHECKING:  # for type checkers only — the runtime path is __getattr__
    from .graph import build_agent

__all__ = [
    # Building / running the agent (lazy — see __getattr__).
    "build_agent",
    # The session contract.
    "DiscoveryState",
    "DiscoveryContext",
    "TrustLevel",
    "resolve_trust_level",
    "resolve_persona",
    "DEFAULT_PERSONA",
    "DEFAULT_TRUST_LEVEL",
    "VALID_PERSONAS",
    "VALID_TRUST_LEVELS",
    # The tool surface.
    "all_tools",
]

_LAZY = {"build_agent"}


def __getattr__(name: str):
    """Import ``build_agent`` on first access.

    Deferred so ``import watchline.discovery.agent`` stays cheap and free of the
    agent build (and of any import cycle through the middleware). Note the
    compiled singleton is deliberately *not* re-exported here: the name would
    collide with the ``graph`` submodule and resolve to the module once imported.
    """
    if name in _LAZY:
        module = importlib.import_module(f"{__name__}.graph")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
