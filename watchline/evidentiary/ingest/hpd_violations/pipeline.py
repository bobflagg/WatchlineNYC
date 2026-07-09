"""
Watchline HPD Violations Ingestion Pipeline
watchline/ingest/hpd_violations/pipeline.py

Ingests HPD violations from the WoW PostgreSQL database (`wow`, port 5434)
into the Watchline Neo4j knowledge graph.

What this pipeline creates:
  Layer 1 (Domain):
    - Building nodes (one per distinct BBL, enriched from MapPLUTO)
    - Event nodes of event_type=Violation (one per HPD violation)
    - HAS_EVENT edges linking Buildings to their Violations

  Layer 2 (Evidence):
    - Source node for HPD Violations (created/updated on every run)
    - Observation nodes (one per violation row)
    - ORIGINATES_IN edges from Observations to Source

  After this pipeline completes, run:
    uv run python -m watchline.evidentiary.ingest.portfolio.pipeline --step reconcile

Scope: all violations (open and closed). Class I (informational notices)
       are included and flagged via violation_class = 'I'.
       Event.status distinguishes Open from Closed violations.

Usage:
    uv run python -m watchline.evidentiary.ingest.hpd_violations.pipeline
    uv run python -m watchline.evidentiary.ingest.hpd_violations.pipeline --step source
    uv run python -m watchline.evidentiary.ingest.hpd_violations.pipeline --step buildings
    uv run python -m watchline.evidentiary.ingest.hpd_violations.pipeline --step violations
"""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List

import psycopg2
from psycopg2.extras import RealDictCursor

import os

from watchline.shared.batching import BATCH_SIZE, CURSOR_ITERSIZE
from watchline.shared.bbl import borough_from_bbl
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE

VIOLATION_BATCH_SIZE  = BATCH_SIZE
OBSERVATION_BATCH_SIZE = BATCH_SIZE

HPD_VIOLATIONS_SOURCE = {
    "source_id":        "SRC-HPD-VIOLATIONS-001",
    "source_name":      "HPD Online Violations",
    "producing_agency": "NYC Department of Housing Preservation and Development",
    "legal_authority": (
        "New York City Administrative Code, Housing Maintenance Code. "
        "HPD is empowered to issue notices of violation (NOVs) for conditions "
        "that violate the Housing Maintenance Code. Class A: non-hazardous. "
        "Class B: hazardous. Class C: immediately hazardous. "
        "Class I: informational notices (not violations in the legal sense)."
    ),
    "data_url": (
        "https://data.cityofnewyork.us/Housing-Development/"
        "Housing-Maintenance-Code-Violations/wvxf-dwi5"
    ),
    "description": (
        "HPD Housing Maintenance Code violations. Legally empowered to assert: "
        "that an HPD inspector observed a condition at a specific address on a "
        "specific date that violates the Housing Maintenance Code, and the class "
        "of that violation (A/B/C/I). Does NOT assert that the condition persists "
        "today, that the owner is responsible, or that any enforcement action "
        "has been or will be taken. Includes all violations: open and closed. "
        "Event.status distinguishes current state. Class I records are "
        "informational notices, not violations in the legal sense."
    ),
}

PLUTO_SOURCE = {
    "source_id":        "SRC-PLUTO-001",
    "source_name":      "MapPLUTO",
    "producing_agency": "NYC Department of City Planning",
    "legal_authority": (
        "NYC Department of City Planning authoritative tax lot dataset. "
        "Derived from NYC Department of Finance RPAD data and other city sources."
    ),
    "data_url": "https://www.nyc.gov/site/planning/data-maps/open-data/dwn-pluto-mappluto.page",
    "description": (
        "MapPLUTO tax lot data. Used to enrich Building nodes with address, "
        "coordinates, residential unit count, year built, and building class. "
        "Legally empowered to assert: the physical and administrative "
        "characteristics of a tax lot as recorded by NYC. Does NOT assert "
        "current ownership."
    ),
}



# ---------------------------------------------------------------------------
# BBL normalization
# ---------------------------------------------------------------------------

def normalize_bbl(row: dict) -> str:
    """
    Return a canonical 10-digit BBL string.
    Falls back to constructing from boroid/block/lot when bbl field is blank.
    """
    bbl = (row.get("bbl") or "").strip()
    if len(bbl) == 10:
        return bbl
    # Reconstruct from components
    boroid = str(row.get("boroid") or "").strip().lstrip("0") or "0"
    block  = str(row.get("block")  or 0)
    lot    = str(row.get("lot")    or 0)
    return boroid.zfill(1) + block.zfill(5) + lot.zfill(4)


# ---------------------------------------------------------------------------
# Step 1: Source nodes
# ---------------------------------------------------------------------------

def create_source_nodes(session) -> None:
    """Create or update Source nodes for HPD Violations and PLUTO."""
    now  = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()

    for src in (HPD_VIOLATIONS_SOURCE, PLUTO_SOURCE):
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
            **src,
        )
        print(f"  Source node created/updated: {src['source_name']}")


# ---------------------------------------------------------------------------
# Step 2: Building nodes
# ---------------------------------------------------------------------------

# Schema-only stub (ADR-001): PLUTO enrichment is done by the shared buildings
# substrate (evidentiary-buildings). This step only ensures a landing node
# exists for every BBL seen in hpd_violations that wasn't covered by PLUTO.
_BACKFILL_SQL = """
SELECT DISTINCT
    CASE
        WHEN trim(bbl) = '' OR bbl IS NULL
        THEN lpad(boroid::text,1,'0')||lpad(block::text,5,'0')||lpad(lot::text,4,'0')
        ELSE trim(bbl)
    END AS bbl
FROM hpd_violations
WHERE bbl IS NOT NULL
"""

_MERGE_BUILDING_STUB = """
UNWIND $batch AS b
MERGE (bld:Building:WatchlineNode {bbl: b.bbl})
SET bld.borough    = CASE WHEN bld.borough IS NULL THEN b.borough ELSE bld.borough END,
    bld.address    = CASE WHEN bld.address IS NULL THEN "Unknown" ELSE bld.address END,
    bld.updated_at = datetime($now),
    bld.created_at = CASE WHEN bld.created_at IS NULL THEN datetime($now) ELSE bld.created_at END
"""


def _bbl_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="hpd_viol_bbls", cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        cur.execute(_BACKFILL_SQL)
        batch: List[dict] = []
        for row in cur:
            bbl = row["bbl"]
            batch.append({"bbl": bbl, "borough": borough_from_bbl(bbl) or "Unknown"})
            if len(batch) == BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_buildings(session, conn) -> int:
    """Ensure a Building node exists for every HPD violation BBL.

    PLUTO enrichment is handled by the shared substrate. This stub only
    creates minimal nodes for any BBLs not covered by load_pluto() /
    load_backfill(). Returns total BBLs processed.
    """
    now = datetime.now(timezone.utc).isoformat()
    total = 0
    for batch in _bbl_batches(conn):
        session.run(_MERGE_BUILDING_STUB, batch=batch, now=now)
        total += len(batch)
    return total


# ---------------------------------------------------------------------------
# Step 3: Violation Events + Observations
# ---------------------------------------------------------------------------

VIOLATIONS_SQL = """
SELECT
    violationid,
    CASE
        WHEN trim(bbl) = '' OR bbl IS NULL
        THEN lpad(boroid::text,1,'0')||lpad(block::text,5,'0')||lpad(lot::text,4,'0')
        ELSE trim(bbl)
    END AS bbl_canonical,
    class,
    inspectiondate,
    novissueddate,
    currentstatus,
    currentstatusdate,
    violationstatus,
    novdescription,
    ordernumber,
    originalcorrectbydate,
    newcorrectbydate,
    certifieddate,
    rentimpairing,
    apartment,
    story,
    novtype
FROM hpd_violations
WHERE bbl IS NOT NULL
ORDER BY violationid
"""

STATUS_MAP = {
    "Open":  "Open",
    "Close": "Closed",
}

CLASS_MAP = {
    "A": "A",
    "B": "B",
    "C": "C",
    "I": "I",
}


def _violation_batches(conn) -> Iterator[List[dict]]:
    """Yield batches of violation dicts using a server-side cursor for streaming."""
    with conn.cursor(name="hpd_violations_cursor",
                     cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        print("  Querying all violations (open and closed) ...")
        cur.execute(VIOLATIONS_SQL)
        batch = []
        for row in cur:
            def d(col):
                v = row.get(col)
                return v.isoformat() if v else None

            batch.append({
                "event_id":              f"EVT-HPD-{row['violationid']}",
                "bbl":                   row["bbl_canonical"],
                "source_record_id":      str(row["violationid"]),
                "event_type":            "Violation",
                "source_name":           "HPD",
                "event_date":            d("novissueddate") or d("inspectiondate"),
                "status":                STATUS_MAP.get(row["violationstatus"], "Unknown"),
                "violation_class":       CLASS_MAP.get((row["class"] or "").strip(), None),
                "open_date":             d("novissueddate"),
                "inspection_date":       d("inspectiondate"),
                "current_status":        row["currentstatus"],
                "current_status_date":   d("currentstatusdate"),
                "original_correct_by":   d("originalcorrectbydate"),
                "new_correct_by":        d("newcorrectbydate"),
                "certified_date":        d("certifieddate"),
                "description":           row["novdescription"],
                "order_number":          row["ordernumber"],
                "rent_impairing":        row["rentimpairing"],
                "apartment":             row["apartment"],
                "story":                 row["story"],
                "nov_type":              row["novtype"],
                "legal_authority":       "NYC Housing Maintenance Code",
                "raw_record":            json.dumps({
                    "violationid":       row["violationid"],
                    "class":             row["class"],
                    "currentstatus":     row["currentstatus"],
                    "violationstatus":   row["violationstatus"],
                    "novdescription":    row["novdescription"],
                }),
            })
            if len(batch) == VIOLATION_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_violations(session, conn) -> int:
    """
    Write Event nodes and Observation nodes to Neo4j.
    Links each Event to its Building via HAS_EVENT.
    Links each Observation to the HPD Violations Source via ORIGINATES_IN.

    Uses MERGE on event_id so re-runs are safe.
    Skips events whose Building node does not exist (BBL not in graph).
    Returns total violations written.
    """
    event_cypher = """
    UNWIND $batch AS v
    MATCH (bld:Building {bbl: v.bbl})
    MERGE (e:Event:WatchlineNode {event_id: v.event_id})
    SET e.event_type            = v.event_type,
        e.source_id             = $source_id,
        e.source_name           = v.source_name,
        e.source_record_id      = v.source_record_id,
        e.event_date            = CASE WHEN v.event_date IS NOT NULL
                                       THEN date(v.event_date) ELSE null END,
        e.status                = v.status,
        e.violation_class       = v.violation_class,
        e.open_date             = CASE WHEN v.open_date IS NOT NULL
                                       THEN date(v.open_date) ELSE null END,
        e.inspection_date       = CASE WHEN v.inspection_date IS NOT NULL
                                       THEN date(v.inspection_date) ELSE null END,
        e.current_status        = v.current_status,
        e.current_status_date   = CASE WHEN v.current_status_date IS NOT NULL
                                       THEN date(v.current_status_date) ELSE null END,
        e.original_correct_by   = CASE WHEN v.original_correct_by IS NOT NULL
                                       THEN date(v.original_correct_by) ELSE null END,
        e.new_correct_by        = CASE WHEN v.new_correct_by IS NOT NULL
                                       THEN date(v.new_correct_by) ELSE null END,
        e.certified_date        = CASE WHEN v.certified_date IS NOT NULL
                                       THEN date(v.certified_date) ELSE null END,
        e.description           = v.description,
        e.order_number          = v.order_number,
        e.rent_impairing        = v.rent_impairing,
        e.apartment             = v.apartment,
        e.story                 = v.story,
        e.nov_type              = v.nov_type,
        e.legal_authority       = v.legal_authority,
        e.raw_record            = v.raw_record,
        e.created_at            = CASE WHEN e.created_at IS NULL
                                       THEN datetime($now) ELSE e.created_at END
    MERGE (bld)-[:HAS_EVENT]->(e)
    WITH e, v
    MATCH (s:Source {source_id: $source_id})
    MERGE (obs:Observation:WatchlineNode {
        observation_id: 'OBS-HPD-' + v.source_record_id
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
    skipped = 0

    for batch in _violation_batches(conn):
        # Count how many buildings exist for this batch before writing
        result = session.run(
            """
            UNWIND $bbls AS bbl
            MATCH (b:Building {bbl: bbl})
            RETURN count(b) AS found
            """,
            bbls=list({v["bbl"] for v in batch}),
        ).single()
        found = result["found"] if result else 0
        missing = len({v["bbl"] for v in batch}) - found
        skipped += missing

        session.run(
            event_cypher,
            batch=batch,
            source_id=HPD_VIOLATIONS_SOURCE["source_id"],
            now=now,
        )
        total += len(batch)
        if total % 10_000 == 0:
            print(f"    {total:,} violations written ...")

    return total, skipped


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_source(driver):
    print("Step 1 -- Creating/updating Source nodes ...")
    with driver.session(database=NEO4J_DATABASE) as session:
        create_source_nodes(session)
    print("  Done.")


def step_buildings(driver):
    print("Step 2 -- Writing Building nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total = load_buildings(session, conn)
        print(f"  {total:,} Building nodes written.")
    finally:
        conn.close()


def step_violations(driver):
    print("Step 3 -- Writing Violation Event nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_violations(session, conn)
        print(f"  {total:,} Violation Events written.")
        if skipped:
            print(f"  {skipped:,} BBLs in violations had no Building node (unexpected).")
    finally:
        conn.close()


def run_all(driver):
    step_source(driver)
    step_buildings(driver)
    step_violations(driver)
    print("")
    print("HPD violations ingestion complete.")
    print("Now run:")
    print("  uv run python -m watchline.evidentiary.ingest.portfolio.pipeline --step reconcile")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Watchline HPD violations ingestion")
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
