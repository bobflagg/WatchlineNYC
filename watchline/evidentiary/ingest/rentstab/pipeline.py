"""
Watchline Rent Stabilization Ingestion Pipeline
watchline/ingest/rentstab/pipeline.py

Enriches existing Building nodes with annual rent-stabilized unit counts
from the DHCR rent stabilization dataset (rentstab_v2).

Unlike other ingestion pipelines, this creates no Event nodes and no
Observation nodes. Rent stabilization status is a property of a building,
not a discrete event. The annual unit counts (2018-2023) are added directly
to Building nodes as properties.

What this pipeline does:
  - Adds rent stabilization properties to existing Building nodes via MERGE
  - Creates Building nodes for any BBLs not yet in the graph (rare -- most
    rent-stabilized buildings will already exist from violation ingestion)
  - Creates a Source node for DHCR rent stabilization data

Properties added to Building nodes:
  - rs_units_2018 through rs_units_2023: unit counts per year
  - rs_units_current: most recent year count (2023)
  - rs_units_change: net change 2018-2023 (negative = deregulation)
  - rs_deregulating: true if lost more than 0 units 2018-2023
  - rs_pdfsoa_2023: URL to most recent DHCR annual registration PDF

Key design decisions:
  - Unit counts are a Building property, not an Event, because they describe
    the building's regulatory status at a point in time rather than a
    discrete enforcement action.
  - rs_deregulating is a derived boolean computed at ingest time for query
    convenience. It is not a Claim -- it does not go through the Rules layer.
    Investigative queries that need to surface deregulating buildings can
    use this property directly without a graph traversal.
  - The pdfsoa URLs link to DHCR primary source documents and are stored
    to support evidence chain construction in future pipeline phases.
  - Buildings in rentstab_v2 that are not already in the graph are created
    as minimal Building nodes enriched from PLUTO where available.

Usage:
    uv run python -m watchline.evidentiary.ingest.rentstab.pipeline
    uv run python -m watchline.evidentiary.ingest.rentstab.pipeline --step source
    uv run python -m watchline.evidentiary.ingest.rentstab.pipeline --step enrich
"""

import argparse
from datetime import datetime, timezone

from watchline.shared.buildings import load_rentstab
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE

DHCR_RENTSTAB_SOURCE = {
    "source_id":        "SRC-DHCR-RENTSTAB-001",
    "source_name":      "DHCR Rent Stabilization",
    "producing_agency": (
        "NYC Division of Housing and Community Renewal (DHCR)"
    ),
    "legal_authority": (
        "New York Rent Stabilization Law (Administrative Code Section "
        "26-501 et seq.) and Emergency Tenant Protection Act. Owners of "
        "rent-stabilized buildings must register annually with DHCR. The "
        "annual Statement of Registration (SOA) records the number of "
        "stabilized units. DHCR is legally empowered to assert the number "
        "of registered rent-stabilized units per building per year."
    ),
    "data_url": "https://github.com/talos/nyc-stabilization-unit-counts",
    "description": (
        "Annual rent-stabilized unit counts per building derived from DHCR "
        "rent registration filings, compiled by the NYC Stabilization Unit "
        "Counts project. Covers 2018-2023. Legally empowered to assert: the "
        "number of units registered as rent-stabilized by the building owner "
        "in each year's DHCR filing. Does NOT assert current rent status of "
        "individual units or that all stabilized units are correctly reported. "
        "A decline in unit count may indicate legal deregulation, illegal "
        "deregulation, or reporting error."
    ),
}


# ---------------------------------------------------------------------------
# Step 1: Source node
# ---------------------------------------------------------------------------

def create_source_node(session) -> None:
    now   = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    session.run(
        """
        MERGE (s:Source:WatchlineNode {source_id: $source_id})
        SET s.source_name      = $source_name,
            s.producing_agency = $producing_agency,
            s.legal_authority  = $legal_authority,
            s.data_url         = $data_url,
            s.description      = $description,
            s.retrieval_date   = date($today),
            s.updated_at       = datetime($now),
            s.created_at       = CASE WHEN s.created_at IS NULL
                                     THEN datetime($now)
                                     ELSE s.created_at END
        """,
        today=today,
        now=now,
        **DHCR_RENTSTAB_SOURCE,
    )
    print(f"  Source node created/updated: {DHCR_RENTSTAB_SOURCE['source_name']}")


# ---------------------------------------------------------------------------
# Step 2: Enrich Building nodes (delegates to shared substrate)
# ---------------------------------------------------------------------------

def enrich_buildings(session, conn) -> tuple:
    """Enrich Building nodes with RS data via shared substrate. Returns (total, deregulating)."""
    return load_rentstab(session, conn)


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_source(driver):
    print("Step 1 -- Creating/updating DHCR Rent Stabilization Source node ...")
    with driver.session(database=NEO4J_DATABASE) as session:
        create_source_node(session)
    print("  Done.")


def step_enrich(driver):
    print("Step 2 -- Enriching Building nodes with rent stabilization data ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, deregulating = enrich_buildings(session, conn)
        print(f"  {total:,} Building nodes enriched with rent stabilization data.")
        print(f"  {deregulating:,} buildings show net unit loss 2018-2023 "
              f"(rs_deregulating = true).")
    finally:
        conn.close()


def run_all(driver):
    step_source(driver)
    step_enrich(driver)
    print("")
    print("Rent stabilization ingestion complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Watchline rent stabilization ingestion"
    )
    parser.add_argument(
        "--step",
        choices=["source", "enrich"],
        help="Run a single step (omit to run all steps)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "source":
            step_source(driver)
        elif args.step == "enrich":
            step_enrich(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
