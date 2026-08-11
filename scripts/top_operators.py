"""Prototype: ``top_operators`` — resolve fragmented landlord identities and rank
operators by the portfolio they apparently control.

WHY A SCRIPT, NOT AN AGENT TOOL (yet)
-------------------------------------
It runs GDS on demand (project → WCC → drop), which needs catalog access. The
read-only agent path (:func:`watchline.discovery.agent.db.read`) deliberately refuses
procedures, catalog ops, and multi-statement queries — so GDS can't run there, by
design. Nothing here is written to the graph *store*; only the ephemeral in-memory
GDS catalog is used, and it is always dropped.

IDENTITY RESOLUTION (reconciled)
--------------------------------
Two landlord records are the SAME operator when the graph links them
(``CONNECTED_BY_NAME``) **or** they carry the identical name string. That union,
closed transitively by WCC over one augmented projection, gives a single
``operator`` used for both the leaderboard and the per-operator detail — so their
numbers always agree. (An earlier version ranked by edge-only WCC but detailed by
name, which disagreed: Castellano read 231 vs 356.)

PRODUCTION SHAPE
----------------
Precompute ``operator_id`` on Landlord nodes with one WCC job (this same augmented
resolution) in the ingestion pipeline. The agent tool then becomes a trivial, fast,
read-only query grouped by ``operator_id`` — guard-clean. This script is the
capability demo and the payload that tool will return: a ranked leaderboard plus a
resolved-cluster subgraph for the artifact panel.

RELIABILITY
-----------
Type II (inferred). ``APPARENT_CONTROL`` is a heuristic control determination; the
name-links are an identity-resolution signal — leads, not legal determinations.
Exact-name unioning can over-merge a very common name (two different "JOHN SMITH");
``distinct_names > 1`` in a cluster flags an edge-bridged, cross-name merge to check.

Run:  uv run python scripts/top_operators.py
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from neo4j import WRITE_ACCESS

from watchline.shared.connections import NEO4J_DISCOVERY_DATABASE, neo4j_driver

# --- Augmented projection: CONNECTED_BY_NAME edges UNION exact-name star edges --- #
# (gds.graph.project.cypher is deprecated; fine for a prototype — production would use
#  the current projection API and precompute the result anyway.)
_NODE_QUERY = "MATCH (l:Landlord) RETURN id(l) AS id"
_REL_QUERY = (
    "MATCH (a:Landlord)-[:CONNECTED_BY_NAME]-(b:Landlord) "
    "RETURN id(a) AS source, id(b) AS target "
    "UNION "
    "MATCH (a:Landlord) WHERE a.name IS NOT NULL "
    "WITH a.name AS nm, collect(id(a)) AS ids WHERE size(ids) > 1 "
    "UNWIND ids[1..] AS t RETURN ids[0] AS source, t AS target"
)

# Rank resolved operators (WCC components of the augmented graph) by buildings.
# `hidden` passes min_records=2 to keep only fragmented (multi-record) operators.
_LEADERBOARD = """
CALL gds.wcc.stream($graph) YIELD nodeId, componentId
WITH componentId, collect(gds.util.asNode(nodeId)) AS members
WITH componentId, members, size(members) AS records
WHERE records >= $min_records
UNWIND members AS l
OPTIONAL MATCH (l)-[:APPARENT_CONTROL]->(b:Building)
WITH componentId, records,
     collect(DISTINCT l.name) AS names,
     count(DISTINCT b) AS buildings
WHERE buildings >= $min_buildings
RETURN componentId, names[0] AS operator, size(names) AS distinct_names, records, buildings
ORDER BY buildings DESC
LIMIT $limit
"""

# Detail for one operator, keyed by the SAME componentId (same projection) so it
# reconciles with the leaderboard exactly.
_DETAIL = """
CALL gds.wcc.stream($graph) YIELD nodeId, componentId
WITH gds.util.asNode(nodeId) AS l, componentId
WHERE componentId = $component
WITH collect(l) AS members
UNWIND members AS l
OPTIONAL MATCH (l)-[:APPARENT_CONTROL]->(b:Building)
WITH members, collect(DISTINCT b) AS bldgs
RETURN
  [m IN members | {actor_id: m.actor_id, name: m.name, address: m.bizaddr,
                   buildings: COUNT { (m)-[:APPARENT_CONTROL]->(:Building) }}] AS records,
  size(bldgs) AS buildings,
  reduce(u = 0, b IN bldgs | u + coalesce(b.residential_units, 0)) AS residential_units,
  reduce(u = 0, b IN bldgs | u + coalesce(b.rs_units_current, 0)) AS rent_stabilized_units
"""

_EVENTS = """
CALL gds.wcc.stream($graph) YIELD nodeId, componentId
WITH gds.util.asNode(nodeId) AS l, componentId
WHERE componentId = $component
MATCH (l)-[:APPARENT_CONTROL]->(b:Building)
WITH DISTINCT b
MATCH (b)-[:HAS_EVENT]->(e:Event)
RETURN e.event_type AS event_type, count(*) AS events
ORDER BY events DESC
"""

# CONNECTED_BY_NAME edges within the cluster — the "resolved identity" subgraph.
_NAME_EDGES = """
MATCH (a:Landlord)-[:CONNECTED_BY_NAME]-(b:Landlord)
WHERE a.actor_id IN $ids AND b.actor_id IN $ids AND a.actor_id < b.actor_id
RETURN DISTINCT a.actor_id AS source, b.actor_id AS target
"""


def top_operators(limit: int = 15, min_buildings: int = 40, *, hidden: bool = False) -> dict[str, Any]:
    """Return a ranked operator leaderboard + a resolved-cluster subgraph for #1.

    ``hidden=True`` restricts to *fragmented* operators — clusters of >= 2 records
    (aliases / misspelled variants), i.e. the ones whose true portfolio a per-record
    (relational) view would split apart. That is where identity resolution is the win.

    Leaderboard and detail share one augmented WCC resolution, so their numbers agree.
    """
    min_records = 2 if hidden else 1
    graph = f"top_operators_{uuid.uuid4().hex[:8]}"
    driver = neo4j_driver()
    with driver.session(database=NEO4J_DISCOVERY_DATABASE, default_access_mode=WRITE_ACCESS) as s:
        try:
            s.run("CALL gds.graph.project.cypher($g, $nq, $rq)",
                  g=graph, nq=_NODE_QUERY, rq=_REL_QUERY).consume()
            leaderboard = [
                dict(r) for r in s.run(_LEADERBOARD, graph=graph, limit=limit,
                                       min_buildings=min_buildings, min_records=min_records)
            ]
            detail: dict[str, Any] = {}
            if leaderboard:
                component = leaderboard[0]["componentId"]
                row = s.run(_DETAIL, graph=graph, component=component).single()
                detail = dict(row) if row else {}
                ids = [r["actor_id"] for r in detail.get("records", [])]
                detail["name_edges"] = [dict(e) for e in s.run(_NAME_EDGES, ids=ids)]
                detail["events"] = [dict(e) for e in s.run(_EVENTS, graph=graph, component=component)]
        finally:
            s.run("CALL gds.graph.drop($g, false)", g=graph).consume()

    top = leaderboard[0]["operator"] if leaderboard else None
    return {
        "view": "hidden operators — fragmented identity (>= 2 records)" if hidden else "top operators",
        "reliability": "II — inferred. APPARENT_CONTROL is a heuristic; identity is "
                       "CONNECTED_BY_NAME unioned with exact-name equality. distinct_names > 1 "
                       "flags a cross-name merge to check. Leads, not legal determinations.",
        "leaderboard": leaderboard,
        "top_operator": {"name": top, **detail},
    }


def _print(payload: dict[str, Any]) -> None:
    print(f"\n=== {payload.get('view', 'top operators')} (ranked by buildings) ===")
    for i, r in enumerate(payload["leaderboard"], 1):
        frag = "" if r["records"] == 1 else f"  ({r['records']} records unified)"
        print(f"{i:>2}. {r['operator']:<24} {r['buildings']:>4} buildings{frag}")

    op = payload["top_operator"]
    print(f"\n=== #1 resolved: {op['name']} ===")
    print(f"  buildings: {op.get('buildings')} · residential units: "
          f"{op.get('residential_units')} · rent-stabilized: {op.get('rent_stabilized_units')}")
    print(f"  records unified ({len(op.get('records', []))}):")
    for rec in op.get("records", []):
        print(f"    - {rec['actor_id']}  {rec.get('buildings', 0):>3} bldgs  {rec.get('address')}")
    print(f"  name-links in cluster: {len(op.get('name_edges', []))}")
    ev = op.get("events", [])
    if ev:
        print("  event fingerprint: " + ", ".join(f"{e['event_type']} {e['events']:,}" for e in ev[:6]))
    print("\n(subgraph nodes+edges are in the payload for the artifact panel)")


if __name__ == "__main__":
    payload = top_operators(hidden=True)   # the "hidden operators" view (fragmented identity)
    _print(payload)
    print("\n--- raw payload (first 1200 chars) ---")
    print(json.dumps(payload, default=str)[:1200])
