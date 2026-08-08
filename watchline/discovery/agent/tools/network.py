"""Landlord / building network traversals. Phase 4 Tier 3.

Who else is connected to whom — by apparent control, by portfolio, by shared
business address. Every tool here touches inferred elements (`Landlord`,
`Portfolio`, `APPARENT_CONTROL`, `CONNECTED_BY_*`), so all are **Type II** and
carry the matching caveats. `CONNECTED_BY_*` edges are matched **undirected** —
the graph stores a direction but the signal is symmetric.

These traversals fan out fast (one landlord can control hundreds of buildings; an
111-member portfolio has ~12,650 connection edges), so every result is a
**compact summary plus a capped, sorted handle list plus the true total** — never
raw rows (CLAUDE.md, P4-2).

`trace_actor_to_landlord` — the known-gap tool — is added in group 2.
"""

from __future__ import annotations

import re
from typing import Any

from ..db import read
from ..names import compare_names, normalize
from ..reliability import tagged

__all__ = [
    "sister_buildings",
    "control_network",
    "shared_address_landlords",
    "trace_actor_to_landlord",
    "SISTER_BUILDINGS_DESCRIPTION",
    "CONTROL_NETWORK_DESCRIPTION",
    "SHARED_ADDRESS_LANDLORDS_DESCRIPTION",
    "TRACE_ACTOR_TO_LANDLORD_DESCRIPTION",
]

#: Hard cap on handles surfaced per dimension. The true total is always reported.
_HANDLE_CAP = 50

_BBL = re.compile(r"^[1-5][0-9]{9}$")


def _capped(items: list[Any]) -> tuple[list[Any], bool]:
    return items[:_HANDLE_CAP], len(items) > _HANDLE_CAP


# --------------------------------------------------------------------------
# sister_buildings
# --------------------------------------------------------------------------

SISTER_BUILDINGS_DESCRIPTION = (
    "Find a building's 'sister' buildings by BBL — others sharing its apparent "
    "controller or its detected portfolio. Use for 'what else does this "
    "landlord/owner control', 'related buildings', 'sister buildings'. Returns a "
    "capped, counted list per sharing dimension. Both sharing signals are "
    "inferred, not confirmed ownership. Takes a 10-digit BBL."
)

_SISTER_CYPHER = (
    "MATCH (b0:Building {bbl: $bbl}) "
    "OPTIONAL MATCH (b0)<-[:APPARENT_CONTROL]-(l:Landlord)-[:APPARENT_CONTROL]->(sc:Building) "
    "  WHERE sc.bbl <> $bbl "
    "WITH b0, collect(DISTINCT {bbl: sc.bbl, address: sc.address, borough: sc.borough, "
    "  via_actor_id: l.actor_id, via_name: l.name}) AS by_controller "
    "OPTIONAL MATCH (b0)-[:IN_PORTFOLIO]->(p:Portfolio)<-[:IN_PORTFOLIO]-(sp:Building) "
    "  WHERE sp.bbl <> $bbl "
    "WITH b0, by_controller, "
    "  collect(DISTINCT {bbl: sp.bbl, address: sp.address, borough: sp.borough, "
    "  portfolio_id: p.portfolio_id}) AS by_portfolio "
    "RETURN b0.bbl AS bbl, b0.address AS address, by_controller, by_portfolio"
)


@tagged(["Building", "APPARENT_CONTROL", "Landlord", "IN_PORTFOLIO", "Portfolio"])
def sister_buildings(bbl: str) -> dict[str, Any]:
    """Buildings sharing this one's apparent controller or portfolio. Type II."""
    if not isinstance(bbl, str) or not _BBL.match(bbl.strip()):
        return {"found": False, "bbl": bbl if isinstance(bbl, str) else repr(bbl),
                "reason": "Not a valid BBL (10 digits, borough 1-5)."}
    row = read(_SISTER_CYPHER, {"bbl": bbl.strip()}).single
    if row is None:
        return {"found": False, "bbl": bbl.strip(),
                "reason": f"No building in the discovery graph with BBL {bbl.strip()}."}

    controller_handles, controller_trunc = _capped(row["by_controller"])
    portfolio_handles, portfolio_trunc = _capped(row["by_portfolio"])
    return {
        "found": True, "bbl": row["bbl"], "address": row["address"],
        "summary": {
            "same_controller_count": len(row["by_controller"]),
            "same_portfolio_count": len(row["by_portfolio"]),
        },
        "same_controller": controller_handles,
        "same_portfolio": portfolio_handles,
        "truncated": controller_trunc or portfolio_trunc,
    }


# --------------------------------------------------------------------------
# control_network
# --------------------------------------------------------------------------

CONTROL_NETWORK_DESCRIPTION = (
    "Map the apparent-control network of a portfolio (by portfolio_id) or the "
    "portfolio a landlord belongs to (by actor_id): the member landlords, how many "
    "buildings each apparently controls, and how many name/address connections "
    "each has. Returns a summary plus a capped, sorted member list. Grouping and "
    "control are inferred, not verified. Provide exactly one of portfolio_id or "
    "actor_id."
)

_CONTROL_NETWORK_CYPHER = (
    "MATCH (p:Portfolio {portfolio_id: $pid})<-[:MEMBER_OF]-(l:Landlord) "
    "OPTIONAL MATCH (l)-[:APPARENT_CONTROL]->(cb:Building) "
    "OPTIONAL MATCH (l)-[c:CONNECTED_BY_NAME|CONNECTED_BY_ADDRESS]-(:Landlord) "
    "WITH p, l, count(DISTINCT cb) AS buildings, count(DISTINCT c) AS connections "
    "ORDER BY buildings DESC "
    "RETURN p.portfolio_id AS portfolio_id, p.run_id AS run_id, p.method AS method, "
    "toString(p.generated_at) AS generated_at, "
    "p.member_count AS member_count, p.building_count AS building_count, "
    "sum(connections) AS connection_edges, "
    "collect({actor_id: l.actor_id, name: l.name, controlled_buildings: buildings, "
    "  connections: connections}) AS members"
)


@tagged(["Portfolio", "MEMBER_OF", "Landlord", "CONNECTED_BY_NAME",
         "CONNECTED_BY_ADDRESS", "APPARENT_CONTROL", "Building"])
def control_network(portfolio_id: str | None = None, actor_id: str | None = None) -> dict[str, Any]:
    """The apparent-control network of a portfolio. Type II.

    Provide a ``portfolio_id`` directly, or an ``actor_id`` whose portfolio is
    used. Returns member/building counts and a capped, controlled-count-sorted
    member list with connection counts. ``connection_edges`` double-counts an
    edge whose both endpoints are members, so it is an approximate scale
    indicator, not an exact count.
    """
    if bool(portfolio_id) == bool(actor_id):
        return {"error": "scope_required",
                "reason": "Provide exactly one of portfolio_id or actor_id."}
    pid = portfolio_id
    if actor_id:
        resolved = read("MATCH (l:Landlord {actor_id: $aid})-[:MEMBER_OF]->(p:Portfolio) "
                        "RETURN p.portfolio_id AS pid LIMIT 1", {"aid": actor_id.strip()}).single
        if resolved is None:
            return {"found": False, "actor_id": actor_id.strip(),
                    "reason": "That landlord is in no detected portfolio."}
        pid = resolved["pid"]

    row = read(_CONTROL_NETWORK_CYPHER, {"pid": pid.strip()}).single
    if row is None:
        return {"found": False, "portfolio_id": pid,
                "reason": f"No portfolio with id {pid}."}
    members, truncated = _capped(row["members"])
    return {
        "found": True, "portfolio_id": row["portfolio_id"],
        "provenance": {"run_id": row["run_id"], "method": row["method"],
                       "generated_at": row["generated_at"]},
        "summary": {
            "member_count": row["member_count"],
            "building_count": row["building_count"],
            "connection_edges_approx": row["connection_edges"],
        },
        "members": members,
        "truncated": truncated,
    }


# --------------------------------------------------------------------------
# shared_address_landlords
# --------------------------------------------------------------------------

SHARED_ADDRESS_LANDLORDS_DESCRIPTION = (
    "Find landlords sharing a business address with a given landlord (by "
    "actor_id), via the graph's shared-address connections. Use for 'who else "
    "operates from the same address'. The connection is inferred from a shared "
    "business address and the network is known to be incomplete — surface both."
)

_SHARED_ADDRESS_CYPHER = (
    "MATCH (l:Landlord {actor_id: $actor_id}) "
    "OPTIONAL MATCH (l)-[r:CONNECTED_BY_ADDRESS]-(o:Landlord) "
    "RETURN l.actor_id AS actor_id, l.name AS name, l.bizaddr AS bizaddr, "
    "collect(DISTINCT {actor_id: o.actor_id, name: o.name, bizaddr: o.bizaddr, "
    "  weight: r.weight}) AS connected"
)

#: The under-connection disclosure (D11). CONNECTED_BY_ADDRESS clusters on the
#: raw, partly-standardized bizaddr string, so the same physical address stored
#: two ways is not linked — the network misses connections as well as adding them.
_UNDER_CONNECTION_NOTE = (
    "This network is built from CONNECTED_BY_ADDRESS, which matches on the raw "
    "business-address string. Because that string is only partly standardized, "
    "landlords at the same physical address stored in different formats are not "
    "linked — so absence of a connection here does not mean none exists."
)


@tagged(["Landlord", "CONNECTED_BY_ADDRESS"])
def shared_address_landlords(actor_id: str) -> dict[str, Any]:
    """Landlords sharing a business address with this one. Type II.

    Traverses ``CONNECTED_BY_ADDRESS`` (undirected). Carries the D11 under-
    connection disclosure, because this signal misses connections as well as
    over-connecting.
    """
    if not isinstance(actor_id, str) or not actor_id.strip():
        return {"found": False, "actor_id": repr(actor_id),
                "reason": "An actor_id is required, e.g. 'ACT-LL-1'."}
    row = read(_SHARED_ADDRESS_CYPHER, {"actor_id": actor_id.strip()}).single
    if row is None:
        return {"found": False, "actor_id": actor_id.strip(),
                "reason": f"No landlord with actor_id {actor_id.strip()}."}
    connected, truncated = _capped(row["connected"])
    return {
        "found": True, "actor_id": row["actor_id"], "name": row["name"],
        "bizaddr": row["bizaddr"],
        "connected_count": len(row["connected"]),
        "connected": connected,
        "truncated": truncated,
        "network_limitation": _UNDER_CONNECTION_NOTE,
    }


# --------------------------------------------------------------------------
# trace_actor_to_landlord — the known-gap tool (T3 #10)
# --------------------------------------------------------------------------

TRACE_ACTOR_TO_LANDLORD_DESCRIPTION = (
    "Given a raw ACRIS party (an actor_id), try to connect it to a resolved "
    "landlord. IMPORTANT: the graph has no edge that resolves a raw party to a "
    "landlord, so this returns possibly-related landlords by shared name only, "
    "never a confirmed match. Use when asked to link a deed/mortgage party to a "
    "landlord, and report the result as tentative."
)

#: The graph carries no "this raw Actor is this Landlord" edge — only fuzzy
#: name/address inference between Landlords. So a raw party can be *associated*
#: with candidates but never *resolved*, and saying otherwise would over-claim.
_NO_RESOLUTION_NOTE = (
    "There is no edge in the graph that resolves a raw ACRIS party to a landlord. "
    "The candidates below share a name and are possibly-related, not confirmed "
    "matches — treat any link as tentative."
)

_ACTOR_CYPHER = "MATCH (a:Actor {actor_id: $actor_id}) RETURN a.name AS name, (a:Landlord) AS is_landlord"

_CANDIDATES_CYPHER = (
    "CALL db.index.fulltext.queryNodes('landlord_name_fulltext', $query) YIELD node, score "
    "RETURN node.actor_id AS actor_id, node.name AS name, "
    "size(coalesce(node.bbls, [])) AS building_count LIMIT $limit"
)


@tagged(["Actor", "Landlord", "CONNECTED_BY_NAME", "CONNECTED_BY_ADDRESS"])
def trace_actor_to_landlord(actor_id: str) -> dict[str, Any]:
    """Try to connect a raw ACRIS party to a landlord — honestly. Type II.

    Because no resolution edge exists (§3.2), this **never** returns a confident
    single match. It states the gap and returns possibly-related landlords by
    shared name, each with ``compare_names`` evidence. If the actor already
    carries the ``:Landlord`` label, that is reported directly.
    """
    if not isinstance(actor_id, str) or not actor_id.strip():
        return {"found": False, "actor_id": repr(actor_id),
                "reason": "An actor_id is required."}
    actor = read(_ACTOR_CYPHER, {"actor_id": actor_id.strip()}).single
    if actor is None:
        return {"found": False, "actor_id": actor_id.strip(),
                "reason": f"No actor with actor_id {actor_id.strip()}."}

    name = actor["name"]
    if actor["is_landlord"]:
        return {"found": True, "actor_id": actor_id.strip(), "name": name,
                "is_landlord": True,
                "note": "This actor already carries the Landlord label; it is a "
                        "resolved landlord, not a raw party."}

    tokens = normalize(name)
    candidates: list[dict[str, Any]] = []
    if tokens:
        rows = read(_CANDIDATES_CYPHER, {"query": " ".join(tokens), "limit": 10}).records
        for r in rows:
            cmp = compare_names(name, r["name"])
            candidates.append({
                "actor_id": r["actor_id"], "name": r["name"],
                "building_count": r["building_count"],
                "match": {"verdict": cmp.verdict.value,
                          "shared_tokens": list(cmp.shared_tokens)},
            })

    return {
        "found": True, "actor_id": actor_id.strip(), "name": name,
        "is_landlord": False,
        "resolved_landlord": None,  # never a confident match — no resolution edge
        "possibly_related": candidates[:_HANDLE_CAP],
        "possibly_related_count": len(candidates),
        "note": _NO_RESOLUTION_NOTE,
    }
