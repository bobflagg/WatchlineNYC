"""Diff and side-by-side comparison tools. Phase 4 Tier 3.

* `ownership_vs_registration_diff(bbl)` — aligns the three parties a building can
  present (DOF recorded owner, HPD-registered actor, apparent controller) and
  reports whether they agree, using the same guardrail-safe `compare_names`
  verdict the ownership tool uses. Never a determination; disagreement is the
  finding (P4-6).
* `compare_entities(...)` — runs an existing aggregation once per entity and
  aligns the results side by side, **never summed** (P4-4). It orchestrates the
  Phase 3 aggregate tools, so each per-entity result carries its own reliability.
"""

from __future__ import annotations

import re
from typing import Any

from ..db import read
from ..names import compare_names
from ..reliability import tagged
from .building import aggregate_building_events
from .landlord_portfolio import aggregate_landlord_portfolio_events

__all__ = [
    "ownership_vs_registration_diff",
    "compare_entities",
    "OWNERSHIP_VS_REGISTRATION_DIFF_DESCRIPTION",
    "COMPARE_ENTITIES_DESCRIPTION",
]

_BBL = re.compile(r"^[1-5][0-9]{9}$")
_ROLE_NOT_RECORDED = "role not recorded"
_MAX_COMPARE = 6


OWNERSHIP_VS_REGISTRATION_DIFF_DESCRIPTION = (
    "Compare the three parties a building can present, by BBL: the DOF-recorded "
    "owner, the HPD-registered party, and the apparent controller inferred by the "
    "graph. Reports whether they agree. Use for 'does the registered landlord "
    "match the owner', 'who's really behind this building'. The apparent "
    "controller is inferred, not confirmed; disagreement among the three is "
    "common and is itself informative. Takes a 10-digit BBL."
)

_DIFF_CYPHER = (
    "MATCH (b:Building {bbl: $bbl}) "
    "OPTIONAL MATCH (reg:Actor)-[r:REGISTERED_FOR]->(b) "
    "WITH b, [x IN collect(DISTINCT {actor_id: reg.actor_id, name: reg.name, role: r.role}) "
    "  WHERE x.actor_id IS NOT NULL][..10] AS registered "
    "OPTIONAL MATCH (ctrl:Landlord)-[:APPARENT_CONTROL]->(b) "
    "WITH b, registered, [x IN collect(DISTINCT {actor_id: ctrl.actor_id, name: ctrl.name}) "
    "  WHERE x.actor_id IS NOT NULL][..5] AS controllers "
    "RETURN b.bbl AS bbl, b.dof_ownername AS recorded_owner, registered, controllers"
)


def _verdict(left: str | None, right: str | None) -> dict[str, Any] | None:
    if not left or not right:
        return None
    cmp = compare_names(left, right)
    return {"verdict": cmp.verdict.value,
            "shared_distinguishing_tokens": list(cmp.shared_distinguishing)}


@tagged(["Building", "Building.dof_ownername", "REGISTERED_FOR", "Actor",
         "APPARENT_CONTROL", "Landlord"])
def ownership_vs_registration_diff(bbl: str) -> dict[str, Any]:
    """Align recorded owner, registered party, and apparent controller. Type II.

    ``REGISTERED_FOR`` originates on ``:Actor`` (not ``:Landlord``); a null role
    is shown as "role not recorded". Pairwise ``compare_names`` verdicts say
    whether the names agree, without asserting a determination.
    """
    if not isinstance(bbl, str) or not _BBL.match(bbl.strip()):
        return {"found": False, "bbl": bbl if isinstance(bbl, str) else repr(bbl),
                "reason": "Not a valid BBL (10 digits, borough 1-5)."}
    row = read(_DIFF_CYPHER, {"bbl": bbl.strip()}).single
    if row is None:
        return {"found": False, "bbl": bbl.strip(),
                "reason": f"No building in the discovery graph with BBL {bbl.strip()}."}

    recorded = row["recorded_owner"]
    registered = [{"actor_id": r["actor_id"], "name": r["name"],
                   "role": r["role"] or _ROLE_NOT_RECORDED,
                   "label": "registered with HPD"} for r in row["registered"]]
    controllers = [{"actor_id": c["actor_id"], "name": c["name"],
                    "label": "apparent controller"} for c in row["controllers"]]

    reg_name = registered[0]["name"] if registered else None
    ctrl_name = controllers[0]["name"] if controllers else None
    return {
        "found": True, "bbl": row["bbl"],
        "recorded_owner": ({"name": recorded, "label": "recorded owner",
                            "source": "DOF (dof_ownername)"} if recorded else None),
        "registered": registered,
        "apparent_controllers": controllers,
        "comparisons": {
            "recorded_vs_registered": _verdict(recorded, reg_name),
            "recorded_vs_controller": _verdict(recorded, ctrl_name),
            "registered_vs_controller": _verdict(reg_name, ctrl_name),
        },
    }


COMPARE_ENTITIES_DESCRIPTION = (
    "Compare several buildings, landlords, or portfolios side by side on the same "
    "event metric — e.g. 'compare the violation counts of these three buildings'. "
    "Runs the matching aggregation once per entity and aligns the results; it "
    "never sums across entities. Provide 2-6 entity ids of one kind "
    "(entity_kind='building' with BBLs, or 'landlord'/'portfolio' with ids), the "
    "source, and event type."
)


@tagged([])  # orchestrator: each per-entity result carries its own reliability
def compare_entities(
    entity_ids: list[str],
    entity_kind: str,
    source_name: str,
    event_type: str | None = None,
    since_months: int | None = None,
) -> dict[str, Any]:
    """Run an aggregation per entity and align results side by side. Never sums.

    ``entity_kind`` is ``'building'`` (BBLs → ``aggregate_building_events``) or
    ``'landlord'``/``'portfolio'`` (ids → ``aggregate_landlord_portfolio_events``).
    Each per-entity result keeps its own ``reliability``; there is deliberately no
    cross-entity total (P4-4).
    """
    if not isinstance(entity_ids, list) or not 2 <= len(entity_ids) <= _MAX_COMPARE:
        return {"error": "invalid_comparison",
                "reason": f"Provide 2 to {_MAX_COMPARE} entity ids to compare."}
    kind = str(entity_kind).strip().lower()
    if kind not in {"building", "landlord", "portfolio"}:
        return {"error": "invalid_entity_kind",
                "reason": "entity_kind must be 'building', 'landlord', or 'portfolio'."}

    since_years = None if since_months is None else max(1, round(since_months / 12))
    results: list[dict[str, Any]] = []
    for entity_id in entity_ids:
        if kind == "building":
            agg = aggregate_building_events(entity_id, source_name, event_type,
                                            since_months=since_months)
        else:
            key = {"portfolio_id" if kind == "portfolio" else "actor_id": entity_id}
            agg = aggregate_landlord_portfolio_events(
                source_name=source_name, event_type=event_type,
                since_years=since_years, **key)
        results.append({"entity_id": entity_id, "aggregate": agg})

    return {
        "entity_kind": kind, "source_name": source_name, "event_type": event_type,
        "metric": "event aggregation (aligned per entity, never summed)",
        "results": results,
        "count": len(results),
    }
