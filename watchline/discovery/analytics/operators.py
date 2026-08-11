"""GDS-backed operator analysis: resolve fragmented landlord identities and rank
operators by the portfolio they apparently control.

NOT the read-only agent path. GDS needs catalog access, which
:func:`watchline.discovery.agent.db.read` refuses by design (procedures, catalog
ops, multi-statement). This runs GDS on demand (project → WCC → drop) via its own
session; nothing is written to the graph *store* — only the ephemeral in-memory GDS
catalog, always dropped.

Production shape: precompute ``operator_id`` on Landlord nodes with this same
augmented WCC in the ingestion pipeline; the agent tool then becomes a trivial,
fast, read-only group-by — guard-clean.

Reliability: Type II (inferred). ``APPARENT_CONTROL`` is a heuristic; identity is
``CONNECTED_BY_NAME`` unioned with exact-name equality; ``distinct_names > 1`` in a
cluster flags a cross-name merge to check. Leads, not legal determinations.
"""

from __future__ import annotations

import uuid
from typing import Any

from neo4j import WRITE_ACCESS

from watchline.shared.connections import NEO4J_DISCOVERY_DATABASE, neo4j_driver

# Augmented projection: CONNECTED_BY_NAME edges UNION exact-name star edges. WCC over
# it resolves one operator per component, used by leaderboard + detail (so they agree).
_NODE_QUERY = "MATCH (l:Landlord) RETURN id(l) AS id"
_REL_QUERY = (
    "MATCH (a:Landlord)-[:CONNECTED_BY_NAME]-(b:Landlord) "
    "RETURN id(a) AS source, id(b) AS target "
    "UNION "
    "MATCH (a:Landlord) WHERE a.name IS NOT NULL "
    "WITH a.name AS nm, collect(id(a)) AS ids WHERE size(ids) > 1 "
    "UNWIND ids[1..] AS t RETURN ids[0] AS source, t AS target"
)

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

_NAME_EDGES = """
MATCH (a:Landlord)-[:CONNECTED_BY_NAME]-(b:Landlord)
WHERE a.actor_id IN $ids AND b.actor_id IN $ids AND a.actor_id < b.actor_id
RETURN DISTINCT a.actor_id AS source, b.actor_id AS target
"""


def top_operators(limit: int = 15, min_buildings: int = 40, *, hidden: bool = False) -> dict[str, Any]:
    """Return a ranked operator leaderboard + a resolved-cluster subgraph for #1.

    ``hidden=True`` restricts to *fragmented* operators — clusters of >= 2 records
    (aliases / misspelled variants), where identity resolution changes the answer.
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
