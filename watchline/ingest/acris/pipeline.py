"""
watchline/ingest/acris/pipeline.py

Ingests ACRIS deed transfer records into the Neo4j epistemic graph as
DeedTransfer Event nodes on Building nodes.

Scope:
    Document types DEED and CORRD, recorded since 2010-01-01.
    Only buildings already present in the graph receive DeedTransfer events.
    Buildings not yet in the graph (typically 1-4 family homeowner properties
    not covered by HPD violation data) are silently skipped. These will be
    handled by a future DeedWatch ingestion pipeline.

Enables:
    OwnershipChange investigative intent (currently stubbed) -- requires
    DeedTransfer event dates to define before/after periods for violation
    trajectory comparison.

Usage:
    uv run python -m watchline.ingest.acris.pipeline            # run all steps
    uv run python -m watchline.ingest.acris.pipeline --step load
    uv run python -m watchline.ingest.acris.pipeline --step store

Step descriptions:
    load    Read ACRIS deed records from PostgreSQL (real_property_master,
            real_property_legals, real_property_parties). Aggregates
            grantors and grantees per (document, BBL) pair. ~1M rows.
    store   Write DeedTransfer Event nodes and HAS_EVENT relationships
            to Neo4j in batches of 500.

Run order in a full KG rebuild:
    make schema        -- schema + constraints
    make seed-rules    -- Rule nodes
    make indexes       -- performance indexes
    make hpd           -- Building nodes must exist before DeedTransfer events
    ...other ingest...
    make acris         -- this pipeline

The pipeline is idempotent: all Neo4j writes use MERGE. Re-running picks
up any new deed records and updates existing Event node properties.
"""

import argparse

from .config import neo4j_driver, NEO4J_DATABASE
from .load  import fetch_deeds
from .store import run as store_run


def step_load() -> list[dict]:
    print("Step 1 -- Fetching ACRIS deed records from PostgreSQL")
    deeds = fetch_deeds()
    print(f"  {len(deeds):,} deed transfer records ready for ingestion.")
    return deeds


def step_store(deeds: list[dict]) -> None:
    driver = neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            store_run(session, deeds)
    finally:
        driver.close()


def run_all() -> None:
    deeds = step_load()
    step_store(deeds)
    print("ACRIS pipeline complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Watchline ACRIS deed transfer ingestion pipeline"
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
        deeds = step_load()
        print(f"  Load complete. {len(deeds):,} records ready (not written).")
    elif args.step == "store":
        print("Note: --step store requires a prior load; running load first.")
        deeds = step_load()
        step_store(deeds)
        print("Store complete.")


if __name__ == "__main__":
    main()
