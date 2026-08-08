"""The agent graph — validation 5.1 to 5.5.

Hermetic: the graph is *built* and inspected, never invoked, so no model is
called and no API key is needed. Behaviour that genuinely requires Claude lives
in the ``llm`` tier (group 6).

:class:`TestNoRejectedModelParameters` is the one to read first. The Claude 5
family (default ``claude-sonnet-5``, and ``claude-opus-5``) returns a 400 for
``temperature``, ``top_p``, ``top_k`` and ``budget_tokens``, and a 400 from a
rejected parameter looks like an outage rather than a config error — so it is
worth catching at build time.
"""

from __future__ import annotations

import inspect

import pytest
from langchain_anthropic import ChatAnthropic

from watchline.discovery.agent import graph as graph_module
from watchline.discovery.agent.graph import (
    MAX_TOKENS,
    MODEL_ID,
    build_agent,
    build_model,
    graph,
)
from watchline.discovery.agent.middleware import visible_tools
from watchline.discovery.agent.tools.registry import all_tools


class TestGraphLoads:
    """Validation 5.1 — the symbol langgraph.json points at."""

    def test_exports_a_compiled_graph(self):
        assert graph is not None
        assert hasattr(graph, "invoke")

    def test_builder_is_reusable(self):
        assert build_agent() is not None

    def test_entrypoint_is_a_module_path_not_a_file_path(self):
        """A file path makes `langgraph dev` load this module *outside* its
        package, so every relative import raises "attempted relative import
        with no known parent package". A dotted module path loads it as part of
        the installed package, which is also what keeps a single canonical
        module object rather than a path-loaded duplicate.
        """
        import json
        from pathlib import Path

        config = json.loads(
            (Path(__file__).resolve().parent.parent / "langgraph.json").read_text()
        )
        target = config["graphs"]["discovery_agent"]
        module_path, _, symbol = target.partition(":")
        assert symbol == "graph"
        assert module_path == "watchline.discovery.agent.graph"
        assert not module_path.endswith(".py")
        assert "/" not in module_path

    def test_entrypoint_module_actually_imports(self):
        """The dotted path must resolve — a typo here fails at server start,
        not at test time, unless it is checked."""
        import importlib

        module = importlib.import_module("watchline.discovery.agent.graph")
        assert hasattr(module, "graph")


class TestNoRejectedModelParameters:
    """Validation 5.2 — none of the four parameters this model 400s on."""

    REJECTED = ("temperature", "top_p", "top_k")

    @pytest.mark.parametrize("param", REJECTED)
    def test_not_set_on_the_model(self, param):
        assert getattr(build_model(), param) is None, param

    def test_no_budget_tokens_anywhere(self):
        """`budget_tokens` was removed with adaptive thinking; sending it is a
        400. It would only reach the API via `thinking`, so check that too.

        The source check looks for assignment forms rather than the bare word:
        the module docstring names the parameter in order to explain that it is
        rejected, which is documentation, not configuration.
        """
        model = build_model()
        assert model.thinking is None
        source = inspect.getsource(graph_module)
        assert "budget_tokens=" not in source
        assert '"budget_tokens"' not in source
        assert "'budget_tokens'" not in source

    @pytest.mark.parametrize("param", REJECTED)
    def test_not_mentioned_in_the_module(self, param):
        """Guards a future 'helpful' addition, which would break every call."""
        assert f"{param}=" not in inspect.getsource(graph_module)

    def test_model_id_is_the_agreed_one(self):
        # Default is Sonnet 5 — Opus is avoided until a demonstrated need.
        assert MODEL_ID == "claude-sonnet-5"
        assert build_model().model == "claude-sonnet-5"

    def test_watchline_model_env_overrides_only_when_set(self, monkeypatch):
        """Production reads no WATCHLINE_MODEL and stays on the default (Sonnet 5);
        the llm test tier sets it to route the stack onto a cheaper model. Read at
        call time."""
        monkeypatch.delenv("WATCHLINE_MODEL", raising=False)
        assert build_model().model == "claude-sonnet-5"
        monkeypatch.setenv("WATCHLINE_MODEL", "claude-haiku-4-5-20251001")
        assert build_model().model == "claude-haiku-4-5-20251001"

    def test_model_id_carries_no_date_suffix(self):
        """Current aliases are complete as-is; appending a date makes them 404.

        The version digit in ``claude-sonnet-5`` is part of the alias — what must
        not appear is an 8-digit date like ``-20251101``.
        """
        import re

        assert not re.search(r"\d{8}", MODEL_ID), MODEL_ID

    def test_max_tokens_is_set_explicitly_and_generous(self):
        """Not left to a library default: a dual-answer response carrying three
        caveats must never truncate mid-sentence."""
        assert build_model().max_tokens == MAX_TOKENS
        assert MAX_TOKENS >= 8_000

    def test_is_a_langchain_anthropic_model(self):
        """Bound through langchain-anthropic, the correct integration for this
        stack — not the raw Anthropic SDK."""
        assert isinstance(build_model(), ChatAnthropic)


class TestToolsAreWiredIn:
    #: The one gated (Tier-4) tool. Everything else is Tier 1-3 and public.
    GATED = {"deep_investigation"}
    PUBLIC = {
        "lookup_building_ownership",
        "resolve_address",
        "resolve_landlord_name",
        "lookup_building",
        "lookup_building_events",
        "lookup_landlord",
        "landlord_portfolio_membership",
        "aggregate_building_events",
        "aggregate_landlord_portfolio_events",
        "aggregate_events_by_geo_time",
        "portfolio_summary",
        "portfolio_buildings_by_borough",
        "trace_ownership_chain",
        "sister_buildings",
        "control_network",
        "shared_address_landlords",
        "portfolio_buildings_with_violations",
        "portfolio_litigation",
        "trace_actor_to_landlord",
        "ownership_vs_registration_diff",
        "compare_entities",
    }

    def test_registered_tools_are_available_to_the_agent(self):
        names = {tool.name for tool in all_tools()}
        assert names == self.PUBLIC | self.GATED

    def test_agent_is_built_with_the_unfiltered_list(self):
        """Filtering at build time would bake trust into the graph, but trust is
        per-thread — so the gate has to run per model call instead."""
        source = inspect.getsource(graph_module.build_agent)
        assert "all_tools()" in source
        assert "visible_tools" not in source

    def test_gate_would_hide_tier_4_from_a_public_thread(self):
        public = {tool.name for tool in visible_tools(all_tools(), "public")}
        # The Tier 1-3 tools are Type I/II and stay public; only the Tier-4
        # deep_investigation is withheld.
        assert public == self.PUBLIC


class TestMiddlewareIsAttached:
    """Validation 5.3-adjacent: enforcement is structural, not prompt-based."""

    def test_all_three_middlewares_present(self):
        source = inspect.getsource(graph_module.build_agent)
        for name in ("persona_prompt", "trust_gate", "tool_call_guard"):
            assert name in source, name

    def test_no_system_prompt_argument_that_would_shadow_the_persona_prompt(self):
        """The system prompt comes from the persona middleware. Passing one here
        as well would silently win or conflict."""
        source = inspect.getsource(graph_module.build_agent)
        assert "system_prompt=" not in source


class TestSessionContractPreserved:
    """Validation 5.4 — Phase 0 behaviour must not regress."""

    def test_resolvers_still_reachable_from_graph(self):
        assert graph_module.resolve_trust_level({"configurable": {"trust_level": "vetted"}}) == (
            "vetted"
        )
        assert graph_module.resolve_trust_level(None) == "public"

    def test_thread_id_remains_the_session(self):
        """No separate session object was introduced."""
        source = inspect.getsource(graph_module)
        assert "session_id" not in source

    def test_no_checkpointer_hardcoded(self):
        """build_agent accepts an optional checkpointer but constructs none itself —
        langgraph dev / a deployment / an in-process caller supplies its own, and
        the default is uncheckpointed."""
        assert "Saver(" not in inspect.getsource(graph_module.build_agent)
        assert build_agent().checkpointer is None


class TestStructuredOutputSurvives:
    """Validation 5.5 — the payload is the product, not the prose."""

    def test_tools_return_mappings_not_strings(self):
        for func, _ in graph_module.all_tools.__globals__["TOOL_FUNCTIONS"]:
            annotation = inspect.signature(func).return_annotation
            assert "dict" in str(annotation), func.__name__

    def test_graph_does_not_stringify_tool_results(self):
        source = inspect.getsource(graph_module)
        for smell in ("json.dumps", "str(result)", "summarize"):
            assert smell not in source, smell


class TestOptionalTracing:
    """Validation 5.5 — tracing is recommended, not required."""

    def test_builds_without_langsmith_configuration(self, monkeypatch):
        for var in ("LANGSMITH_API_KEY", "LANGSMITH_TRACING", "LANGSMITH_PROJECT"):
            monkeypatch.delenv(var, raising=False)
        assert build_agent() is not None


class TestOptionalCheckpointer:
    """UI-2: build_agent takes an optional checkpointer, default None.

    In-process callers (the Streamlit UI) pass one for multi-turn memory without a
    server; every existing caller passes nothing and is unaffected.
    """

    def test_default_is_uncheckpointed(self):
        assert build_agent().checkpointer is None

    def test_accepts_a_checkpointer(self):
        from langgraph.checkpoint.memory import InMemorySaver

        agent = build_agent(checkpointer=InMemorySaver())
        assert agent.checkpointer is not None
