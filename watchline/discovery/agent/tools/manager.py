"""Management-layer tools — the Manager / MANAGED_BY layer.

Who *manages* a building, as distinct from who *owns* or *controls* it. The
managing agent is self-disclosed on the HPD registration; ``managed_by`` in the
ingest normalizes it to one brand key across spelling and corporate-form
variants and materializes ``(:Building)-[:MANAGED_BY]->(:Manager)``.

This is deliberately a *different question* from ownership. The same agent
commonly manages buildings for many unrelated owners, so a shared manager is
**not** evidence of common ownership — the exact conflation the three-layer
model exists to avoid. Every result is **Type II** and ships the canonical
Manager caveat automatically (a manager is not an owner; wording lives in
:mod:`..caveats`); ``building_count`` is read from the node, not recomputed.
"""

from __future__ import annotations

from typing import Any

from ..db import read
from ..reliability import tagged

__all__ = [
    "building_manager",
    "manager_portfolio",
    "BUILDING_MANAGER_DESCRIPTION",
    "MANAGER_PORTFOLIO_DESCRIPTION",
]

#: Cap the building sample a manager tool streams; the precomputed count carries
#: the total (CLAUDE.md: compact large outputs).
_SAMPLE_CAP = 15

BUILDING_MANAGER_DESCRIPTION = (
    "Find who MANAGES a specific building, by BBL — the self-disclosed managing "
    "agent, distinct from who owns or controls it. Returns the manager and how "
    "many buildings that agent manages. Call this when the user asks who manages "
    "or is the managing agent of a building, or to separate management from "
    "ownership. A manager is not an owner; managing agents run buildings for many "
    "unrelated owners. Takes a 10-digit BBL, not an address."
)

MANAGER_PORTFOLIO_DESCRIPTION = (
    "Show the buildings a managing agent runs, by manager_id: the total count and "
    "a sample. Use this to see a manager's footprint. A shared manager is NOT "
    "evidence of common ownership — many unrelated owners use the same agent."
)

_BUILDING_MANAGER_CYPHER = (
    "MATCH (b:Building {bbl: $bbl}) "
    "OPTIONAL MATCH (b)-[:MANAGED_BY]->(m:Manager) "
    "RETURN b.bbl AS bbl, b.address AS address, "
    "CASE WHEN m IS NULL THEN NULL ELSE { "
    "  manager_id: m.manager_id, name: m.name, building_count: m.building_count, "
    "  method: m.method, generated_at: toString(m.generated_at) "
    "} END AS manager"
)

_MANAGER_PORTFOLIO_CYPHER = (
    "MATCH (m:Manager {manager_id: $manager_id}) "
    "OPTIONAL MATCH (b:Building)-[:MANAGED_BY]->(m) "
    "WITH m, collect(b)[0..$cap] AS sample "
    "RETURN m.manager_id AS manager_id, m.name AS name, "
    "m.building_count AS building_count, m.method AS method, "
    "toString(m.generated_at) AS generated_at, "
    "[ x IN sample | {bbl: x.bbl, address: x.address, borough: x.borough} ] AS buildings_sample"
)


def _is_bbl(value: Any) -> bool:
    return isinstance(value, str) and value.strip().isdigit() and len(value.strip()) == 10


@tagged(["Building", "MANAGED_BY", "Manager"])
def building_manager(bbl: str) -> dict[str, Any]:
    """Return a building's self-disclosed managing agent. Type II.

    ``manager`` is ``None`` for a building with no managing agent on record — a
    normal, complete answer, not an error. The Manager caveat travels with the
    result: a manager is not an owner.
    """
    if not _is_bbl(bbl):
        return {
            "found": False,
            "bbl": bbl if isinstance(bbl, str) else repr(bbl),
            "reason": "A 10-digit BBL is required (borough digit, 5-digit block, "
            "4-digit lot) — for example '1005930008'.",
        }
    row = read(_BUILDING_MANAGER_CYPHER, {"bbl": bbl.strip()}).single
    if row is None:
        return {
            "found": False,
            "bbl": bbl.strip(),
            "reason": f"No building in the discovery graph with BBL {bbl.strip()}.",
        }
    manager = row["manager"]
    return {
        "found": True,
        "bbl": row["bbl"],
        "address": row["address"],
        "manager": manager,
        "note": (
            None
            if manager is not None
            else "No managing agent is recorded for this building."
        ),
    }


@tagged(["Manager", "MANAGED_BY", "Building"])
def manager_portfolio(manager_id: str) -> dict[str, Any]:
    """Return the buildings a managing agent runs. Type II.

    ``building_count`` is read from the ``Manager`` node; ``buildings_sample`` is
    a capped summary. A shared manager is not evidence of common ownership.
    """
    if not isinstance(manager_id, str) or not manager_id.strip():
        return {
            "found": False,
            "manager_id": manager_id if isinstance(manager_id, str) else repr(manager_id),
            "reason": "A manager_id is required.",
        }
    row = read(
        _MANAGER_PORTFOLIO_CYPHER, {"manager_id": manager_id.strip(), "cap": _SAMPLE_CAP}
    ).single
    if row is None:
        return {
            "found": False,
            "manager_id": manager_id.strip(),
            "reason": f"No manager in the discovery graph with manager_id "
            f"{manager_id.strip()}.",
        }
    return {
        "found": True,
        "manager_id": row["manager_id"],
        "name": row["name"],
        "building_count": row["building_count"],
        "buildings_sample": row["buildings_sample"],
        "provenance": {"method": row["method"], "generated_at": row["generated_at"]},
    }
