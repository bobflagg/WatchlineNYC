"""Tests for the Tier-4 deep_investigation tool and the registry — hermetic.

The investigator itself is faked (its own core is covered in
``tests/test_investigator.py``); here we test the tool's report contract, its
Type IV declaration, and that the gate reads the declaration rather than a name.
"""

from __future__ import annotations

import pytest

from watchline.discovery.agent.caveats import CAVEATS, DerivedElement
from watchline.discovery.agent.middleware import (
    TIER_4_METADATA_KEY,
    as_gated_metadata,
    requires_tier_4,
    visible_tools,
)
from watchline.discovery.agent.reliability import (
    RELIABILITY_KEY,
    ExternalSource,
    ReliabilityType,
)
from watchline.discovery.agent.tools import investigation
from watchline.discovery.agent.tools.investigation import TOOL_DESCRIPTION, deep_investigation
from watchline.discovery.agent.tools.registry import (
    TOOL_FUNCTIONS,
    all_tools,
    build_tool,
    tool_by_name,
)

_FAKE_REPORT = {
    "narrative": "Open Class C violations concentrate in 12 of the portfolio's buildings.",
    "findings": ["12 buildings carry open immediately-hazardous violations"],
    "priority": "high",
    "suggested_focus": "the 12 worst buildings",
    "citations": [{"tool": "portfolio_buildings_with_violations", "args": {"portfolio_id": "PF-1"}}],
    "web_sources": [],
    "tool_call_count": 4,
}


@pytest.fixture
def fake_investigator(monkeypatch):
    """Replace the model-driven investigator with a canned report."""
    monkeypatch.setattr(investigation, "run_investigation", lambda q, scope, **k: dict(_FAKE_REPORT))


@pytest.fixture
def payload(fake_investigator) -> dict:
    return deep_investigation("is this portfolio systematically neglected?", portfolio_id="PF-1")


class TestReportContract:
    """The tool returns one synthesized, cited report (D8, P5-4)."""

    def test_status_complete(self, payload):
        assert payload["status"] == "complete"

    def test_carries_narrative_findings_priority(self, payload):
        assert payload["narrative"].startswith("Open Class C")
        assert payload["findings"] == _FAKE_REPORT["findings"]
        assert payload["priority"] == "high"
        assert payload["suggested_focus"] == "the 12 worst buildings"

    def test_graph_and_web_provenance_separate(self, payload):
        assert payload["citations"] and "web_sources" in payload
        assert payload["web_sources"] == []  # separate section, empty here

    def test_scope_echoed(self, payload):
        assert payload["requested"]["portfolio_id"] == "PF-1"
        assert payload["question"].startswith("is this portfolio")

    def test_scope_arguments_optional_except_question(self, fake_investigator):
        result = deep_investigation("anything")
        assert result["requested"] == {"bbl": None, "actor_id": None,
                                        "portfolio_id": None, "borough": None}

    def test_description_says_when_to_call_and_is_no_longer_a_placeholder(self):
        lowered = TOOL_DESCRIPTION.casefold()
        assert "only for questions" in lowered
        assert "not yet implemented" not in lowered

    def test_has_async_twin(self):
        # The tool nests a graph invocation; the async server needs the coroutine.
        assert callable(getattr(deep_investigation, "async_impl", None))


class TestDeclaredTypeFour:
    """Web/registry search now runs inside the investigator, so this is Type IV."""

    def test_type_iv(self, payload):
        assert payload[RELIABILITY_KEY]["type"] == ReliabilityType.TYPE_IV.value

    def test_requires_tier_4(self, payload):
        assert payload[RELIABILITY_KEY]["requires_tier_4"] is True

    def test_external_sources_declared(self):
        sources = set(deep_investigation.reliability.external_sources)
        assert {ExternalSource.WEB_SEARCH, ExternalSource.REGISTRY_SEARCH} <= sources

    def test_declares_the_tier_4_graph_surface(self):
        elements = set(deep_investigation.reliability.elements)
        for derived in ("Landlord", "Portfolio", "APPARENT_CONTROL", "CONNECTED_BY_NAME"):
            assert derived in elements

    def test_carries_long_form_caveats(self, fake_investigator):
        result = deep_investigation("q", portfolio_id="PF-1")
        by_element = {c["element"]: c["text"] for c in result[RELIABILITY_KEY]["caveats"]}
        assert by_element["Portfolio"] == CAVEATS[DerivedElement.PORTFOLIO].long
        assert by_element["Portfolio"] != CAVEATS[DerivedElement.PORTFOLIO].short

    def test_async_result_also_carries_reliability(self, monkeypatch):
        import asyncio

        async def _fake(q, scope, **k):
            return dict(_FAKE_REPORT)

        monkeypatch.setattr(investigation, "arun_investigation", _fake)
        result = asyncio.run(deep_investigation.async_impl("q", portfolio_id="PF-1"))
        assert result[RELIABILITY_KEY]["type"] == ReliabilityType.TYPE_IV.value


class TestGateReadsTheDeclaration:
    """The gate is the mechanism, not a name list."""

    def test_built_tool_metadata_comes_from_the_declaration(self):
        tool = tool_by_name("deep_investigation")
        assert tool.metadata == as_gated_metadata(deep_investigation.reliability)
        assert tool.metadata[TIER_4_METADATA_KEY] is True

    def test_hidden_at_public(self):
        names = [tool.name for tool in visible_tools(all_tools(), "public")]
        assert "deep_investigation" not in names

    def test_visible_at_vetted(self):
        names = [tool.name for tool in visible_tools(all_tools(), "vetted")]
        assert "deep_investigation" in names

    def test_dropping_the_declaration_makes_it_visible(self, monkeypatch):
        original = deep_investigation.reliability
        ungated = type(original)(
            type=ReliabilityType.TYPE_II,
            elements=original.elements,
            caveats=original.caveats,
            external_sources=(),
        )
        monkeypatch.setattr(deep_investigation, "reliability", ungated)
        rebuilt = tool_by_name("deep_investigation")
        assert requires_tier_4(rebuilt) is False
        names = [tool.name for tool in visible_tools(all_tools(), "public")]
        assert "deep_investigation" in names


class TestRegistry:
    def test_registered_tools(self):
        names = {tool.name for tool in all_tools()}
        assert "deep_investigation" in names
        assert {
            "lookup_building_ownership", "resolve_address", "resolve_landlord_name",
            "lookup_building", "control_network", "compare_entities",
        } <= names

    def test_order_is_stable_across_calls(self):
        assert [t.name for t in all_tools()] == [t.name for t in all_tools()]

    def test_every_registered_tool_declares_reliability(self):
        for func, _ in TOOL_FUNCTIONS:
            assert hasattr(func, "reliability"), func.__name__

    def test_every_registered_tool_carries_gate_metadata(self):
        for tool in all_tools():
            assert TIER_4_METADATA_KEY in tool.metadata, tool.name

    def test_descriptions_are_model_facing_not_docstrings(self):
        for tool in all_tools():
            assert ":param" not in tool.description and len(tool.description) > 40

    def test_undeclared_function_is_rejected_loudly(self):
        def undeclared() -> dict:
            return {}

        with pytest.raises(AttributeError):
            build_tool(undeclared, "no declaration")

    def test_registry_module_hardcodes_no_tool_name_literals(self):
        import inspect

        from watchline.discovery.agent.tools import registry

        source = inspect.getsource(registry)
        assert '"deep_investigation"' not in source
        assert "'deep_investigation'" not in source
