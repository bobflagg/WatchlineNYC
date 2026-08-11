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
from collections import defaultdict
from typing import Any

from neo4j import READ_ACCESS, WRITE_ACCESS

from watchline.shared.connections import NEO4J_DISCOVERY_DATABASE, neo4j_driver

# Augmented projection: CONNECTED_BY_NAME edges UNION exact-name star edges. WCC over
# it resolves one operator per component, used everywhere (so numbers agree).
_NODE_QUERY = "MATCH (l:Landlord) RETURN id(l) AS id"
_REL_QUERY = (
    "MATCH (a:Landlord)-[:CONNECTED_BY_NAME]-(b:Landlord) "
    "RETURN id(a) AS source, id(b) AS target "
    "UNION "
    "MATCH (a:Landlord) WHERE a.name IS NOT NULL "
    "WITH a.name AS nm, collect(id(a)) AS ids WHERE size(ids) > 1 "
    "UNWIND ids[1..] AS t RETURN ids[0] AS source, t AS target"
)

# Leaderboard: rank resolved operators by buildings; also return each cluster's member
# actor_ids so the detail below can run in pure Cypher (no more GDS).
_LEADERBOARD = """
CALL gds.wcc.stream($graph) YIELD nodeId, componentId
WITH componentId, collect(gds.util.asNode(nodeId)) AS members
WITH componentId, members, size(members) AS records
WHERE records >= $min_records
CALL (members) {
  UNWIND members AS l
  OPTIONAL MATCH (l)-[:APPARENT_CONTROL]->(b:Building)
  RETURN collect(DISTINCT l.name) AS names, count(DISTINCT b) AS buildings
}
WITH componentId, records, [m IN members | m.actor_id] AS member_ids, names, buildings
WHERE buildings >= $min_buildings
RETURN componentId, names[0] AS operator, size(names) AS distinct_names, records, buildings, member_ids
ORDER BY buildings DESC
LIMIT $limit
"""

# Batched detail for every leaderboard component, keyed by actor_id (pure Cypher).
_DETAILS = """
UNWIND $rows AS row
UNWIND row.ids AS aid
MATCH (l:Landlord {actor_id: aid})
WITH row.cid AS cid, l, COUNT { (l)-[:APPARENT_CONTROL]->(:Building) } AS lb
OPTIONAL MATCH (l)-[:APPARENT_CONTROL]->(b:Building)
WITH cid, collect(DISTINCT b) AS bldgs,
     collect(DISTINCT {actor_id: l.actor_id, name: l.name, address: l.bizaddr, buildings: lb}) AS records
RETURN cid, records, size(bldgs) AS buildings,
       reduce(u = 0, b IN bldgs | u + coalesce(b.residential_units, 0)) AS residential_units,
       reduce(u = 0, b IN bldgs | u + coalesce(b.rs_units_current, 0)) AS rent_stabilized_units
"""

_EVENTS = """
UNWIND $rows AS row
UNWIND row.ids AS aid
MATCH (l:Landlord {actor_id: aid})-[:APPARENT_CONTROL]->(b:Building)
WITH row.cid AS cid, collect(DISTINCT b) AS bldgs
UNWIND bldgs AS b
MATCH (b)-[:HAS_EVENT]->(e:Event)
RETURN cid, e.event_type AS event_type, count(*) AS events
ORDER BY events DESC
"""

_NAME_EDGES = """
MATCH (a:Landlord)-[:CONNECTED_BY_NAME]-(b:Landlord)
WHERE a.actor_id IN $ids AND b.actor_id IN $ids AND a.actor_id < b.actor_id
RETURN DISTINCT a.actor_id AS source, b.actor_id AS target
"""

# One operator's event fingerprint (its records' buildings). Pure Cypher, read-only.
_OPERATOR_EVENTS = """
UNWIND $ids AS aid
MATCH (l:Landlord {actor_id: aid})-[:APPARENT_CONTROL]->(b:Building)
WITH DISTINCT b
MATCH (b)-[:HAS_EVENT]->(e:Event)
RETURN e.event_type AS event_type, count(*) AS events
ORDER BY events DESC
"""


_RECORD_BUILDINGS = """
MATCH (l:Landlord {actor_id: $aid})-[:APPARENT_CONTROL]->(b:Building)
WITH b ORDER BY coalesce(b.residential_units, 0) DESC LIMIT $limit
RETURN b.bbl AS bbl, b.address AS address, b.borough AS borough,
       coalesce(b.residential_units, 0) AS units,
       COUNT { (b)-[:HAS_EVENT]->() } AS events
"""


def record_buildings(actor_id: str, limit: int = 15) -> list[dict[str, Any]]:
    """The buildings one landlord record apparently controls (top by units), fetched
    lazily when its node is clicked in the interactive graph. Pure read-only Cypher."""
    with neo4j_driver().session(database=NEO4J_DISCOVERY_DATABASE,
                                default_access_mode=READ_ACCESS) as s:
        return [dict(r) for r in s.run(_RECORD_BUILDINGS, aid=actor_id, limit=limit)]


def operator_events(member_ids: list[str]) -> list[dict[str, Any]]:
    """Event fingerprint for one operator, fetched lazily on drill-down — scanning
    events for the whole leaderboard at once is too slow (~2 min), one operator is ~5s."""
    if not member_ids:
        return []
    with neo4j_driver().session(database=NEO4J_DISCOVERY_DATABASE,
                                default_access_mode=READ_ACCESS) as s:
        return [dict(r) for r in s.run(_OPERATOR_EVENTS, ids=member_ids)]


def top_operators(limit: int = 15, min_buildings: int = 40, *, hidden: bool = False,
                  with_events: bool = False) -> dict[str, Any]:
    """Rank resolved operators and return a full cluster (records, name-links,
    portfolio, events) for *each* leaderboard entry, keyed by component id — so a UI
    can switch between them without re-querying.

    ``hidden=True`` keeps only *fragmented* operators (clusters of >= 2 records),
    where identity resolution changes the answer. One augmented WCC resolution feeds
    the leaderboard and every detail, so the numbers agree.
    """
    min_records = 2 if hidden else 1
    graph = f"top_operators_{uuid.uuid4().hex[:8]}"
    driver = neo4j_driver()
    with driver.session(database=NEO4J_DISCOVERY_DATABASE, default_access_mode=WRITE_ACCESS) as s:
        try:
            s.run("CALL gds.graph.project.cypher($g, $nq, $rq)",
                  g=graph, nq=_NODE_QUERY, rq=_REL_QUERY).consume()
            board = [dict(r) for r in s.run(_LEADERBOARD, graph=graph, limit=limit,
                                            min_buildings=min_buildings, min_records=min_records)]
        finally:
            s.run("CALL gds.graph.drop($g, false)", g=graph).consume()

        rows = [{"cid": r["componentId"], "ids": r["member_ids"]} for r in board]
        all_ids = [aid for r in board for aid in r["member_ids"]]
        details = {r["cid"]: dict(r) for r in s.run(_DETAILS, rows=rows)} if rows else {}
        events: dict[Any, list] = defaultdict(list)
        if rows and with_events:
            for e in s.run(_EVENTS, rows=rows):
                events[e["cid"]].append({"event_type": e["event_type"], "events": e["events"]})
        cid_of = {aid: r["componentId"] for r in board for aid in r["member_ids"]}
        name_edges: dict[Any, list] = defaultdict(list)
        for edge in (s.run(_NAME_EDGES, ids=all_ids) if all_ids else []):
            cid = cid_of.get(edge["source"])
            if cid is not None and cid == cid_of.get(edge["target"]):
                name_edges[cid].append({"source": edge["source"], "target": edge["target"]})

    clusters: dict[Any, dict[str, Any]] = {}
    for r in board:
        cid = r["componentId"]
        d = details.get(cid, {})
        clusters[cid] = {
            "name": r["operator"],
            "records": d.get("records", []),
            "name_edges": name_edges.get(cid, []),
            "buildings": d.get("buildings", r["buildings"]),
            "residential_units": d.get("residential_units", 0),
            "rent_stabilized_units": d.get("rent_stabilized_units", 0),
            "events": events.get(cid, []),
        }

    leaderboard = [{k: r[k] for k in ("componentId", "operator", "distinct_names", "records", "buildings")}
                   for r in board]
    return {
        "view": "hidden operators — fragmented identity (>= 2 records)" if hidden else "top operators",
        "reliability": "II — inferred. APPARENT_CONTROL is a heuristic; identity is "
                       "CONNECTED_BY_NAME unioned with exact-name equality. distinct_names > 1 "
                       "flags a cross-name merge to check. Leads, not legal determinations.",
        "leaderboard": leaderboard,
        "clusters": clusters,
        "top_operator": clusters.get(board[0]["componentId"]) if board else {},
    }
