"""
Watchline agents pipeline -- store stage.

Writes ManagingAgent Actor nodes and ManagedBy Relationship nodes
to Neo4j from the deduplicated agent list produced by load.py.

Ontology mapping:
    Layer 3 (Identity):
        IdentityObservation  -- one per unique agent (name+address)
    Layer 1 (Domain):
        Actor {actor_type: 'ManagingAgent'}  -- one per unique agent
    Layer 4 (Interpretation):
        Relationship {relationship_type: 'ManagedBy'}
            -- one per (building, managing_agent) pair

Rule reference:
    MA-001 (RUL-00009): Management Differential
        Registered in 02_seed_rules.cypher. Evaluation pipeline not
        yet implemented; ManagedBy relationships are the prerequisite
        data for future MA-001 evaluation.

Design notes:
    - canonical_id is UUID5-derived (stable across runs) -- see load.py
    - MERGE on canonical_id makes all writes idempotent
    - CASE WHEN IS NULL pattern used throughout (ON CREATE SET removed
      in Cypher 25, consistent with store.py in portfolio pipeline)
    - ManagedBy Relationship IDs follow the same pattern as
      BeneficialControl: 'REL-MGT-{agent_short}-{bbl}'
    - Source node for HPD registrations is shared with portfolio pipeline
      (SRC-HPD-REGISTRATIONS-001); no new Source node is needed
"""

import uuid
from datetime import datetime, timezone
from typing import List

from neo4j import Session

BATCH_SIZE    = 200
RULE_ID_MA001 = "RUL-00009"
SOURCE_ID     = "SRC-HPD-REGISTRATIONS-001"


# ---------------------------------------------------------------------------
# ManagingAgent Actor nodes
# ---------------------------------------------------------------------------

def _upsert_managing_agents(session: Session, agents: List[dict]) -> None:
    """
    Create or update ManagingAgent Actor nodes.
    One node per unique managing agent (keyed on canonical_id).
    """
    now = datetime.now(timezone.utc).isoformat()

    cypher = """
        UNWIND $batch AS a
        MERGE (actor:Actor:WatchlineNode {canonical_id: a.canonical_id})
        SET actor.actor_type          = 'ManagingAgent',
            actor.display_name        = a.display_name,
            actor.business_address    = a.norm_address,
            actor.biz_housenumber     = a.biz_housenumber,
            actor.biz_streetname      = a.biz_streetname,
            actor.biz_apartment       = a.biz_apartment,
            actor.biz_zip             = a.biz_zip,
            actor.resolution_confidence = 'Medium',
            actor.updated_at          = datetime($now),
            actor.created_at          = CASE WHEN actor.created_at IS NULL
                                             THEN datetime($now)
                                             ELSE actor.created_at END
    """

    total = _write_batches(
        session, cypher,
        (
            {
                "canonical_id":  a["canonical_id"],
                "display_name":  a["display_name"],
                "norm_address":  a["norm_address"],
                "biz_housenumber": a["biz_housenumber"],
                "biz_streetname":  a["biz_streetname"],
                "biz_apartment":   a["biz_apartment"],
                "biz_zip":         a["biz_zip"],
            }
            for a in agents
        ),
        now=now,
    )
    print(f"  {total:,} ManagingAgent Actor nodes written.")


# ---------------------------------------------------------------------------
# IdentityObservation nodes for managing agents
# ---------------------------------------------------------------------------

def _upsert_identity_observations(session: Session, agents: List[dict]) -> None:
    """
    Create IdentityObservation nodes for each managing agent and link
    them to the Source node and their Actor node.

    One IdentityObservation per unique agent (keyed on norm_name + norm_address).
    """
    now = datetime.now(timezone.utc).isoformat()

    cypher = """
        UNWIND $batch AS a
        MERGE (io:IdentityObservation:WatchlineNode {
            raw_name:  a.norm_name,
            source_id: $source_id,
            context:   a.context
        })
        SET io.iobs_id        = CASE WHEN io.iobs_id IS NULL
                                     THEN a.iobs_id ELSE io.iobs_id END,
            io.ingested_at    = CASE WHEN io.ingested_at IS NULL
                                     THEN datetime($now) ELSE io.ingested_at END,
            io.observation_id = CASE WHEN io.observation_id IS NULL
                                     THEN a.iobs_id ELSE io.observation_id END
        WITH io, a
        MATCH (s:Source {source_id: $source_id})
        MERGE (io)-[:ORIGINATES_IN]->(s)
        WITH io, a
        MATCH (actor:Actor {canonical_id: a.canonical_id})
        MERGE (actor)-[:RESOLVED_FROM]->(io)
    """

    params = [
        {
            "canonical_id": a["canonical_id"],
            "norm_name":    a["norm_name"] or a["display_name"],
            "context": (
                f"HPD managing agent contact; "
                f"address: {a['norm_address']}; "
                f"buildings: {len(a['bbls'])}"
            ),
            "iobs_id": f"IOBS-MGT-{uuid.uuid4()}",
        }
        for a in agents
    ]

    _write_batches(session, cypher, iter(params), source_id=SOURCE_ID, now=now)
    print(f"  {len(agents):,} IdentityObservation nodes written.")


# ---------------------------------------------------------------------------
# ManagedBy Relationship nodes
# ---------------------------------------------------------------------------

def _upsert_managed_by_relationships(session: Session, agents: List[dict]) -> None:
    """
    Create ManagedBy Relationship nodes linking each Building to its
    ManagingAgent Actor.

    Buildings that do not yet exist in the graph are silently skipped
    (MATCH will find nothing; MERGE on Relationship will not fire).
    This mirrors the deferred reconcile pattern in the portfolio pipeline.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    now   = datetime.now(timezone.utc).isoformat()

    # Flatten agents into (bbl, canonical_id) pairs for batching
    pairs = []
    for a in agents:
        short = a["canonical_id"][4:12]  # strip 'MGT-' prefix, take 8 chars
        for bbl in a["bbls"]:
            pairs.append({
                "bbl":              bbl,
                "canonical_id":     a["canonical_id"],
                "canonical_short":  short,
                "display_name":     a["display_name"],
                "norm_address":     a["norm_address"],
            })

    cypher = """
        UNWIND $batch AS row
        MATCH  (b:Building {bbl: row.bbl})
        MATCH  (a:Actor    {canonical_id: row.canonical_id})
        MATCH  (r:Rule     {rule_id: $rule_id})
        MERGE  (rel:Relationship:WatchlineNode {
            relationship_id: 'REL-MGT-' + row.canonical_short + '-' + row.bbl
        })
        SET rel.relationship_type   = 'ManagedBy',
            rel.subject_id          = CASE WHEN rel.subject_id IS NULL
                                           THEN row.bbl ELSE rel.subject_id END,
            rel.object_id           = CASE WHEN rel.object_id IS NULL
                                           THEN row.canonical_id ELSE rel.object_id END,
            rel.interpretive_status = CASE WHEN rel.interpretive_status IS NULL
                                           THEN 'Observed' ELSE rel.interpretive_status END,
            rel.basis               = CASE WHEN rel.basis IS NULL
                                           THEN 'HPD registration contact (title=Agent): ' + row.norm_address
                                           ELSE rel.basis END,
            rel.effective_from      = CASE WHEN rel.effective_from IS NULL
                                           THEN date($today) ELSE rel.effective_from END,
            rel.created_at          = CASE WHEN rel.created_at IS NULL
                                           THEN datetime($now) ELSE rel.created_at END
        WITH rel, a, b, r
        MERGE (rel)-[:INVOLVES_ACTOR]   ->(a)
        MERGE (rel)-[:INVOLVES_BUILDING]->(b)
        MERGE (rel)-[:PRODUCED_BY]      ->(r)
    """

    total = _write_batches(
        session, cypher, iter(pairs),
        rule_id=RULE_ID_MA001,
        today=today,
        now=now,
    )
    print(f"  {total:,} ManagedBy Relationship nodes written.")

    skipped = len(pairs) - total
    if skipped:
        print(f"  {skipped:,} BBLs skipped (Building not yet in graph).")


# ---------------------------------------------------------------------------
# Shared batch writer (mirrors load.py pattern)
# ---------------------------------------------------------------------------

def _write_batches(
    session: Session,
    cypher: str,
    param_iter,
    **extra_params,
) -> int:
    """Write param_iter to Neo4j in BATCH_SIZE chunks. Returns total rows written."""
    total = 0
    batch = []
    for params in param_iter:
        batch.append(params)
        if len(batch) == BATCH_SIZE:
            result = session.run(cypher, batch=batch, **extra_params)
            total += len(batch)
            result.consume()
            batch = []
    if batch:
        result = session.run(cypher, batch=batch, **extra_params)
        total += len(batch)
        result.consume()
    return total


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(session: Session, agents: List[dict]) -> None:
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    print(f"Step 3 -- Writing ManagingAgent nodes (run={now_str})")

    print("  Upserting ManagingAgent Actor nodes ...")
    _upsert_managing_agents(session, agents)

    print("  Upserting IdentityObservation nodes ...")
    _upsert_identity_observations(session, agents)

    print("  Upserting ManagedBy Relationship nodes ...")
    _upsert_managed_by_relationships(session, agents)

    print("  Store complete.")
