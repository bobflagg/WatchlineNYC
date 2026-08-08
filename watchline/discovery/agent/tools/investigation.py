"""Tier-4 deep investigation — the real thing, as of Phase 5.

``deep_investigation`` builds the Deep Agents **investigator**
(:mod:`watchline.discovery.agent.investigator`) with fresh, isolated context and
runs one iterative query/rank/correlate loop, returning a single synthesized,
cited report. The investigator has the shared Tier 1-3 library plus
``run_cypher`` (self-generated Cypher through ``cypher_guard`` + ``db.read``) and
``web_search`` (Type IV) — none of which the top-level agent sees; only this one
gated tool is exposed to it.

**Type IV, gated.** The declaration is unchanged from the Phase 1 placeholder
except for the ``external_sources`` bump: web/registry search now runs inside the
investigator, so this tool is Type IV and remains ``requires_tier_4`` — visible
only on a ``vetted`` thread, enforced in the tool-filtering layer, never by
prompt.

**Both sync and async bodies.** The tool nests a graph invocation and
``langgraph dev`` runs async, so an async twin is provided (the Phase-1 lesson:
a sync-only path is absent exactly where it matters).
"""

from __future__ import annotations

from typing import Any

from ..investigator import arun_investigation, run_investigation
from ..reliability import RELIABILITY_KEY, ExternalSource, tagged

__all__ = ["deep_investigation", "TOOL_DESCRIPTION"]

TOOL_DESCRIPTION = (
    "Run an open-ended investigative analysis across the housing graph — systemic "
    "patterns across a landlord's portfolio, deterioration trends, serial-LLC "
    "ownership obfuscation, a referral-ready case file, eviction-cluster analysis, "
    "or cumulative-risk ranking. Call this ONLY for questions that a direct lookup "
    "or a single aggregation cannot answer, because it runs a full investigative "
    "agent and is slow and expensive. Returns a synthesized, cited report."
)

# The graph surface a Tier-4 investigation reads. Declared in full; the trust
# gate and caveat layer key off this. self_generated_cypher=True and the external
# sources make this Type IV — Tier-4-only.
_TIER_4_GRAPH_SURFACE = [
    "Building",
    "Building.dof_ownername",
    "Event",
    "HAS_EVENT",
    "REGISTERED_FOR",
    "PARTY_TO",
    "REFERENCES",
    "Actor",
    "Landlord",
    "Portfolio",
    "APPARENT_CONTROL",
    "CONNECTED_BY_NAME",
    "CONNECTED_BY_ADDRESS",
    "MEMBER_OF",
    "IN_PORTFOLIO",
]


def _scope(bbl, actor_id, portfolio_id, borough) -> dict[str, Any]:
    return {"bbl": bbl, "actor_id": actor_id, "portfolio_id": portfolio_id, "borough": borough}


def _assemble(question: str, scope: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """The report contract (without the reliability tag, which is attached last)."""
    return {
        "status": "complete",
        "question": question,
        "requested": scope,
        "narrative": report["narrative"],
        "findings": report["findings"],
        "priority": report["priority"],
        "suggested_focus": report["suggested_focus"],
        # Graph-verified citations kept separate from web-sourced context (P5-3).
        "citations": report["citations"],
        "web_sources": report["web_sources"],
        "tool_call_count": report["tool_call_count"],
        # True when the deep agent hit its step limit before concluding.
        "truncated": report.get("truncated", False),
    }


@tagged(
    _TIER_4_GRAPH_SURFACE,
    external_sources=[ExternalSource.WEB_SEARCH, ExternalSource.REGISTRY_SEARCH],
    self_generated_cypher=True,
    long_form=True,
)
def deep_investigation(
    question: str,
    bbl: str | None = None,
    actor_id: str | None = None,
    portfolio_id: str | None = None,
    borough: str | None = None,
) -> dict[str, Any]:
    """Run a Tier-4 investigation and return one synthesized, cited report.

    :param question: The investigative question, in the user's own words.
    :param bbl: Optional building scope.
    :param actor_id: Optional landlord scope.
    :param portfolio_id: Optional portfolio scope (ids are per-run, not stable).
    :param borough: Optional geographic scope.

    Long-form caveats for every derived element are attached automatically
    (Type IV, ``long_form=True``). Web-sourced context is kept in ``web_sources``,
    separate from graph-verified ``citations`` and never presented as ownership.

    The investigation nests under this call's run context automatically (LangChain
    propagates the config/callbacks via contextvars), so its steps trace under the
    parent and it emits progress onto the parent's ``custom`` stream — no config
    parameter is exposed to the model.
    """
    scope = _scope(bbl, actor_id, portfolio_id, borough)
    report = run_investigation(question, scope)
    return _assemble(question, scope, report)


async def _adeep_investigation(
    question: str,
    bbl: str | None = None,
    actor_id: str | None = None,
    portfolio_id: str | None = None,
    borough: str | None = None,
) -> dict[str, Any]:
    """Async twin — the async server calls this. Attaches the same reliability tag."""
    scope = _scope(bbl, actor_id, portfolio_id, borough)
    report = await arun_investigation(question, scope)
    result = _assemble(question, scope, report)
    return {**result, RELIABILITY_KEY: deep_investigation.reliability.as_payload(long_form=True)}


#: Registered as the tool's async coroutine by ``registry.build_tool``.
deep_investigation.async_impl = _adeep_investigation
