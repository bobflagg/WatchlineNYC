"""Hermetic tests for the Studio context schema (2026-08-04-context-schema).

The agent declares a ``DiscoveryContext`` context schema so LangGraph Studio
renders ``trust_level``/``persona`` fields. The middleware folds the run context
into ``configurable`` (configurable wins) so both Studio and programmatic callers
work, and the fail-closed trust gate is preserved. These pin that data flow
without a model or a live run.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import get_args

import pytest

from watchline.discovery.agent import middleware
from watchline.discovery.agent.session import (
    DEFAULT_PERSONA,
    DEFAULT_TRUST_LEVEL,
    VALID_PERSONAS,
    DiscoveryContext,
    Persona,
)


def _wire(monkeypatch, *, configurable=None, context=None):
    """Point the middleware's ambient readers at controlled config/context."""
    monkeypatch.setattr(middleware, "get_config",
                        lambda: {"configurable": dict(configurable or {})})
    monkeypatch.setattr(middleware, "get_runtime",
                        lambda: SimpleNamespace(context=context))


# --------------------------------------------------------------------------- #
# The user-visible goal: Studio will render the fields.
# --------------------------------------------------------------------------- #

def test_graph_advertises_the_context_fields():
    from watchline.discovery.agent.graph import graph

    props = (graph.get_context_jsonschema() or {}).get("properties", {})
    assert {"trust_level", "persona"} <= set(props)


# --------------------------------------------------------------------------- #
# Trust: both channels, precedence, fail-closed.
# --------------------------------------------------------------------------- #

def test_context_vetted_reaches_the_gate(monkeypatch):
    _wire(monkeypatch, context=DiscoveryContext(trust_level="vetted"))
    assert middleware._trust_from_ambient_config() == "vetted"


def test_configurable_vetted_survives_context_default(monkeypatch):
    # A programmatic caller sets configurable=vetted; the context is at its
    # default (public). Configurable must win — no downgrade.
    _wire(monkeypatch, configurable={"trust_level": "vetted"}, context=DiscoveryContext())
    assert middleware._trust_from_ambient_config() == "vetted"


def test_configurable_wins_on_conflict(monkeypatch):
    _wire(monkeypatch, configurable={"trust_level": "public"},
          context=DiscoveryContext(trust_level="vetted"))
    assert middleware._trust_from_ambient_config() == "public"


def test_malformed_context_trust_fails_closed(monkeypatch):
    _wire(monkeypatch, context=SimpleNamespace(trust_level="admin", persona=None))
    assert middleware._trust_from_ambient_config() == "public"


def test_no_run_context_is_public(monkeypatch):
    def _boom():
        raise RuntimeError("outside a runnable context")

    monkeypatch.setattr(middleware, "get_config", _boom)
    monkeypatch.setattr(middleware, "get_runtime", _boom)
    assert middleware._trust_from_ambient_config() == "public"


# --------------------------------------------------------------------------- #
# Persona: same fold, configurable wins, unknown falls back.
# --------------------------------------------------------------------------- #

def test_persona_from_context(monkeypatch):
    from watchline.discovery.agent.session import resolve_persona

    _wire(monkeypatch, context=DiscoveryContext(persona="journalist"))
    assert resolve_persona(middleware._ambient_config()) == "journalist"


def test_configurable_persona_wins(monkeypatch):
    from watchline.discovery.agent.session import resolve_persona

    _wire(monkeypatch, configurable={"persona": "watchdog_agency"},
          context=DiscoveryContext(persona="journalist"))
    assert resolve_persona(middleware._ambient_config()) == "watchdog_agency"


def test_unknown_persona_falls_back(monkeypatch):
    from watchline.discovery.agent.session import resolve_persona

    _wire(monkeypatch, context=SimpleNamespace(trust_level=None, persona="influencer"))
    assert resolve_persona(middleware._ambient_config()) == DEFAULT_PERSONA


# --------------------------------------------------------------------------- #
# The fold helper + the type.
# --------------------------------------------------------------------------- #

def test_context_to_dict_handles_dataclass_dict_and_none():
    assert middleware._context_to_dict(None) == {}
    assert middleware._context_to_dict(DiscoveryContext(trust_level="vetted")) == {
        "trust_level": "vetted", "persona": "general_public"}
    assert middleware._context_to_dict({"trust_level": "vetted"}) == {"trust_level": "vetted"}
    # Only trust/persona are lifted — nothing else the context might carry.
    assert middleware._context_to_dict({"trust_level": "vetted", "secret": "x"}) == {
        "trust_level": "vetted"}


def test_discovery_context_defaults_and_persona_literal():
    ctx = DiscoveryContext()
    assert ctx.trust_level == DEFAULT_TRUST_LEVEL == "public"
    assert ctx.persona == DEFAULT_PERSONA == "general_public"
    # The Literal used for the Studio dropdown stays in sync with the validator.
    assert set(get_args(Persona)) == VALID_PERSONAS
