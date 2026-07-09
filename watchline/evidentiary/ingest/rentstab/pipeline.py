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
import os
from datetime import datetime, timezone
from typing import Iterator, List

import psycopg2
from psycopg2.extras import RealDictCursor


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE
BATCH_SIZE = 500

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
# Connections
# ---------------------------------------------------------------------------

from watchline.shared.bbl import borough_from_bbl
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


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
# Step 2: Enrich Building nodes
# ---------------------------------------------------------------------------

RENTSTAB_SQL = """
SELECT
    trim(r.ucbbl)  AS bbl,
    r.uc2018,
    r.uc2019,
    r.uc2020,
    r.uc2021,
    r.uc2022,
    r.uc2023,
    r.pdfsoa2023,
    -- PLUTO for any buildings not yet in the graph
    p.address      AS pluto_address,
    p.unitsres     AS residential_units,
    p.yearbuilt    AS year_built,
    p.bldgclass    AS building_class,
    p.latitude,
    p.longitude
FROM rentstab_v2 r
LEFT JOIN pluto_latest p ON p.bbl = trim(r.ucbbl)
WHERE r.ucbbl IS NOT NULL
  AND LENGTH(trim(r.ucbbl)) = 10
ORDER BY r.ucbbl
"""


def _batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        print("  Querying rentstab_v2 + pluto_latest ...")
        cur.execute(RENTSTAB_SQL)
        batch = []
        for row in cur:
            bbl = row["bbl"]
            # Derive summary fields -- only flag deregulating when both
            # 2018 and 2023 counts are non-null (avoids spurious negatives
            # from buildings with null baselines)
            uc2018 = row["uc2018"]
            uc2023 = row["uc2023"]
            if uc2018 is not None and uc2023 is not None:
                rs_change = uc2023 - uc2018
                rs_deregulating = rs_change < 0
            else:
                rs_change = None
                rs_deregulating = False
            borough = borough_from_bbl(bbl) or "Unknown"

            batch.append({
                "bbl":               bbl,
                "borough":           borough,
                "address":           row["pluto_address"] or "",
                "latitude":          float(row["latitude"]) if row["latitude"] else None,
                "longitude":         float(row["longitude"]) if row["longitude"] else None,
                "residential_units": row["residential_units"],
                "year_built":        row["year_built"],
                "building_class":    (row["building_class"] or "").strip() or None,
                "rs_units_2018":     row["uc2018"],
                "rs_units_2019":     row["uc2019"],
                "rs_units_2020":     row["uc2020"],
                "rs_units_2021":     row["uc2021"],
                "rs_units_2022":     row["uc2022"],
                "rs_units_2023":     row["uc2023"],
                "rs_units_current":  uc2023,
                "rs_units_change":   rs_change,
                "rs_deregulating":   rs_deregulating,
                "rs_pdfsoa_2023":    row["pdfsoa2023"],
            })
            if len(batch) == BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def enrich_buildings(session, conn) -> tuple:
    """
    MERGE Building nodes and set rent stabilization properties.
    For existing buildings: adds rs_* properties without overwriting
    other existing properties.
    For new buildings: creates minimal node with PLUTO enrichment.
    Returns (total_processed, deregulating_count).
    """
    cypher = """
    UNWIND $batch AS b
    MERGE (bld:Building:WatchlineNode {bbl: b.bbl})
    SET bld.rs_units_2018   = b.rs_units_2018,
        bld.rs_units_2019   = b.rs_units_2019,
        bld.rs_units_2020   = b.rs_units_2020,
        bld.rs_units_2021   = b.rs_units_2021,
        bld.rs_units_2022   = b.rs_units_2022,
        bld.rs_units_2023   = b.rs_units_2023,
        bld.rs_units_current  = b.rs_units_current,
        bld.rs_units_change   = b.rs_units_change,
        bld.rs_deregulating   = b.rs_deregulating,
        bld.rs_pdfsoa_2023    = b.rs_pdfsoa_2023,
        bld.updated_at        = datetime($now),
        // Only set structural properties if not already populated
        bld.borough           = CASE WHEN bld.borough IS NULL
                                     THEN b.borough ELSE bld.borough END,
        bld.address           = CASE WHEN bld.address IS NULL OR bld.address = ''
                                     THEN b.address ELSE bld.address END,
        bld.latitude          = CASE WHEN bld.latitude IS NULL
                                     THEN b.latitude ELSE bld.latitude END,
        bld.longitude         = CASE WHEN bld.longitude IS NULL
                                     THEN b.longitude ELSE bld.longitude END,
        bld.residential_units = CASE WHEN bld.residential_units IS NULL
                                     THEN b.residential_units
                                     ELSE bld.residential_units END,
        bld.year_built        = CASE WHEN bld.year_built IS NULL
                                     THEN b.year_built ELSE bld.year_built END,
        bld.building_class    = CASE WHEN bld.building_class IS NULL
                                     THEN b.building_class ELSE bld.building_class END,
        bld.created_at        = CASE WHEN bld.created_at IS NULL
                                     THEN datetime($now) ELSE bld.created_at END
    """

    now = datetime.now(timezone.utc).isoformat()
    total = 0
    deregulating = 0

    for batch in _batches(conn):
        session.run(cypher, batch=batch, now=now)
        total += len(batch)
        deregulating += sum(1 for b in batch if b["rs_deregulating"])
        if total % 10_000 == 0:
            print(f"    {total:,} buildings enriched ...")

    return total, deregulating


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
