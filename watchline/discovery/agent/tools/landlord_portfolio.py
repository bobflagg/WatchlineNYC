"""Landlord and portfolio tools. Phase 3.

Keyed on ``actor_id`` (landlord) or ``portfolio_id``:

* :func:`lookup_landlord` — a resolved landlord's record (Type II).
* :func:`landlord_portfolio_membership` — the portfolio(s) it belongs to (Type II).
* aggregate/summary tools are added in group 2.

Everything here touches ``Landlord`` or ``Portfolio`` — inferred, derived
elements — so every result is **Type II** and carries the matching caveat
automatically (identity for ``Landlord``, algorithmic grouping for
``Portfolio``). Portfolio answers surface ``run_id`` / ``method`` /
``generated_at``, because a portfolio is a specific heuristic run's output, not a
standing fact (D7).
"""

from __future__ import annotations

from typing import Any

from ..db import read
from ..reliability import tagged
from ..vocab import VALID_PAIRS, EventType, Source, VocabularyError, require_pair
from ._events import hazard_coverage_note, rollup_events

__all__ = [
    "lookup_landlord",
    "landlord_portfolio_membership",
    "portfolio_summary",
    "portfolio_buildings_by_borough",
    "aggregate_landlord_portfolio_events",
    "LOOKUP_LANDLORD_DESCRIPTION",
    "LANDLORD_PORTFOLIO_MEMBERSHIP_DESCRIPTION",
    "PORTFOLIO_SUMMARY_DESCRIPTION",
    "PORTFOLIO_BUILDINGS_BY_BOROUGH_DESCRIPTION",
    "AGGREGATE_LANDLORD_PORTFOLIO_EVENTS_DESCRIPTION",
]


LOOKUP_LANDLORD_DESCRIPTION = (
    "Look up a resolved landlord by its actor_id: name, business address, and how "
    "many buildings it apparently controls. Call this when you already have a "
    "landlord's actor_id (e.g. from resolve_landlord_name) and want its record. "
    "To find a landlord by name instead, use resolve_landlord_name."
)

LANDLORD_PORTFOLIO_MEMBERSHIP_DESCRIPTION = (
    "Find which algorithmically-detected portfolio a landlord belongs to, by "
    "actor_id. Returns the portfolio id and the detection run's provenance. "
    "Portfolio grouping is inferred, not verified."
)

_LANDLORD_CYPHER = (
    "MATCH (l:Landlord {actor_id: $actor_id}) "
    "RETURN l.actor_id AS actor_id, l.name AS name, l.bizaddr AS bizaddr, "
    "size(coalesce(l.bbls, [])) AS building_count"
)

_MEMBERSHIP_CYPHER = (
    "MATCH (l:Landlord {actor_id: $actor_id}) "
    "OPTIONAL MATCH (l)-[:MEMBER_OF]->(p:Portfolio) "
    "RETURN l.actor_id AS actor_id, l.name AS name, "
    "[ p IN collect(p) WHERE p IS NOT NULL | { "
    "portfolio_id: p.portfolio_id, member_count: p.member_count, "
    "building_count: p.building_count, residential_units: p.residential_units, "
    "method: p.method, run_id: p.run_id, generated_at: toString(p.generated_at) "
    "} ] AS portfolios"
)


def _invalid_actor(actor_id: Any) -> dict[str, Any]:
    return {
        "found": False,
        "actor_id": actor_id if isinstance(actor_id, str) else repr(actor_id),
        "reason": "An actor_id is required, e.g. 'ACT-LL-42357'.",
    }


@tagged(["Landlord"])
def lookup_landlord(actor_id: str) -> dict[str, Any]:
    """Return a resolved landlord's record. Type II — inferred identity.

    ``building_count`` is the size of the landlord's apparently-controlled
    ``bbls`` list. The ``Landlord`` caveat travels with the result.
    """
    if not isinstance(actor_id, str) or not actor_id.strip():
        return _invalid_actor(actor_id)
    row = read(_LANDLORD_CYPHER, {"actor_id": actor_id.strip()}).single
    if row is None:
        return {"found": False, "actor_id": actor_id.strip(),
                "reason": f"No landlord in the discovery graph with actor_id "
                          f"{actor_id.strip()}. It may be a raw ACRIS party that "
                          "was never resolved to a landlord."}
    return {"found": True, **row}


@tagged(["Landlord", "MEMBER_OF", "Portfolio"])
def landlord_portfolio_membership(actor_id: str) -> dict[str, Any]:
    """Return the portfolio(s) a landlord is a member of. Type II.

    Returns a collection: the schema does not constrain a landlord to one
    portfolio. An empty ``portfolios`` list is a normal answer — a landlord in no
    detected portfolio (e.g. a singleton). Each carries the detection run's
    provenance (D7); ``portfolio_id`` is not stable across pipeline runs.
    """
    if not isinstance(actor_id, str) or not actor_id.strip():
        return _invalid_actor(actor_id)
    row = read(_MEMBERSHIP_CYPHER, {"actor_id": actor_id.strip()}).single
    if row is None:
        return {"found": False, "actor_id": actor_id.strip(),
                "reason": f"No landlord in the discovery graph with actor_id "
                          f"{actor_id.strip()}."}
    return {"found": True, "actor_id": row["actor_id"], "name": row["name"],
            "portfolios": row["portfolios"], "portfolio_count": len(row["portfolios"])}


# --------------------------------------------------------------------------
# Tier 2 — portfolio and cross-building aggregation
# --------------------------------------------------------------------------

PORTFOLIO_SUMMARY_DESCRIPTION = (
    "Summarise an algorithmically-detected portfolio by its portfolio_id: how "
    "many landlords (members), how many buildings, and how many residential "
    "units, with the detection run's provenance. Reads precomputed figures. "
    "Portfolio grouping is inferred, not verified."
)

PORTFOLIO_BUILDINGS_BY_BOROUGH_DESCRIPTION = (
    "Break down a portfolio's buildings by borough, by portfolio_id. Returns a "
    "count per borough. Portfolio grouping is inferred, not verified."
)

AGGREGATE_LANDLORD_PORTFOLIO_EVENTS_DESCRIPTION = (
    "Aggregate public-record events across all of a landlord's buildings (by "
    "actor_id) or a portfolio's buildings (by portfolio_id): totals, a status "
    "breakdown with percent open, and a violation-class breakdown. Requires the "
    "source (HPD, DOB, ACRIS, ECB, HPD-Litigations, Marshal); event type is "
    "inferred when the source has only one. Optional since_years limits to recent "
    "events. Provide exactly one of actor_id or portfolio_id."
)

_PORTFOLIO_SUMMARY_CYPHER = (
    "MATCH (p:Portfolio {portfolio_id: $portfolio_id}) "
    "RETURN p.portfolio_id AS portfolio_id, p.member_count AS member_count, "
    "p.building_count AS building_count, p.residential_units AS residential_units, "
    "p.method AS method, p.run_id AS run_id, toString(p.generated_at) AS generated_at"
)

_PORTFOLIO_BY_BOROUGH_CYPHER = (
    "MATCH (p:Portfolio {portfolio_id: $portfolio_id}) "
    "OPTIONAL MATCH (b:Building)-[:IN_PORTFOLIO]->(p) "
    "WITH p, b.borough AS borough, count(b) AS c WHERE borough IS NOT NULL "
    "RETURN p.portfolio_id AS portfolio_id, collect({borough: borough, count: c}) AS by_borough, "
    "p.building_count AS building_count"
)


@tagged(["Portfolio"])
def portfolio_summary(portfolio_id: str) -> dict[str, Any]:
    """Return a portfolio's precomputed size figures. Type II.

    **Reads** ``building_count`` / ``residential_units`` / ``member_count`` from
    the ``Portfolio`` node — it does not recompute them from the members (D7,
    P3-6). The figures came from a specific detection run, whose
    ``run_id``/``method``/``generated_at`` travel with the answer.
    """
    if not isinstance(portfolio_id, str) or not portfolio_id.strip():
        return {"found": False, "portfolio_id": repr(portfolio_id),
                "reason": "A portfolio_id is required."}
    row = read(_PORTFOLIO_SUMMARY_CYPHER, {"portfolio_id": portfolio_id.strip()}).single
    if row is None:
        return {"found": False, "portfolio_id": portfolio_id.strip(),
                "reason": f"No portfolio with id {portfolio_id.strip()}. Portfolio "
                          "ids are regenerated each pipeline run and are not stable."}
    return {"found": True, **row}


@tagged(["Portfolio", "IN_PORTFOLIO", "Building"])
def portfolio_buildings_by_borough(portfolio_id: str) -> dict[str, Any]:
    """Count a portfolio's buildings per borough. Type II."""
    if not isinstance(portfolio_id, str) or not portfolio_id.strip():
        return {"found": False, "portfolio_id": repr(portfolio_id),
                "reason": "A portfolio_id is required."}
    row = read(_PORTFOLIO_BY_BOROUGH_CYPHER, {"portfolio_id": portfolio_id.strip()}).single
    if row is None:
        return {"found": False, "portfolio_id": portfolio_id.strip(),
                "reason": f"No portfolio with id {portfolio_id.strip()}."}
    by_borough = {entry["borough"]: entry["count"] for entry in row["by_borough"]}
    return {"found": True, "portfolio_id": row["portfolio_id"],
            "by_borough": by_borough, "total_buildings": sum(by_borough.values()),
            "portfolio_building_count": row["building_count"]}


def _infer_event_type(source: Source, event_type: str | None) -> EventType:
    """Resolve the event type, inferring it when the source emits only one."""
    if event_type is not None:
        _, etype = require_pair(source, event_type)
        return etype
    types = [t for s, t in VALID_PAIRS if s is source]
    if len(types) == 1:
        return types[0]
    raise VocabularyError(
        f"{source.value!r} emits several event types "
        f"({', '.join(sorted(t.value for t in types))}); specify event_type."
    )


@tagged(["Landlord", "Portfolio", "MEMBER_OF", "IN_PORTFOLIO", "HAS_EVENT", "Event"])
def aggregate_landlord_portfolio_events(
    actor_id: str | None = None,
    portfolio_id: str | None = None,
    source_name: str | None = None,
    event_type: str | None = None,
    since_years: int | None = None,
) -> dict[str, Any]:
    """Aggregate events across a landlord's or a portfolio's buildings. Type II.

    Provide exactly one of ``actor_id`` / ``portfolio_id``. ``source_name`` is
    required; ``event_type`` is inferred when the source has only one. Returns
    totals, a status breakdown with percent open, and a class breakdown (HPD
    classes labelled hazard vs informational). For ECB, a coverage note discloses
    that the hazard scheme covers only a minority of judgments (OQ8).
    """
    if bool(actor_id) == bool(portfolio_id):
        return {"error": "scope_required",
                "reason": "Provide exactly one of actor_id or portfolio_id."}
    if not source_name:
        return {"error": "source_required",
                "reason": "source_name is required (HPD, DOB, ACRIS, ECB, "
                          "HPD-Litigations, Marshal)."}
    try:
        source = Source(source_name)
        etype = _infer_event_type(source, event_type)
    except (ValueError, VocabularyError) as exc:
        return {"error": "invalid_event_filter", "reason": str(exc)}

    params: dict[str, Any] = {"source": source.value, "type": etype.value}
    since_pred = ""
    if since_years is not None:
        since_pred = "AND e.event_date >= date() - duration({years: $since_years}) "
        params["since_years"] = int(since_years)

    if portfolio_id:
        scope = read("MATCH (p:Portfolio {portfolio_id: $pid}) RETURN p.building_count AS n",
                     {"pid": portfolio_id.strip()}).single
        if scope is None:
            return {"found": False, "portfolio_id": portfolio_id.strip(),
                    "reason": f"No portfolio with id {portfolio_id.strip()}."}
        scope_buildings = scope["n"]
        params["pid"] = portfolio_id.strip()
        scope_match = "MATCH (b:Building)-[:IN_PORTFOLIO]->(:Portfolio {portfolio_id: $pid}) "
    else:
        scope = read("MATCH (l:Landlord {actor_id: $aid}) RETURN size(coalesce(l.bbls, [])) AS n",
                     {"aid": actor_id.strip()}).single
        if scope is None:
            return {"found": False, "actor_id": actor_id.strip(),
                    "reason": f"No landlord with actor_id {actor_id.strip()}."}
        scope_buildings = scope["n"]
        params["aid"] = actor_id.strip()
        scope_match = ("MATCH (l:Landlord {actor_id: $aid}) UNWIND l.bbls AS scope_bbl "
                       "MATCH (b:Building {bbl: scope_bbl}) ")

    cypher = (
        f"{scope_match}"
        "MATCH (b)-[:HAS_EVENT]->(e:Event) "
        f"WHERE e.source_name = $source AND e.event_type = $type {since_pred}"
        "RETURN e.status AS status, e.violation_class AS cls, count(e) AS c"
    )
    rows = read(cypher, params).records
    rollup = rollup_events(source, etype, rows)

    result: dict[str, Any] = {
        "found": True,
        "scope": "portfolio" if portfolio_id else "landlord",
        "portfolio_id": portfolio_id.strip() if portfolio_id else None,
        "actor_id": actor_id.strip() if actor_id else None,
        "source_name": source.value, "event_type": etype.value,
        "scope_building_count": scope_buildings,
        **rollup,
    }
    coverage = hazard_coverage_note(source, etype)
    if coverage:
        result["coverage_note"] = coverage
    return result
