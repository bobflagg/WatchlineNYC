"""Prototype: ``top_operators`` — resolve fragmented landlord identities via the
name-connection network and rank operators by the portfolio they apparently control.

WHY A SCRIPT, NOT AN AGENT TOOL (yet)
-------------------------------------
It runs GDS on demand (project → WCC → drop), which needs catalog access. The
read-only agent path (:func:`watchline.discovery.agent.db.read`) deliberately refuses
procedures, catalog ops, and multi-statement queries — so GDS can't run there, by
design. Nothing here is written to the graph *store*; only the ephemeral in-memory
GDS catalog is used, and it is always dropped.

PRODUCTION SHAPE
----------------
Precompute ``operator_id`` on Landlord nodes with one WCC job in the ingestion
pipeline. The agent tool then becomes a trivial, fast, read-only query grouped by
``operator_id`` — guard-clean. This script is the capability demo and the payload
that tool will return: a ranked leaderboard plus a resolved-cluster subgraph for the
artifact panel.

RELIABILITY
-----------
Type II (inferred). ``APPARENT_CONTROL`` is a heuristic control determination, and
the name-links are an identity-resolution signal — leads to investigate, not legal
determinations. Event counts are raw public-record tallies.

Run:  uv run python scripts/top_operators.py
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from neo4j import WRITE_ACCESS

from watchline.shared.connections import NEO4J_DISCOVERY_DATABASE, neo4j_driver

# --- Cypher ---------------------------------------------------------------- #

# Resolve every building-controlling landlord to its name-cluster (WCC over the
# name layer), then rank clusters by distinct buildings controlled. Un-fragmented
# landlords are singleton clusters, so they rank too.
_LEADERBOARD = """
CALL gds.wcc.stream($graph, {relationshipTypes: ['CONNECTED_BY_NAME']})
  YIELD nodeId, componentId
WITH componentId, collect(gds.util.asNode(nodeId)) AS members
WITH componentId, members, size(members) AS records
WHERE records >= $min_records
UNWIND members AS l
OPTIONAL MATCH (l)-[:APPARENT_CONTROL]->(b:Building)
WITH componentId, records,
     collect(DISTINCT l.name) AS names,
     count(DISTINCT b) AS buildings
WHERE buildings >= $min_buildings
RETURN names[0] AS operator, size(names) AS distinct_names, records, buildings
ORDER BY buildings DESC
LIMIT $limit
"""

# Detail for one operator, resolved by name-expansion (pure Cypher — read-only, no
# GDS). This is exactly what the production read-only tool would run per operator.
_DETAIL = """
MATCH (seed:Landlord {name: $operator})
MATCH (seed)-[:CONNECTED_BY_NAME*0..6]-(m:Landlord)
WITH collect(DISTINCT m) AS members
UNWIND members AS l
OPTIONAL MATCH (l)-[:APPARENT_CONTROL]->(b:Building)
WITH members, collect(DISTINCT b) AS bldgs
RETURN
  [m IN members | {actor_id: m.actor_id, address: m.bizaddr,
                   buildings: COUNT { (m)-[:APPARENT_CONTROL]->(:Building) }}] AS records,
  size(bldgs) AS buildings,
  reduce(u = 0, b IN bldgs | u + coalesce(b.residential_units, 0)) AS residential_units,
  reduce(u = 0, b IN bldgs | u + coalesce(b.rs_units_current, 0)) AS rent_stabilized_units
"""

# The CONNECTED_BY_NAME edges within a cluster — the "resolved identity" subgraph
# for the artifact panel.
_NAME_EDGES = """
MATCH (a:Landlord)-[:CONNECTED_BY_NAME]-(b:Landlord)
WHERE a.actor_id IN $ids AND b.actor_id IN $ids AND a.actor_id < b.actor_id
RETURN DISTINCT a.actor_id AS source, b.actor_id AS target
"""

# Event fingerprint across the operator's portfolio.
_EVENTS = """
MATCH (seed:Landlord {name: $operator})
MATCH (seed)-[:CONNECTED_BY_NAME*0..6]-(m:Landlord)
WITH DISTINCT m
MATCH (m)-[:APPARENT_CONTROL]->(b:Building)
WITH DISTINCT b
MATCH (b)-[:HAS_EVENT]->(e:Event)
RETURN e.event_type AS event_type, count(*) AS events
ORDER BY events DESC
"""


def top_operators(limit: int = 15, min_buildings: int = 40, *, hidden: bool = False) -> dict[str, Any]:
    """Return a ranked operator leaderboard + a resolved-cluster subgraph for #1.

    ``hidden=True`` restricts to *fragmented* operators — name-clusters of >= 2 records
    (aliases / misspelled variants), i.e. the ones whose true portfolio a per-record
    (relational) view would split apart. That is where identity resolution is the win.

    Structure matches what the production read-only tool would emit, so the UI /
    artifact panel can be built against it now.
    """
    min_records = 2 if hidden else 1
    graph = f"top_operators_{uuid.uuid4().hex[:8]}"
    driver = neo4j_driver()
    with driver.session(database=NEO4J_DISCOVERY_DATABASE, default_access_mode=WRITE_ACCESS) as s:
        try:
            s.run(
                "CALL gds.graph.project($g, 'Landlord', "
                "{CONNECTED_BY_NAME: {orientation: 'UNDIRECTED'}})",
                g=graph,
            ).consume()
            leaderboard = [
                dict(r) for r in s.run(_LEADERBOARD, graph=graph, limit=limit,
                                       min_buildings=min_buildings, min_records=min_records)
            ]
        finally:
            s.run("CALL gds.graph.drop($g, false)", g=graph).consume()

        top = leaderboard[0]["operator"] if leaderboard else None
        detail: dict[str, Any] = {}
        if top:
            row = s.run(_DETAIL, operator=top).single()
            detail = dict(row) if row else {}
            ids = [r["actor_id"] for r in detail.get("records", [])]
            detail["name_edges"] = [dict(e) for e in s.run(_NAME_EDGES, ids=ids)]
            detail["events"] = [dict(e) for e in s.run(_EVENTS, operator=top)]

    return {
        "view": "hidden operators — fragmented identity (>= 2 records)" if hidden else "top operators",
        "reliability": "II — inferred (APPARENT_CONTROL heuristic; name-link identity "
                       "resolution). Leads to investigate, not legal determinations.",
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
