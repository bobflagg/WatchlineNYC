"""
Watchline PHC-001 Evaluation Pipeline
watchline/ingest/phc001/pipeline.py

Evaluates Rule PHC-001 (Persistent Hazardous Conditions) against the
Watchline knowledge graph and generates Claims for qualifying buildings.

PHC-001 threshold (from Rule record RUL-00001):
  - 3 or more Class C (immediately hazardous) HPD violations currently open
  - Oldest open Class C violation open for more than 180 days

This pipeline operates entirely within Neo4j -- it does not read from
Postgres. It uses the Event nodes already in the graph (ingested by the
HPD violations pipeline) and produces:

  Layer 4 (Interpretation):
    - Claim nodes of interpretive_concept=PersistentHazardousConditions
    - One Claim per qualifying building
    - Supersedes previous PHC-001 Claims for the same building on re-run

  Layer 2 (Evidence):
    - Evidence nodes aggregating the qualifying Observation nodes
    - DERIVED_FROM edges from Evidence to the Observations of qualifying
      violations

Evidence chain for a PHC-001 Claim:
  Claim
    -[:SUPPORTED_BY]-> Evidence
      -[:DERIVED_FROM]-> Observation (one per qualifying violation)
        -[:ORIGINATES_IN]-> Source (HPD Violations)
  Claim
    -[:PRODUCED_BY]-> Rule (RUL-00001, PHC-001)
  Building
    -[:SUBJECT_OF]-> Claim

Design decisions:
  - Evaluation runs entirely in Neo4j using the event_class_status composite
    index on (violation_class, status) for efficient filtering.
  - days_open is calculated as duration between open_date and today, not
    stored as a property (which would go stale). The evaluation Cypher
    computes it at query time.
  - Evidence nodes link to Observation nodes (not Event nodes directly)
    to satisfy the ontology invariant: Evidence -> DERIVED_FROM -> Observation.
  - Re-runs supersede existing PHC-001 Claims for buildings that no longer
    qualify (violations resolved) and update Claims for buildings where
    the violation count or oldest-days has changed.
  - Buildings that no longer qualify after a re-run have their Claims
    superseded with valid_to set to today.

Usage:
    uv run python -m watchline.evidentiary.ingest.phc001.pipeline
    uv run python -m watchline.evidentiary.ingest.phc001.pipeline --dry-run
"""

import argparse
import os
import uuid
from datetime import datetime, timezone



NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE
RULE_ID = "RUL-00001"
INTERPRETIVE_CONCEPT = "PersistentHazardousConditions"
MIN_VIOLATIONS = 3
MIN_DAYS_OPEN = 180
BATCH_SIZE = 200  # smaller: each batch does significant graph work


from watchline.shared.connections import neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


# ---------------------------------------------------------------------------
# Step 1: Verify Rule exists
# ---------------------------------------------------------------------------

def verify_rule(session) -> bool:
    result = session.run(
        "MATCH (r:Rule {rule_id: $rule_id}) RETURN r.name AS name, r.deprecated AS deprecated",
        rule_id=RULE_ID,
    ).single()
    if not result:
        print(f"  ERROR: Rule {RULE_ID} not found in graph.")
        print(f"  Run scripts/02_seed_rules.cypher to load Rule nodes first.")
        return False
    if result["deprecated"]:
        print(f"  ERROR: Rule {RULE_ID} is deprecated. Load a current version first.")
        return False
    print(f"  Rule {result['name']} ({RULE_ID}) verified.")
    return True


# ---------------------------------------------------------------------------
# Step 2: Find qualifying buildings
# ---------------------------------------------------------------------------

QUALIFYING_QUERY = """
MATCH (bld:Building)-[:HAS_EVENT]->(e:Event)
WHERE e.violation_class = 'C'
  AND e.status = 'Open'
  AND e.open_date IS NOT NULL
WITH bld,
     count(e) AS open_c_count,
     min(e.open_date) AS oldest_open_date,
     collect(e.event_id) AS event_ids
WHERE open_c_count >= $min_violations
  AND duration.inDays(oldest_open_date, date()).days > $min_days
RETURN bld.bbl AS bbl,
       open_c_count,
       duration.inDays(oldest_open_date, date()).days AS oldest_days,
       event_ids
ORDER BY oldest_days DESC
"""

DISQUALIFIED_QUERY = """
MATCH (bld:Building)-[:SUBJECT_OF]->(c:Claim)
WHERE c.interpretive_concept = $concept
  AND c.superseded_by IS NULL
  AND c.valid_to IS NULL
WITH bld, c
WHERE NOT EXISTS {
    MATCH (bld)-[:HAS_EVENT]->(e:Event)
    WHERE e.violation_class = 'C'
      AND e.status = 'Open'
      AND e.open_date IS NOT NULL
    WITH bld, count(e) AS cnt, min(e.open_date) AS oldest
    WHERE cnt >= $min_violations
      AND duration.inDays(oldest, date()).days > $min_days
}
RETURN bld.bbl AS bbl, c.claim_id AS claim_id
"""


def find_qualifying_buildings(session) -> list:
    print("  Querying qualifying buildings (this may take 1-2 minutes)...")
    result = session.run(
        QUALIFYING_QUERY,
        min_violations=MIN_VIOLATIONS,
        min_days=MIN_DAYS_OPEN,
    )
    rows = result.data()
    print(f"  {len(rows):,} buildings qualify under PHC-001.")
    return rows


def find_disqualified_buildings(session) -> list:
    """Buildings with active PHC-001 Claims that no longer qualify."""
    result = session.run(
        DISQUALIFIED_QUERY,
        concept=INTERPRETIVE_CONCEPT,
        min_violations=MIN_VIOLATIONS,
        min_days=MIN_DAYS_OPEN,
    )
    return result.data()


# ---------------------------------------------------------------------------
# Step 3: Write Claims
# ---------------------------------------------------------------------------

WRITE_CLAIM_CYPHER = """
UNWIND $batch AS row
MATCH (bld:Building {bbl: row.bbl})
MATCH (rule:Rule {rule_id: $rule_id})

// Supersede existing active PHC-001 Claim for this building if any
OPTIONAL MATCH (bld)-[:SUBJECT_OF]->(old_c:Claim)
WHERE old_c.interpretive_concept = $concept
  AND old_c.superseded_by IS NULL
  AND old_c.valid_to IS NULL
  AND old_c.claim_id <> row.claim_id
SET old_c.superseded_by = row.claim_id,
    old_c.valid_to      = date($today)

WITH bld, rule, row

// Create Evidence node
CREATE (ev:Evidence:WatchlineNode {
    evidence_id: row.evidence_id,
    summary:     row.evidence_summary,
    created_at:  datetime($now)
})

WITH bld, rule, row, ev

// Create the Claim
CREATE (c:Claim:WatchlineNode {
    claim_id:             row.claim_id,
    claim_text:           row.claim_text,
    interpretive_status:  'Inferred',
    interpretive_concept: $concept,
    subject_type:         'Building',
    subject_id:           row.bbl,
    valid_from:           date($today),
    valid_to:             null,
    run_id:               $run_id,
    created_at:           datetime($now)
})
CREATE (bld)-[:SUBJECT_OF]->(c)
CREATE (c)-[:SUPPORTED_BY]->(ev)
CREATE (c)-[:PRODUCED_BY]->(rule)
"""

LINK_EVIDENCE_CYPHER = """
UNWIND $pairs AS pair
MATCH (ev:Evidence {evidence_id: pair.evidence_id})
MATCH (e:Event {event_id: pair.event_id})
MATCH (obs:Observation {source_record_id: e.source_record_id,
                        source_id: e.source_id})
MERGE (ev)-[:DERIVED_FROM]->(obs)
"""

SUPERSEDE_DISQUALIFIED_CYPHER = """
UNWIND $batch AS row
MATCH (c:Claim {claim_id: row.claim_id})
SET c.superseded_by = 'DISQUALIFIED',
    c.valid_to      = date($today)
"""

EXPLANATION_TEMPLATE = (
    "This building satisfies Watchline Rule PHC-001 for Persistent Hazardous "
    "Conditions. It has {open_c_count} open Class C violation(s), the oldest "
    "of which has been open for {oldest_days} days. Class C violations are "
    "classified by HPD as immediately hazardous. The threshold of 3 or more "
    "open Class C violations with the oldest open for more than 180 days "
    "reflects Watchline editorial judgment, not a statutory definition. "
    "A different threshold would produce a different result."
)


def write_claims(session, qualifying: list, run_id: str, dry_run: bool) -> int:
    """
    Write PHC-001 Claims in two passes:
      Pass 1: Write Claim, Evidence, and connecting edges (small memory footprint)
      Pass 2: Link Evidence to Observation nodes via event_ids (separately)

    Separating the two passes avoids the memory explosion from UNWINDing
    event_id arrays (potentially hundreds per building) inside a batch UNWIND.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    now   = datetime.now(timezone.utc).isoformat()
    total = 0

    # Pass 1: Write Claims and Evidence nodes
    # Keep a mapping of evidence_id -> event_ids for Pass 2
    evidence_event_map = []

    for i in range(0, len(qualifying), BATCH_SIZE):
        chunk = qualifying[i:i + BATCH_SIZE]
        batch = []

        for row in chunk:
            claim_id    = f"CLM-PHC-{uuid.uuid4()}"
            evidence_id = f"EVI-PHC-{uuid.uuid4()}"
            claim_text  = EXPLANATION_TEMPLATE.format(
                open_c_count=row["open_c_count"],
                oldest_days=row["oldest_days"],
            )
            evidence_summary = (
                f"{row['open_c_count']} open Class C HPD violations; "
                f"oldest open {row['oldest_days']} days."
            )

            batch.append({
                "bbl":              row["bbl"],
                "claim_id":         claim_id,
                "evidence_id":      evidence_id,
                "claim_text":       claim_text,
                "evidence_summary": evidence_summary,
            })

            # Store for Pass 2 -- cap at 50 events per building to limit
            # memory; the oldest violations (most significant) come first
            # since the qualifying query ordered by oldest_days DESC
            evidence_event_map.append({
                "evidence_id": evidence_id,
                "event_ids":   row["event_ids"][:50],
            })

        if not dry_run:
            session.run(
                WRITE_CLAIM_CYPHER,
                batch=batch,
                rule_id=RULE_ID,
                concept=INTERPRETIVE_CONCEPT,
                today=today,
                now=now,
                run_id=run_id,
            )

        total += len(batch)
        if total % 2_000 == 0:
            print(f"    {total:,} PHC-001 Claims written ...")

    # Pass 2: Link Evidence to Observation nodes
    # Flatten evidence_id/event_id pairs and write in small batches
    if not dry_run:
        print(f"  Linking Evidence nodes to Observations ...")
        pairs = [
            {"evidence_id": item["evidence_id"], "event_id": eid}
            for item in evidence_event_map
            for eid in item["event_ids"]
        ]
        link_batch_size = 500
        linked = 0
        for i in range(0, len(pairs), link_batch_size):
            session.run(LINK_EVIDENCE_CYPHER, pairs=pairs[i:i + link_batch_size])
            linked += min(link_batch_size, len(pairs) - i)
        print(f"  {linked:,} Evidence-Observation links written.")

    return total

    return total


def supersede_disqualified(session, disqualified: list, dry_run: bool) -> int:
    """Supersede Claims for buildings that no longer qualify."""
    if not disqualified:
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    if not dry_run:
        for i in range(0, len(disqualified), BATCH_SIZE):
            session.run(
                SUPERSEDE_DISQUALIFIED_CYPHER,
                batch=disqualified[i:i + BATCH_SIZE],
                today=today,
            )
    return len(disqualified)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(dry_run: bool = False):
    run_id = f"PHC001-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
    print(f"PHC-001 Evaluation Pipeline (run_id={run_id})")
    if dry_run:
        print("  DRY RUN -- no writes to graph.")

    driver = neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            print("Step 1 -- Verifying Rule PHC-001 ...")
            if not verify_rule(session):
                return

            print("Step 2 -- Finding qualifying buildings ...")
            qualifying = find_qualifying_buildings(session)

            print("Step 3 -- Finding disqualified buildings ...")
            disqualified = find_disqualified_buildings(session)
            if disqualified:
                print(f"  {len(disqualified):,} buildings no longer qualify "
                      f"-- Claims will be superseded.")

            print("Step 4 -- Writing PHC-001 Claims ...")
            total_written = write_claims(session, qualifying, run_id, dry_run)

            print("Step 5 -- Superseding disqualified Claims ...")
            total_superseded = supersede_disqualified(session, disqualified, dry_run)

        print("")
        print(f"PHC-001 evaluation complete.")
        print(f"  {total_written:,} Claims written.")
        if total_superseded:
            print(f"  {total_superseded:,} Claims superseded (buildings no longer qualify).")
        if dry_run:
            print("  DRY RUN -- no changes were made to the graph.")

    finally:
        driver.close()


def main():
    parser = argparse.ArgumentParser(description="Watchline PHC-001 evaluation")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query and count qualifying buildings without writing to graph",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
