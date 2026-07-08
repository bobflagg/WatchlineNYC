"""
Watchline agents pipeline.

Ingests managing agent contacts from HPD registration data (wow_bldgs.allcontacts)
and writes ManagingAgent Actor nodes and ManagedBy Relationship nodes to Neo4j.

This pipeline is the prerequisite for Rule MA-001 (Management Differential)
evaluation. It is independent of the portfolio detection pipeline and can be
run or re-run at any time after Building nodes exist in the graph.

Usage:
    uv run python -m watchline.ingest.agents.pipeline            # run all steps
    uv run python -m watchline.ingest.agents.pipeline --step load
    uv run python -m watchline.ingest.agents.pipeline --step store

Step descriptions:
    load    Read Agent contacts from PostgreSQL (wow_bldgs.allcontacts),
            normalise and deduplicate. Produces in-memory agent list.
    store   Write ManagingAgent Actor nodes, IdentityObservation nodes,
            and ManagedBy Relationship nodes to Neo4j.

Run order in a full KG rebuild:
    make schema        -- schema + constraints
    make seed-rules    -- Rule nodes including MA-001 stub
    make indexes       -- performance indexes
    make hpd           -- Building nodes must exist before ManagedBy rels
    ...other ingest...
    make agents        -- this pipeline (after Building nodes are present)

The pipeline is idempotent: all Neo4j writes use MERGE. Re-running picks
up new Agent contacts and adds ManagedBy relationships for any Building
nodes that have been added since the last run.

Note on interpretive_status:
    ManagedBy Relationship nodes use interpretive_status='Observed' rather
    than 'Inferred'. The managing agent contact is self-reported to HPD
    (an Observed fact), not computationally inferred from patterns. The
    management relationship itself is accepted at face value from the
    registration record.
"""

import argparse

from .config import neo4j_driver, NEO4J_DATABASE
from .load  import fetch_agents
from .store import run as store_run


def step_load() -> list[dict]:
    print("Step 1 -- Fetching managing agent contacts from PostgreSQL")
    agents = fetch_agents()
    print(f"  {len(agents):,} unique managing agents ready for ingestion.")
    return agents


def step_store(agents: list[dict]) -> None:
    driver = neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            store_run(session, agents)
    finally:
        driver.close()


def run_all() -> None:
    agents = step_load()
    step_store(agents)
    print("Agents pipeline complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Watchline managing agent ingestion pipeline"
    )
    parser.add_argument(
        "--step",
        choices=["load", "store"],
        help="Run a single pipeline step (omit to run all steps)",
    )
    args = parser.parse_args()

    if args.step is None:
        run_all()
    elif args.step == "load":
        agents = step_load()
        print(f"  Load complete. {len(agents):,} agents ready (not written).")
    elif args.step == "store":
        # Allow store to run standalone by fetching first
        print("Note: --step store requires a prior load; running load first.")
        agents = step_load()
        step_store(agents)
        print("Store complete.")


if __name__ == "__main__":
    main()
