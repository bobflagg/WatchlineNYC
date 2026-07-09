"""
Watchline Evidentiary — Marshal Evictions Ingestion Pipeline
watchline/evidentiary/ingest/marshal_evictions/pipeline.py

Ingests NYC Marshal eviction execution records into the evidentiary graph.
Marshal evictions are domain facts (P-1: conform the substrate), not
epistemic overlays, so this pipeline creates only Event nodes and a Source
node. No Observation or Claim nodes are created here.

What this pipeline creates:
    Source node: SRC-MARSHAL-001 (NYC Office of Court Administration via NYC Open Data)
    Event nodes (event_type='Eviction', source_name='Marshal'), keyed
    event_id = EVT-MARSHAL-<courtindexnumber>-<docketnumber>.
    (Building)-[:HAS_EVENT]->(Event) edges.

Evidentiary overlay (Observations, Claims about eviction patterns) is
deferred until the eviction data model is agreed. See ADR-013.

Dependency order: run AFTER the buildings pipeline (evidentiary-buildings).

Prerequisites:
    - Reads WoW (`wow`, port 5434).
    - Buildings pipeline already run (Building nodes must exist for MATCH).

Usage:
    uv run python -m watchline.evidentiary.ingest.marshal_evictions.pipeline
    uv run python -m watchline.evidentiary.ingest.marshal_evictions.pipeline --step source
    uv run python -m watchline.evidentiary.ingest.marshal_evictions.pipeline --step evictions
"""

import argparse
from datetime import datetime, timezone

from watchline.shared.marshal_evictions import load_marshal_evictions
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE

MARSHAL_SOURCE = {
    "source_id":        "SRC-MARSHAL-001",
    "source_name":      "NYC Marshal Evictions",
    "producing_agency": "NYC Office of Court Administration / NYC Marshals",
    "legal_authority":  (
        "NY RPAPL Art. 7 (Licensure of City Marshals). City Marshals are "
        "quasi-public officers licensed by the NYC Department of Investigation "
        "to execute warrants of eviction issued by Housing Court. Each row "
        "represents a completed warrant execution. The executing marshal and "
        "court index number are legally authoritative identifiers."
    ),
    "data_url":    "https://data.cityofnewyork.us/City-Government/Evictions/6z8x-wfk4",
    "description": (
        "NYC Marshal eviction execution records from NYC Open Data "
        "(marshal_evictions_all in WoW). Covers completed eviction warrant "
        "executions. Does NOT include eviction filings, pending cases, or "
        "cases resolved without physical execution. ~112K rows as of the "
        "current WoW snapshot."
    ),
}


# ---------------------------------------------------------------------------
# Step 1: Source node
# ---------------------------------------------------------------------------

_SOURCE_CYPHER = """
MERGE (s:Source:WatchlineNode {source_id: $source_id})
SET s.source_name      = $source_name,
    s.producing_agency = $producing_agency,
    s.legal_authority  = $legal_authority,
    s.data_url         = $data_url,
    s.description      = $description,
    s.retrieval_date   = date($today),
    s.updated_at       = datetime($now),
    s.created_at       = CASE WHEN s.created_at IS NULL
                              THEN datetime($now) ELSE s.created_at END
"""


def create_source_node(session) -> None:
    now   = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    session.run(_SOURCE_CYPHER, today=today, now=now, **MARSHAL_SOURCE)
    print(f"  Source node created/updated: {MARSHAL_SOURCE['source_name']}")


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_source(driver) -> None:
    print("Step 1 -- Creating/updating Marshal Evictions Source node ...")
    with driver.session(database=NEO4J_DATABASE) as session:
        create_source_node(session)
    print("  Done.")


def step_evictions(driver) -> None:
    print("Step 2 -- Writing Event(Eviction, Marshal) nodes + HAS_EVENT edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_marshal_evictions(session, conn)
        print(f"  {total:,} eviction rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node (rows skipped).")
    finally:
        conn.close()


def run_all(driver) -> None:
    step_source(driver)
    step_evictions(driver)
    print("")
    print("Marshal evictions ingestion complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Watchline evidentiary marshal evictions ingestion"
    )
    parser.add_argument(
        "--step",
        choices=["source", "evictions"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "source":
            step_source(driver)
        elif args.step == "evictions":
            step_evictions(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
