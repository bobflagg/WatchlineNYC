"""Per-building detail across a portfolio or a landlord's holdings. Phase 4 Tier 3.

`portfolio_buildings_with_violations` and `portfolio_litigation` fan out from a
portfolio (or a landlord's `bbls`) to each building's events, then return a
bounded, sorted summary — the "which of my buildings are worst" view an organizer
asks for. Both are **Type II** (they scope through `Portfolio`/`Landlord`), and
both go through :mod:`..vocab` for status and class, never raw equality.
"""

from __future__ import annotations

from typing import Any

from ..db import read
from ..reliability import tagged
from ..vocab import (
    OPEN_STATUSES,
    EventType,
    Source,
    canonical_status,
    class_schemes_for,
    hpd_hazard_filter,
    status_filter,
)

__all__ = [
    "portfolio_buildings_with_violations",
    "portfolio_litigation",
    "PORTFOLIO_BUILDINGS_WITH_VIOLATIONS_DESCRIPTION",
    "PORTFOLIO_LITIGATION_DESCRIPTION",
]

_HANDLE_CAP = 50


def _scope(portfolio_id: str | None, actor_id: str | None) -> tuple[str, dict[str, Any]] | dict[str, Any]:
    """Return (scope_match_cypher, params) for a portfolio or a landlord's bbls,
    or an error dict."""
    if bool(portfolio_id) == bool(actor_id):
        return {"error": "scope_required",
                "reason": "Provide exactly one of portfolio_id or actor_id."}
    if portfolio_id:
        return ("MATCH (b:Building)-[:IN_PORTFOLIO]->(:Portfolio {portfolio_id: $scope_id}) ",
                {"scope_id": portfolio_id.strip()})
    return ("MATCH (l:Landlord {actor_id: $scope_id}) UNWIND l.bbls AS _bbl "
            "MATCH (b:Building {bbl: _bbl}) ", {"scope_id": actor_id.strip()})


PORTFOLIO_BUILDINGS_WITH_VIOLATIONS_DESCRIPTION = (
    "List a portfolio's buildings (by portfolio_id) or a landlord's buildings (by "
    "actor_id) with each one's count of open, hazardous HPD violations (classes "
    "A/B/C; the administrative Class I is excluded). Sorted worst-first, capped, "
    "with portfolio-wide totals. Grouping/control is inferred, not verified. "
    "Provide exactly one of portfolio_id or actor_id."
)

PORTFOLIO_LITIGATION_DESCRIPTION = (
    "List a portfolio's (by portfolio_id) or a landlord's (by actor_id) buildings "
    "that are in housing court (HPD-Litigations), with case type, status, and the "
    "parties on each filing. Capped with totals. Provide exactly one of "
    "portfolio_id or actor_id."
)


@tagged(["Portfolio", "IN_PORTFOLIO", "Landlord", "Building", "HAS_EVENT", "Event"])
def portfolio_buildings_with_violations(
    portfolio_id: str | None = None, actor_id: str | None = None
) -> dict[str, Any]:
    """Each building with its open HPD hazard-violation count, worst-first. Type II."""
    scope = _scope(portfolio_id, actor_id)
    if isinstance(scope, dict):
        return scope
    scope_match, params = scope

    # Distinct param names — the default 'vals' collides between the two filters
    # (both would emit $vals_exact, silently overwriting the status list with the
    # hazard-class list and zeroing the count).
    open_frag, open_params = status_filter(
        Source.HPD, EventType.VIOLATION, OPEN_STATUSES).to_cypher("e.status", param="openv")
    hazard_frag, hazard_params = hpd_hazard_filter().to_cypher("e.violation_class", param="hazv")
    params.update(open_params)
    params.update(hazard_params)

    cypher = (
        f"{scope_match}"
        "OPTIONAL MATCH (b)-[:HAS_EVENT]->(e:Event) "
        "  WHERE e.source_name = 'HPD' AND e.event_type = 'Violation' "
        f"  AND {open_frag} AND {hazard_frag} "
        "WITH b, count(e) AS open_hazard_violations "
        "ORDER BY open_hazard_violations DESC "
        "RETURN collect({bbl: b.bbl, address: b.address, borough: b.borough, "
        "  open_hazard_violations: open_hazard_violations}) AS buildings"
    )
    row = read(cypher, params).single
    if row is None or not row["buildings"]:
        return {"found": False, "portfolio_id": portfolio_id, "actor_id": actor_id,
                "reason": "No buildings found for that portfolio or landlord."}
    buildings = row["buildings"]
    with_violations = [b for b in buildings if b["open_hazard_violations"] > 0]
    return {
        "found": True, "portfolio_id": portfolio_id, "actor_id": actor_id,
        "summary": {
            "building_count": len(buildings),
            "buildings_with_open_hazard_violations": len(with_violations),
            "total_open_hazard_violations": sum(b["open_hazard_violations"] for b in buildings),
        },
        "buildings": buildings[:_HANDLE_CAP],
        "truncated": len(buildings) > _HANDLE_CAP,
        "note": "Open, hazardous HPD violations only (classes A/B/C); Class I "
                "(administrative) is excluded from this count.",
    }


@tagged(["Portfolio", "IN_PORTFOLIO", "Landlord", "Building", "HAS_EVENT", "Event",
         "PARTY_TO", "Actor"])
def portfolio_litigation(
    portfolio_id: str | None = None, actor_id: str | None = None
) -> dict[str, Any]:
    """Portfolio/landlord buildings in housing court, with parties. Type II."""
    scope = _scope(portfolio_id, actor_id)
    if isinstance(scope, dict):
        return scope
    scope_match, params = scope

    cypher = (
        f"{scope_match}"
        "MATCH (b)-[:HAS_EVENT]->(e:Event {source_name: 'HPD-Litigations', event_type: 'CourtFiling'}) "
        "OPTIONAL MATCH (a:Actor)-[:PARTY_TO]->(e) "
        "WITH b, e, [name IN collect(DISTINCT a.name) WHERE name IS NOT NULL][..8] AS parties "
        "ORDER BY e.event_date DESC "
        "RETURN collect({bbl: b.bbl, address: b.address, event_id: e.event_id, "
        "  case_type: e.violation_class, status_raw: e.status, "
        "  date: toString(e.event_date), parties: parties}) AS filings"
    )
    row = read(cypher, params).single
    filings = row["filings"] if row else []
    if not filings:
        return {"found": True, "portfolio_id": portfolio_id, "actor_id": actor_id,
                "summary": {"filing_count": 0, "building_count": 0},
                "filings": [], "truncated": False,
                "note": "No housing-court (HPD-Litigations) filings found."}

    scheme = class_schemes_for(Source.HPD_LITIGATIONS, EventType.COURT_FILING)
    for f in filings:
        f["status"] = canonical_status(Source.HPD_LITIGATIONS, EventType.COURT_FILING, f.pop("status_raw")).value
        f["case_type_scheme"] = scheme[0].value if scheme else None
    buildings = {f["bbl"] for f in filings}
    return {
        "found": True, "portfolio_id": portfolio_id, "actor_id": actor_id,
        "summary": {"filing_count": len(filings), "building_count": len(buildings)},
        "filings": filings[:_HANDLE_CAP],
        "truncated": len(filings) > _HANDLE_CAP,
        "source_note": "Housing-court data is from HPD-Litigations; its coverage "
                       "window may differ from other sources.",
    }
