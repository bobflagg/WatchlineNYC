"""owner_relationships.py — the C4 substantive relationship layer (Option B, Phase 2).

Owner-**association** signals that are NOT identity, expressed as **typed relationships between resolved
entities** (their `resolution_id` from `resolved_entity`), never as merges:

- **`co_grantee_on_deed`** — from `CONNECTED_BY_DEED` (method `acris-deed` held / `acris-deed-linked-successor`,
  kept distinct). The canonical substrate is the existing `:Event {event_type:'DeedTransfer'}` + `PARTY_TO`;
  this pairwise edge is the derived convenience view.
- **`associated_via_reported_owner_entity`** — from `CONNECTED_BY_SPLINK` method `registered-llc`
  (name-only), which F1/R3 removed from identity (it links co-officers = distinct people of one LLC).

Endpoints are mapped to `resolution_id` and **deduped**; an edge whose endpoints resolve to the **same**
entity is an intra-entity edge and is dropped (not a cross-entity relationship). These feed the eventual
common-control admissibility rule (Phase 6), never identity resolution.

Pure core (`to_entity_relationships`) is hermetic; the reads are read-only Neo4j.
"""
from __future__ import annotations

from collections import Counter, defaultdict

DEED_REL = "co_grantee_on_deed"
LLC_REL = "associated_via_reported_owner_entity"


def to_entity_relationships(edges: list[dict], partition: dict) -> dict:
    """Map raw landlord-node relationship edges to deduped **entity-level** relationships.

    ``edges``: ``[{"a","b","rel_type","method"?}, …]`` (node ids). ``partition``: ``{nodeid: resolution_id}``
    from the identity layer; a node absent from it is its own singleton entity (``RE-<nodeid>``, matching
    `resolved_entity`). Returns ``{relationships, self_dropped}`` where each relationship is
    ``{rel_type, a, b, methods, edges}`` between two distinct `resolution_id`s (a ≤ b), aggregating all
    contributing raw edges/methods; intra-entity edges are counted in ``self_dropped``.
    """
    def resid(n):
        return partition.get(n) or f"RE-{n}"

    agg: dict = {}
    self_dropped = 0
    for e in edges:
        ea, eb = resid(e["a"]), resid(e["b"])
        if ea == eb:                                   # both endpoints are the same resolved entity
            self_dropped += 1
            continue
        lo, hi = (ea, eb) if ea <= eb else (eb, ea)
        key = (e["rel_type"], lo, hi)
        rec = agg.get(key)
        if rec is None:
            rec = agg[key] = {"rel_type": e["rel_type"], "a": lo, "b": hi,
                              "methods": Counter(), "edges": 0}
        rec["methods"][e.get("method", "")] += 1
        rec["edges"] += 1
    rels = [{"rel_type": r["rel_type"], "a": r["a"], "b": r["b"],
             "methods": dict(r["methods"]), "edges": r["edges"]} for r in agg.values()]
    return {"relationships": rels, "self_dropped": self_dropped}


# --- graph read (read-only) ---------------------------------------------------------------------

_Q_DEED = ("MATCH (a:Landlord)-[r:CONNECTED_BY_DEED]-(b:Landlord) WHERE a.nodeid < b.nodeid "
           "RETURN a.nodeid AS a, b.nodeid AS b, coalesce(r.method, 'acris-deed') AS method")
_Q_LLC = ("MATCH (a:Landlord)-[r:CONNECTED_BY_SPLINK]-(b:Landlord) "
          "WHERE a.nodeid < b.nodeid AND coalesce(r.method,'') = 'registered-llc' "
          "RETURN a.nodeid AS a, b.nodeid AS b, 'registered-llc' AS method")


def read_relationship_edges(driver, *, database: str) -> list[dict]:
    """Read the raw association edges (deed + name-only registered-llc) at the landlord-node level."""
    with driver.session(database=database) as s:
        deed = [{"a": r["a"], "b": r["b"], "rel_type": DEED_REL, "method": r["method"]}
                for r in s.run(_Q_DEED)]
        llc = [{"a": r["a"], "b": r["b"], "rel_type": LLC_REL, "method": r["method"]}
               for r in s.run(_Q_LLC)]
    return deed + llc


def read_relationships(driver, *, database: str, partition: dict) -> dict:
    """Read the association edges and project them to entity-level relationships under `partition`."""
    return to_entity_relationships(read_relationship_edges(driver, database=database), partition)
