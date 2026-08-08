"""Tests for capability gating and persona policy — validation 3.1 to 3.6.

Hermetic: no Neo4j, no model, no graph run.

This is a security control, so the tests are written the way security tests
should be: the default is denial, every unexpected input is checked rather than
assumed, and the assertion is about the *tool list the model receives* rather
than about what the model was asked to do.
"""

from __future__ import annotations

import pytest
from langchain_core.tools import StructuredTool

from watchline.discovery.agent.middleware import (
    BASE_SYSTEM_PROMPT,
    PERSONA_DIRECTIVES,
    TIER_4_METADATA_KEY,
    as_gated_metadata,
    requires_tier_4,
    visible_tools,
)
from watchline.discovery.agent.reliability import ExternalSource, reliability_of

# Trust values Phase 0 enumerated. Every one of these must resolve to public,
# and therefore hide Tier 4.
NON_VETTED_CONFIGS = [
    None,
    {},
    {"configurable": None},
    {"configurable": {}},
    {"configurable": {"trust_level": None}},
    {"configurable": {"trust_level": ""}},
    {"configurable": {"trust_level": "VETTED"}},
    {"configurable": {"trust_level": " vetted"}},
    {"configurable": {"trust_level": "Vetted"}},
    {"configurable": {"trust_level": "admin"}},
    {"configurable": {"trust_level": "vetted_user"}},
    {"configurable": {"trust_level": True}},
    {"configurable": {"trust_level": 1}},
    {"configurable": {"trust_level": ["vetted"]}},
    {"configurable": {"trust_level": {"level": "vetted"}}},
    {"configurable": {"TRUST_LEVEL": "vetted"}},
]


def make_tool(name: str, *, gated: bool) -> StructuredTool:
    """A minimal LangChain tool carrying the gate metadata."""
    return StructuredTool.from_function(
        func=lambda: "ok",
        name=name,
        description=f"{name} for testing",
        metadata={TIER_4_METADATA_KEY: gated},
    )


@pytest.fixture
def public_tool() -> StructuredTool:
    return make_tool("lookup_building_ownership", gated=False)


@pytest.fixture
def gated_tool() -> StructuredTool:
    return make_tool("deep_investigation", gated=True)


class TestTierFourHiddenOnPublic:
    """Validation 3.1 — absent from the list, not present-and-refusing."""

    def test_gated_tool_removed(self, public_tool, gated_tool):
        allowed = visible_tools([public_tool, gated_tool], "public")
        names = [tool.name for tool in allowed]
        assert names == ["lookup_building_ownership"]

    def test_gated_tool_is_absent_not_merely_marked(self, public_tool, gated_tool):
        """The model must not be told the capability exists. A tool that is
        present but refuses still reveals it and invites persuasion."""
        allowed = visible_tools([public_tool, gated_tool], "public")
        assert gated_tool not in allowed
        assert "deep_investigation" not in [tool.name for tool in allowed]

    def test_all_gated_means_empty_list(self, gated_tool):
        assert visible_tools([gated_tool], "public") == []


class TestTierFourVisibleOnVetted:
    """Validation 3.2."""

    def test_both_tools_present(self, public_tool, gated_tool):
        allowed = visible_tools([public_tool, gated_tool], "vetted")
        assert {tool.name for tool in allowed} == {
            "lookup_building_ownership",
            "deep_investigation",
        }

    def test_order_is_preserved(self, public_tool, gated_tool):
        """Tool order feeds the prompt prefix; a stable order keeps the cache
        stable."""
        allowed = visible_tools([public_tool, gated_tool], "vetted")
        assert [tool.name for tool in allowed] == [public_tool.name, gated_tool.name]


class TestFailsClosed:
    """Validation 3.3 — every value Phase 0 enumerated resolves to public."""

    @pytest.mark.parametrize("config", NON_VETTED_CONFIGS, ids=lambda c: repr(c)[:48])
    def test_non_vetted_config_hides_tier_4(self, config, public_tool, gated_tool):
        from watchline.discovery.agent.graph import resolve_trust_level

        trust = resolve_trust_level(config)
        assert trust == "public"
        allowed = visible_tools([public_tool, gated_tool], trust)
        assert gated_tool not in allowed

    @pytest.mark.parametrize(
        "trust", ["", "public", "PUBLIC", "vetted ", "Vetted", "admin", "root", "unknown"]
    )
    def test_only_the_exact_string_vetted_unlocks(self, trust, public_tool, gated_tool):
        """No case-insensitive match, no prefix match, no fuzzy acceptance."""
        if trust == "vetted":  # pragma: no cover - guard against a typo above
            pytest.skip("covered by the vetted tests")
        assert gated_tool not in visible_tools([public_tool, gated_tool], trust)


class TestUndeclaredToolsAreGated:
    """A tool whose declaration cannot be read is withheld, not granted.

    An unreadable declaration is a bug, and the safe reading of a bug in a
    capability gate is to withhold.
    """

    def test_missing_metadata_key(self):
        tool = StructuredTool.from_function(
            func=lambda: "ok", name="undeclared", description="no metadata key", metadata={}
        )
        assert requires_tier_4(tool) is True
        assert visible_tools([tool], "public") == []

    def test_metadata_none(self):
        tool = StructuredTool.from_function(
            func=lambda: "ok", name="undeclared", description="metadata is None"
        )
        assert requires_tier_4(tool) is True

    def test_object_with_no_metadata_attribute(self):
        assert requires_tier_4(object()) is True

    def test_metadata_not_a_dict(self):
        class Weird:
            name = "weird"
            metadata = "not a dict"

        assert requires_tier_4(Weird()) is True


class TestOrdinaryToolsStayPublic:
    """Validation 3.4 — Tier 1-3 is meant to be public."""

    def test_ownership_tool_visible_at_public(self, public_tool):
        assert visible_tools([public_tool], "public") == [public_tool]

    def test_the_real_ownership_declaration_is_not_gated(self):
        """Guards against the flagship tool accidentally becoming Tier-4 gated."""
        from watchline.discovery.agent.tools.ownership import lookup_building_ownership

        assert lookup_building_ownership.reliability.requires_tier_4 is False


class TestPersonaConfersNoCapability:
    """Validation 3.5."""

    def test_journalist_without_trust_still_hides_tier_4(self, public_tool, gated_tool):
        from watchline.discovery.agent.graph import resolve_persona, resolve_trust_level

        config = {"configurable": {"persona": "journalist"}}
        assert resolve_persona(config) == "journalist"
        assert resolve_trust_level(config) == "public"
        assert gated_tool not in visible_tools([public_tool, gated_tool], "public")

    @pytest.mark.parametrize("persona", sorted(PERSONA_DIRECTIVES))
    def test_no_persona_unlocks_anything(self, persona, public_tool, gated_tool):
        from watchline.discovery.agent.graph import resolve_trust_level

        trust = resolve_trust_level({"configurable": {"persona": persona}})
        assert gated_tool not in visible_tools([public_tool, gated_tool], trust)

    def test_persona_directives_grant_nothing(self):
        """The directives are about register. If one ever mentions a capability,
        that is a policy leak into prose."""
        for persona, directive in PERSONA_DIRECTIVES.items():
            lowered = directive.casefold()
            for word in ("tier 4", "tier-4", "investigation", "vetted", "trust"):
                assert word not in lowered, (persona, word)


class TestGatingIsNotInAPrompt:
    """Validation 3.6 — the tool list differs, rather than the model being
    asked to decline."""

    def test_tool_lists_differ_by_trust(self, public_tool, gated_tool):
        tools = [public_tool, gated_tool]
        assert visible_tools(tools, "public") != visible_tools(tools, "vetted")

    def test_system_prompt_does_not_mention_gating(self):
        """If the prompt explained the gate, the model would know the capability
        exists and could be argued toward it."""
        lowered = BASE_SYSTEM_PROMPT.casefold()
        for word in ("tier 4", "tier-4", "vetted", "trust_level", "not permitted", "you may not"):
            assert word not in lowered, word

    def test_system_prompt_states_the_dual_answer_rule(self):
        """Presentation guidance belongs in the prompt; enforcement does not."""
        lowered = BASE_SYSTEM_PROMPT.casefold()
        assert "recorded owner" in lowered
        assert "apparent controller" in lowered
        assert "no apparent controller" in lowered


class TestMetadataDerivesFromTheDeclaration:
    """Validation 4.3's mechanism, tested here since the gate lives here.

    The gate must read the static reliability declaration, not a hardcoded name
    list — a name list would drift on rename and would miss a newly added Type
    III/IV tool entirely.
    """

    def test_type_ii_tool_is_not_gated(self):
        declaration = reliability_of(["Building", "APPARENT_CONTROL"])
        assert as_gated_metadata(declaration) == {TIER_4_METADATA_KEY: False}

    def test_type_iii_tool_is_gated(self):
        declaration = reliability_of(["Building"], self_generated_cypher=True)
        assert as_gated_metadata(declaration) == {TIER_4_METADATA_KEY: True}

    def test_type_iv_tool_is_gated(self):
        declaration = reliability_of(
            ["Building"], external_sources=[ExternalSource.WEB_SEARCH]
        )
        assert as_gated_metadata(declaration) == {TIER_4_METADATA_KEY: True}

    def test_geosupport_does_not_gate(self):
        """The D10 carve-out: Geosupport is a local deterministic canonicalizer,
        not the open-web search Type IV covers."""
        declaration = reliability_of(
            ["Building"], external_sources=[ExternalSource.GEOSUPPORT]
        )
        assert as_gated_metadata(declaration) == {TIER_4_METADATA_KEY: False}

    def test_unknown_declaration_shape_is_gated(self):
        assert as_gated_metadata(object()) == {TIER_4_METADATA_KEY: True}

    def test_gate_is_not_a_name_list(self):
        """A tool named exactly like the real Tier-4 tool is still visible if it
        declares itself ungated — proving the decision comes from the tag."""
        impostor = make_tool("deep_investigation", gated=False)
        assert impostor in visible_tools([impostor], "public")
