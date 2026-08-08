"""The canonical tool list, and the single point where declarations meet the gate.

Every tool the agent can expose is registered here exactly once, as a pair of
the plain tagged function and the LangChain tool built from it. The build step
copies the function's **static reliability declaration** into the tool's
metadata, which is what
:func:`watchline.discovery.agent.middleware.trust_gate` reads.

That one derivation is what keeps the trust gate honest. The alternative — a
list of tool names the middleware treats as privileged — fails two ways that are
easy to miss in review: it drifts silently the moment a tool is renamed, and it
does not notice a *newly added* Type III/IV tool at all, so the next
investigative tool someone writes would default to visible. Deriving from the
declaration inverts that: a tool is gated because of what it does, and adding a
Tier-4 tool gates it automatically.

Tool descriptions come from each module's ``TOOL_DESCRIPTION`` rather than its
docstring. The docstring is for whoever maintains the tool; the description is a
prompt fragment the model reads, and the two want different things — notably,
the description should say *when* to call the tool, not just what it is.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from ..middleware import as_gated_metadata
from . import (
    address,
    building,
    chain,
    compare,
    geo_time,
    investigation,
    landlord,
    landlord_portfolio,
    network,
    ownership,
    portfolio_detail,
)

__all__ = ["TOOL_FUNCTIONS", "build_tool", "all_tools", "tool_by_name"]

#: Every registered tool function, in a stable order.
#:
#: Order matters more than it looks: the tool list renders at the very front of
#: the prompt prefix, so a stable order keeps the prompt cache stable across
#: requests. A set or a dict comprehension over a set would reorder between runs.
TOOL_FUNCTIONS: tuple[tuple[Any, str], ...] = (
    (ownership.lookup_building_ownership, ownership.TOOL_DESCRIPTION),
    (address.resolve_address, address.TOOL_DESCRIPTION),
    (landlord.resolve_landlord_name, landlord.TOOL_DESCRIPTION),
    # Phase 3 Tier-1 lookups.
    (building.lookup_building, building.LOOKUP_BUILDING_DESCRIPTION),
    (building.lookup_building_events, building.LOOKUP_BUILDING_EVENTS_DESCRIPTION),
    (landlord_portfolio.lookup_landlord, landlord_portfolio.LOOKUP_LANDLORD_DESCRIPTION),
    (landlord_portfolio.landlord_portfolio_membership,
     landlord_portfolio.LANDLORD_PORTFOLIO_MEMBERSHIP_DESCRIPTION),
    # Phase 3 Tier-2 aggregations.
    (building.aggregate_building_events, building.AGGREGATE_BUILDING_EVENTS_DESCRIPTION),
    (landlord_portfolio.aggregate_landlord_portfolio_events,
     landlord_portfolio.AGGREGATE_LANDLORD_PORTFOLIO_EVENTS_DESCRIPTION),
    (geo_time.aggregate_events_by_geo_time, geo_time.AGGREGATE_EVENTS_BY_GEO_TIME_DESCRIPTION),
    (landlord_portfolio.portfolio_summary, landlord_portfolio.PORTFOLIO_SUMMARY_DESCRIPTION),
    (landlord_portfolio.portfolio_buildings_by_borough,
     landlord_portfolio.PORTFOLIO_BUILDINGS_BY_BOROUGH_DESCRIPTION),
    # Phase 4 Tier-3 traversals.
    (chain.trace_ownership_chain, chain.TRACE_OWNERSHIP_CHAIN_DESCRIPTION),
    (network.sister_buildings, network.SISTER_BUILDINGS_DESCRIPTION),
    (network.control_network, network.CONTROL_NETWORK_DESCRIPTION),
    (network.shared_address_landlords, network.SHARED_ADDRESS_LANDLORDS_DESCRIPTION),
    (portfolio_detail.portfolio_buildings_with_violations,
     portfolio_detail.PORTFOLIO_BUILDINGS_WITH_VIOLATIONS_DESCRIPTION),
    (portfolio_detail.portfolio_litigation, portfolio_detail.PORTFOLIO_LITIGATION_DESCRIPTION),
    (network.trace_actor_to_landlord, network.TRACE_ACTOR_TO_LANDLORD_DESCRIPTION),
    # Phase 4 diff / compare.
    (compare.ownership_vs_registration_diff, compare.OWNERSHIP_VS_REGISTRATION_DIFF_DESCRIPTION),
    (compare.compare_entities, compare.COMPARE_ENTITIES_DESCRIPTION),
    (investigation.deep_investigation, investigation.TOOL_DESCRIPTION),
)


def build_tool(func: Any, description: str) -> StructuredTool:
    """Wrap a tagged tool function as a LangChain tool carrying its gate metadata.

    :raises AttributeError: if *func* has no ``.reliability`` — that means it was
        not declared with :func:`~watchline.discovery.agent.reliability.tagged`,
        and an undeclared tool must not reach the model at all. Failing loudly
        here is better than the middleware's fallback (which treats unreadable
        metadata as gated), because a Tier-1 tool silently becoming invisible is
        a confusing bug to chase.
    """
    declaration = func.reliability
    return StructuredTool.from_function(
        func=func,
        name=func.__name__,
        description=description,
        metadata=as_gated_metadata(declaration),
        # A tool may carry an async twin (``async_impl``) for the async server —
        # e.g. deep_investigation, which nests a graph invocation. Sync-only tools
        # leave this None and LangChain runs them in an executor.
        coroutine=getattr(func, "async_impl", None),
    )


def all_tools() -> list[StructuredTool]:
    """Every tool, before trust filtering.

    The agent is constructed with this full list; ``trust_gate`` removes what the
    current thread is not entitled to on each model call. Filtering here instead
    would bake trust into the graph at build time, and trust is per-thread.
    """
    return [build_tool(func, description) for func, description in TOOL_FUNCTIONS]


def tool_by_name(name: str) -> StructuredTool:
    """Look up one built tool. For tests and diagnostics."""
    for tool in all_tools():
        if tool.name == name:
            return tool
    known = ", ".join(sorted(func.__name__ for func, _ in TOOL_FUNCTIONS))
    raise KeyError(f"No registered tool named {name!r}. Registered: {known}")
