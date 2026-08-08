"""Session context — trust level and persona resolution.

Hermetic. These assertions are carried over unchanged from the Phase 0 stub
test suite; only the import path moved, when the resolvers were lifted out of
``graph.py`` into ``session.py`` so the middleware could read session context
without a circular import.

Trust gating is a security control and this is the single place the fail-closed
rule is implemented, so the enumeration below is deliberately exhaustive rather
than representative.
"""

from __future__ import annotations

import pytest

from watchline.discovery.agent.session import (
    DEFAULT_PERSONA,
    DEFAULT_TRUST_LEVEL,
    VALID_PERSONAS,
    VALID_TRUST_LEVELS,
    resolve_persona,
    resolve_trust_level,
)


class TestTrustFailsClosed:
    """`trust_level` must fail closed to "public" on anything unexpected."""

    def test_vetted_is_honored(self):
        assert resolve_trust_level({"configurable": {"trust_level": "vetted"}}) == "vetted"

    def test_public_is_honored(self):
        assert resolve_trust_level({"configurable": {"trust_level": "public"}}) == "public"

    @pytest.mark.parametrize(
        "config",
        [
            None,
            {},
            {"configurable": None},
            {"configurable": {}},
            {"configurable": {"trust_level": None}},
            {"configurable": {"trust_level": ""}},
            {"configurable": {"trust_level": "VETTED"}},  # case must not pass
            {"configurable": {"trust_level": " vetted"}},  # nor whitespace
            {"configurable": {"trust_level": "Vetted"}},
            {"configurable": {"trust_level": "admin"}},  # invented value
            {"configurable": {"trust_level": "vetted_user"}},
            {"configurable": {"trust_level": True}},  # non-string
            {"configurable": {"trust_level": 1}},
            {"configurable": {"trust_level": ["vetted"]}},
            {"configurable": {"trust_level": {"level": "vetted"}}},
            {"configurable": {"TRUST_LEVEL": "vetted"}},  # wrong key
        ],
        ids=lambda c: repr(c)[:60],
    )
    def test_everything_else_is_public(self, config):
        assert resolve_trust_level(config) == "public"

    def test_only_two_trust_levels_exist(self):
        assert VALID_TRUST_LEVELS == frozenset({"public", "vetted"})
        assert DEFAULT_TRUST_LEVEL == "public"


class TestPersonaDefaults:
    @pytest.mark.parametrize("persona", sorted(VALID_PERSONAS))
    def test_valid_personas_honored(self, persona):
        assert resolve_persona({"configurable": {"persona": persona}}) == persona

    @pytest.mark.parametrize(
        "config",
        [None, {}, {"configurable": {}}, {"configurable": {"persona": "lawyer"}}],
        ids=lambda c: repr(c)[:40],
    )
    def test_unknown_persona_falls_back(self, config):
        assert resolve_persona(config) == DEFAULT_PERSONA

    def test_persona_does_not_confer_trust(self):
        """A self-declared journalist is still "public" trust."""
        config = {"configurable": {"persona": "journalist"}}
        assert resolve_persona(config) == "journalist"
        assert resolve_trust_level(config) == "public"


class TestGraphReExportsStillWork:
    """The resolvers moved modules; the old import path must keep working so a
    caller (or the Phase 0 suite) is not broken by an internal refactor."""

    def test_importable_from_graph(self):
        from watchline.discovery.agent import graph, session

        assert graph.resolve_trust_level is session.resolve_trust_level
        assert graph.resolve_persona is session.resolve_persona
        assert graph.DEFAULT_PERSONA == session.DEFAULT_PERSONA
