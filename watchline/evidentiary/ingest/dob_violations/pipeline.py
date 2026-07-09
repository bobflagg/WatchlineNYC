"""
Watchline DOB Violations Ingestion Pipeline
watchline/ingest/dob_violations/pipeline.py

Ingests NYC Department of Buildings violations from the WoW PostgreSQL
database (`wow`, port 5434) into the Watchline Neo4j knowledge graph.

What this pipeline creates:
  Layer 1 (Domain):
    - Building nodes (one per distinct BBL, via MERGE -- safe to run
      after HPD violations pipeline has already created Building nodes)
    - Event nodes of event_type=Violation (one per DOB violation)
    - HAS_EVENT edges linking Buildings to their Violations

  Layer 2 (Evidence):
    - Source node for DOB Violations (created/updated on every run)
    - Observation nodes (one per violation row)
    - ORIGINATES_IN edges from Observations to Source

Scope: all violations (active, resolved, dismissed, work without permit,
       unserved ECB, hazardous). Event.status distinguishes current state.

Key differences from HPD violations pipeline:
  - Primary key is `isndobbisviol` (numeric, verified 1:1 with row count).
    `number` is NOT used as the key — it has 8,601 duplicates (ADR-003).
  - Status derives from violationcategory, not a separate status field
  - DOB violations are issued under the NYC Buildings Code, not the
    Housing Maintenance Code -- different legal authority
  - violationtype and description fields contain long padded strings
    that are trimmed before storage
  - ecbnumber field links to ECB/OATH enforcement actions (future pipeline)
  - BBL 9999999999 records are test/dummy records and are excluded

Usage:
    uv run python -m watchline.evidentiary.ingest.dob_violations.pipeline
    uv run python -m watchline.evidentiary.ingest.dob_violations.pipeline --step source
    uv run python -m watchline.evidentiary.ingest.dob_violations.pipeline --step buildings
    uv run python -m watchline.evidentiary.ingest.dob_violations.pipeline --step violations
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Iterator, List

import psycopg2
from psycopg2.extras import RealDictCursor


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE

BUILDING_BATCH_SIZE  = BATCH_SIZE
VIOLATION_BATCH_SIZE = BATCH_SIZE

DOB_VIOLATIONS_SOURCE = {
    "source_id":        "SRC-DOB-VIOLATIONS-001",
    "source_name":      "DOB Violations",
    "producing_agency": "NYC Department of Buildings",
    "legal_authority": (
        "New York City Administrative Code, NYC Buildings Code. "
        "DOB is empowered to issue violations for conditions that violate "
        "the Buildings Code, including elevator safety, boiler compliance, "
        "work without permits, and structural conditions. "
        "Violations may be resolved, dismissed, or referred to ECB/OATH "
        "for adjudication."
    ),
    "data_url": (
        "https://data.cityofnewyork.us/Housing-Development/"
        "DOB-Violations/3h2n-5cm9"
    ),
    "description": (
        "DOB Buildings Code violations. Legally empowered to assert: that a "
        "DOB inspector identified a condition at a specific address that "
        "violates the NYC Buildings Code, and the type and category of that "
        "violation. Does NOT assert that the condition persists today, that "
        "the owner is responsible, or that any enforcement action has been "
        "taken. ECB number links to OATH/ECB adjudication records where "
        "applicable. Includes all violations: active, resolved, and dismissed. "
        "Event.status distinguishes current state. "
        "Different legal authority from HPD violations (Buildings Code vs "
        "Housing Maintenance Code)."
    ),
}

# ---------------------------------------------------------------------------
# Status vocabulary mapping
# violationcategory -> Event.status (controlled vocab)
# Active categories: anything with ACTIVE or no resolution marker
# Closed categories: Resolved
# Dismissed categories: DISMISSED
# ---------------------------------------------------------------------------
STATUS_MAP = {
    "V-DOB VIOLATION - ACTIVE":                          "Active",
    "V*-DOB VIOLATION - Resolved":                       "Closed",
    "V*-DOB VIOLATION - DISMISSED":                      "Dismissed",
    "VW-VIOLATION WORK WITHOUT PERMIT - ACTIVE":         "Active",
    "VW*-VIOLATION - WORK W/O PERMIT DISMISSED":         "Dismissed",
    "VP-VIOLATION UNSERVED ECB-ACTIVE":                  "Active",
    "VP*-VIOLATION UNSERVED ECB- DISMISSED":             "Dismissed",
    "VPW-VIOLATION UNSERVED ECB-WORK WITHOUT PERMIT-ACTIVE":        "Active",
    "VPW*-VIOLATION UNSERVED ECB-WORK WITHOUT PERMIT-DISMISSED":    "Dismissed",
    "VH-VIOLATION HAZARDOUS - ACTIVE":                   "Active",
    "VH*-VIOLATION HAZARDOUS DISMISSED":                 "Dismissed",
    "VWH-VIOLATION WORK W/OUT PMT HAZARDOUS - ACTIVE":   "Active",
    "VWH*-VIOLATION WORK W/OUT PMT HAZARDOUS DISMISSED": "Dismissed",
    "V%-DOB VIOLATION":                                  "Unknown",
    "V%*-DOB VIOLATION - DISMISSED":                     "Dismissed",
}

HAZARDOUS_CATEGORIES = {
    "VH-VIOLATION HAZARDOUS - ACTIVE",
    "VH*-VIOLATION HAZARDOUS DISMISSED",
    "VWH-VIOLATION WORK W/OUT PMT HAZARDOUS - ACTIVE",
    "VWH*-VIOLATION WORK W/OUT PMT HAZARDOUS DISMISSED",
}

WORK_WITHOUT_PERMIT_CATEGORIES = {
    "VW-VIOLATION WORK WITHOUT PERMIT - ACTIVE",
    "VW*-VIOLATION - WORK W/O PERMIT DISMISSED",
    "VPW-VIOLATION UNSERVED ECB-WORK WITHOUT PERMIT-ACTIVE",
    "VPW*-VIOLATION UNSERVED ECB-WORK WITHOUT PERMIT-DISMISSED",
    "VWH-VIOLATION WORK W/OUT PMT HAZARDOUS - ACTIVE",
    "VWH*-VIOLATION WORK W/OUT PMT HAZARDOUS DISMISSED",
}


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

from watchline.shared.batching import BATCH_SIZE, CURSOR_ITERSIZE
from watchline.shared.bbl import borough_from_bbl
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


# ---------------------------------------------------------------------------
# BBL normalization
# ---------------------------------------------------------------------------

def normalize_bbl(bbl, boro, block, lot) -> str:
    """Return canonical 10-digit BBL, reconstructing from components if needed."""
    bbl = (bbl or "").strip()
    if len(bbl) == 10:
        return bbl
    boro  = str(boro  or "0").strip().zfill(1)
    block = str(block or "0").strip().zfill(5)
    lot   = str(lot   or "0").strip().zfill(4)
    return boro + block + lot


# ---------------------------------------------------------------------------
# Step 1: Source nodes
# ---------------------------------------------------------------------------

def create_source_nodes(session) -> None:
    """Create or update the DOB Violations Source node."""
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
        **DOB_VIOLATIONS_SOURCE,
    )
    print(f"  Source node created/updated: {DOB_VIOLATIONS_SOURCE['source_name']}")


# ---------------------------------------------------------------------------
# Step 2: Building nodes
# ---------------------------------------------------------------------------

BUILDINGS_SQL = """
SELECT
    CASE
        WHEN trim(v.bbl) = '' OR v.bbl IS NULL
        THEN lpad(v.boro::text,1,'0')||lpad(v.block::text,5,'0')||lpad(v.lot::text,4,'0')
        ELSE trim(v.bbl)
    END AS bbl_canonical,
    MAX(v.housenumber)  AS housenumber,
    MAX(v.street)       AS streetname,
    MAX(p.address)      AS pluto_address,
    MAX(p.unitsres)     AS residential_units,
    MAX(p.yearbuilt)    AS year_built,
    MAX(p.bldgclass)    AS building_class,
    MAX(p.latitude)     AS latitude,
    MAX(p.longitude)    AS longitude
FROM dob_violations v
LEFT JOIN pluto_latest p ON p.bbl = CASE
    WHEN trim(v.bbl) = '' OR v.bbl IS NULL
    THEN lpad(v.boro::text,1,'0')||lpad(v.block::text,5,'0')||lpad(v.lot::text,4,'0')
    ELSE trim(v.bbl)
END
WHERE v.bbl IS NOT NULL
  -- Exclude test/dummy records
  AND NOT (trim(v.block) = '99999' AND trim(v.lot) = '99999')
GROUP BY bbl_canonical
"""

def _building_batches(conn) -> Iterator[List[dict]]:
    """Yield batches of building dicts."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        print("  Querying distinct buildings from dob_violations + pluto_latest ...")
        cur.execute(BUILDINGS_SQL)
        batch = []
        for row in cur:
            bbl = row["bbl_canonical"]
            borough = borough_from_bbl(bbl) or "Unknown"
            address = row["pluto_address"] or (
                f"{(row['housenumber'] or '').strip()} "
                f"{(row['streetname'] or '').strip()}"
            ).strip()

            batch.append({
                "bbl":               bbl,
                "address":           address,
                "borough":           borough,
                "latitude":          float(row["latitude"]) if row["latitude"] else None,
                "longitude":         float(row["longitude"]) if row["longitude"] else None,
                "residential_units": row["residential_units"],
                "year_built":        row["year_built"],
                "building_class":    (row["building_class"] or "").strip() or None,
            })
            if len(batch) == BUILDING_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_buildings(session, conn) -> int:
    """
    Write Building nodes. MERGE on bbl so safe to run after HPD pipeline
    has already created Building nodes -- adds new BBLs, updates existing.
    """
    cypher = """
    UNWIND $batch AS b
    MERGE (bld:Building:WatchlineNode {bbl: b.bbl})
    SET bld.borough           = CASE WHEN bld.borough IS NULL
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
        bld.updated_at        = datetime($now),
        bld.created_at        = CASE WHEN bld.created_at IS NULL
                                     THEN datetime($now) ELSE bld.created_at END
    """
    now = datetime.now(timezone.utc).isoformat()
    total = 0
    for batch in _building_batches(conn):
        session.run(cypher, batch=batch, now=now)
        total += len(batch)
        if total % 10_000 == 0:
            print(f"    {total:,} buildings processed ...")
    return total


# ---------------------------------------------------------------------------
# Step 3: Violation Events + Observations
# ---------------------------------------------------------------------------

VIOLATIONS_SQL = """
SELECT
    v.number,
    CASE
        WHEN trim(v.bbl) = '' OR v.bbl IS NULL
        THEN lpad(v.boro::text,1,'0')||lpad(v.block::text,5,'0')||lpad(v.lot::text,4,'0')
        ELSE trim(v.bbl)
    END AS bbl_canonical,
    v.boro,
    v.bin,
    v.issuedate,
    v.violationtypecode,
    v.violationnumber,
    v.housenumber,
    v.street,
    v.dispositiondate,
    v.dispositioncomments,
    v.devicenumber,
    v.description,
    v.ecbnumber,
    v.violationcategory,
    v.violationtype,
    v.isndobbisviol
FROM dob_violations v
WHERE v.bbl IS NOT NULL
  -- Exclude test/dummy records
  AND NOT (trim(v.block) = '99999' AND trim(v.lot) = '99999')
ORDER BY v.isndobbisviol
"""


def _violation_batches(conn) -> Iterator[List[dict]]:
    """Yield batches of DOB violation dicts using a server-side cursor for streaming."""
    with conn.cursor(name="dob_violations_cursor",
                     cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        print("  Querying all DOB violations ...")
        cur.execute(VIOLATIONS_SQL)
        batch = []
        for row in cur:
            def d(col):
                v = row.get(col)
                return v.isoformat() if v else None

            category = (row["violationcategory"] or "").strip()
            status = STATUS_MAP.get(category, "Unknown")
            is_hazardous = category in HAZARDOUS_CATEGORIES
            is_work_without_permit = category in WORK_WITHOUT_PERMIT_CATEGORIES

            # Trim the heavily padded violationtype field
            vtype = (row["violationtype"] or "").strip()
            # Extract just the code and short description before the padding
            vtype_parts = vtype.split("-", 1)
            vtype_code = vtype_parts[0].strip() if vtype_parts else ""
            vtype_desc = vtype_parts[1].strip() if len(vtype_parts) > 1 else vtype

            batch.append({
                "event_id":              f"EVT-DOB-{row['isndobbisviol']}",
                "bbl":                   row["bbl_canonical"],
                "source_record_id":      str(row["isndobbisviol"]),
                "event_type":            "Violation",
                "source_name":           "DOB",
                "event_date":            d("issuedate") or d("dispositiondate"),
                "status":                status,
                "violation_class":       None,  # DOB uses type codes, not A/B/C
                "violation_type_code":   (row["violationtypecode"] or "").strip(),
                "violation_number":      (row["violationnumber"] or "").strip(),
                "violation_category":    category,
                "violation_type":        vtype_desc[:200] if vtype_desc else None,
                "open_date":             d("issuedate"),
                "closed_date":           d("dispositiondate"),
                "description":           (row["description"] or "").strip() or None,
                "disposition_comments":  (row["dispositioncomments"] or "").strip() or None,
                "ecb_number":            (row["ecbnumber"] or "").strip() or None,
                "device_number":         (row["devicenumber"] or "").strip() or None,
                "bin":                   (row["bin"] or "").strip() or None,
                "is_hazardous":          is_hazardous,
                "is_work_without_permit": is_work_without_permit,
                "legal_authority":       "NYC Buildings Code",
                "raw_record":            json.dumps({
                    "number":            row["number"],
                    "violationcategory": row["violationcategory"],
                    "violationtype":     row["violationtype"],
                    "violationnumber":   row["violationnumber"],
                    "ecbnumber":         row["ecbnumber"],
                    "description":       row["description"],
                    "isndobbisviol":     row["isndobbisviol"],
                }),
            })
            if len(batch) == VIOLATION_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_violations(session, conn) -> tuple:
    """
    Write DOB Violation Event and Observation nodes to Neo4j.
    MERGE on event_id so re-runs are safe.
    Skips rows where both issuedate and dispositiondate are null
    (event_date is NOT NULL in schema).
    Returns (total_written, total_skipped).
    """
    event_cypher = """
    UNWIND $batch AS v
    MATCH (bld:Building {bbl: v.bbl})
    MERGE (e:Event:WatchlineNode {event_id: v.event_id})
    SET e.event_type             = v.event_type,
        e.source_id              = $source_id,
        e.source_name            = v.source_name,
        e.source_record_id       = v.source_record_id,
        e.event_date             = date(v.event_date),
        e.status                 = v.status,
        e.violation_class        = v.violation_class,
        e.violation_type_code    = v.violation_type_code,
        e.violation_number       = v.violation_number,
        e.violation_category     = v.violation_category,
        e.violation_type         = v.violation_type,
        e.open_date              = CASE WHEN v.open_date IS NOT NULL
                                        THEN date(v.open_date) ELSE null END,
        e.closed_date            = CASE WHEN v.closed_date IS NOT NULL
                                        THEN date(v.closed_date) ELSE null END,
        e.description            = v.description,
        e.disposition_comments   = v.disposition_comments,
        e.ecb_number             = v.ecb_number,
        e.device_number          = v.device_number,
        e.bin                    = v.bin,
        e.is_hazardous           = v.is_hazardous,
        e.is_work_without_permit = v.is_work_without_permit,
        e.legal_authority        = v.legal_authority,
        e.raw_record             = v.raw_record,
        e.created_at             = CASE WHEN e.created_at IS NULL
                                        THEN datetime($now) ELSE e.created_at END
    MERGE (bld)-[:HAS_EVENT]->(e)
    WITH e, v
    MATCH (s:Source {source_id: $source_id})
    MERGE (obs:Observation:WatchlineNode {
        observation_id: 'OBS-DOB-' + v.source_record_id
    })
    SET obs.source_id        = $source_id,
        obs.raw_content      = v.raw_record,
        obs.source_record_id = v.source_record_id,
        obs.ingested_at      = CASE WHEN obs.ingested_at IS NULL
                                    THEN datetime($now) ELSE obs.ingested_at END
    MERGE (obs)-[:ORIGINATES_IN]->(s)
    MERGE (e)-[:ORIGINATES_IN]->(s)
    """

    now = datetime.now(timezone.utc).isoformat()
    total = 0
    total_skipped = 0

    for batch in _violation_batches(conn):
        # Filter out rows with no usable date -- event_date is NOT NULL in schema
        valid = [v for v in batch if v["event_date"] is not None]
        skipped_in_batch = len(batch) - len(valid)
        total_skipped += skipped_in_batch

        if not valid:
            continue

        session.run(
            event_cypher,
            batch=valid,
            source_id=DOB_VIOLATIONS_SOURCE["source_id"],
            now=now,
        )
        total += len(valid)
        if total % 10_000 == 0:
            print(f"    {total:,} violations written ...")

    return total, total_skipped


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_source(driver):
    print("Step 1 -- Creating/updating DOB Violations Source node ...")
    with driver.session(database=NEO4J_DATABASE) as session:
        create_source_nodes(session)
    print("  Done.")


def step_buildings(driver):
    print("Step 2 -- Writing Building nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total = load_buildings(session, conn)
        print(f"  {total:,} Building nodes processed (new + existing updated).")
    finally:
        conn.close()


def step_violations(driver):
    print("Step 3 -- Writing DOB Violation Event nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_violations(session, conn)
        print(f"  {total:,} DOB Violation Events written.")
        if skipped:
            print(f"  {skipped:,} violations skipped (no issuedate or dispositiondate).")
    finally:
        conn.close()


def run_all(driver):
    step_source(driver)
    step_buildings(driver)
    step_violations(driver)
    print("")
    print("DOB violations ingestion complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Watchline DOB violations ingestion")
    parser.add_argument(
        "--step",
        choices=["source", "buildings", "violations"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "source":
            step_source(driver)
        elif args.step == "buildings":
            step_buildings(driver)
        elif args.step == "violations":
            step_violations(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
