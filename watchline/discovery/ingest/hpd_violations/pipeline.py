"""
Watchline Discovery KG — HPD Violations Ingestion Pipeline
watchline/discovery/ingest/hpd_violations/pipeline.py

Creates the first Event layer of the DISCOVERY knowledge graph: HPD housing
maintenance code violations.

What this pipeline creates:
    Event nodes (event_type='Violation', source_name='HPD'), keyed
    event_id = EVT-HPD-<violationid>.
    (Building)-[:HAS_EVENT]->(Event) edges.

No Actor linkage: HPD violations do not carry a deterministic actor
identity in WoW (unlike registrations, which bridge through
landlords_with_connections), so no PARTY_TO edges are written here.

Field mapping (`hpd_violations`, ~11M rows, violationid is a stable,
globally-unique key -- verified 1:1 with row count):
    event_date       <- inspectiondate (never null; the date the violation
                         was observed, not when paperwork was issued).
    status            <- violationstatus ('Open' | 'Close', passed through
                         verbatim -- no relabeling).
    violation_class   <- class ('A' | 'B' | 'C' | 'I').
    source_id         <- novid (Notice of Violation id; groups multiple
                         violationid rows under one notice). Null for the
                         ~7% of rows where no NOV has been issued yet.
    source_record_id  <- violationid, as a string (same value encoded in
                         event_id; kept as its own property so callers can
                         filter without parsing the id).
    legal_authority   <- constant "NYC Housing Maintenance Code (Admin Code
                         Title 27)" -- all HPD violations are issued under
                         it; the per-row citation lives in raw_record only.
    raw_record        <- compact JSON of fields not already promoted to a
                         column (novdescription, novtype, ordernumber,
                         currentstatus/-date, certifieddate, rentimpairing,
                         registrationid, apartment).

BBL: ~10.4K rows (0.1%) have a blank bbl but always carry boroid/block/lot,
so bbl is reconstructed as boro+block(5)+lot(4) per CLAUDE.md convention.

Dependency order: run AFTER the buildings pipeline. Rows whose (real or
reconstructed) BBL has no Building node are skipped and counted.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied (portfolio pipeline `--step schema`).
    - Buildings pipeline already run.

Usage:
    uv run python -m watchline.discovery.ingest.hpd_violations.pipeline
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

NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE

EVENT_BATCH_SIZE = 2000

LEGAL_AUTHORITY = "NYC Housing Maintenance Code (Admin Code Title 27)"


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(violationid) -> str:
    return f"EVT-HPD-{violationid}"


# ---------------------------------------------------------------------------
# Step 1: Event(Violation, HPD) nodes + HAS_EVENT edges
# ---------------------------------------------------------------------------

# bbl is CHAR(n) -> trim. ~10.4K rows have a blank bbl but always carry
# boroid/block/lot, so reconstruct the canonical 10-digit BBL from those in
# that case (CLAUDE.md: "Reconstruct from boroid/block/lot when blank").
VIOLATIONS_SQL = """
SELECT
    violationid,
    COALESCE(
        NULLIF(trim(bbl), ''),
        trim(boroid) || lpad(block::text, 5, '0') || lpad(lot::text, 4, '0')
    )                    AS bbl,
    class,
    violationstatus,
    inspectiondate,
    novid,
    novtype,
    novdescription,
    ordernumber,
    currentstatus,
    currentstatusdate,
    certifieddate,
    rentimpairing,
    registrationid,
    apartment
FROM hpd_violations
WHERE trim(bbl) <> ''
   OR (boroid IS NOT NULL AND block IS NOT NULL AND lot IS NOT NULL)
"""


def _raw_record(row: dict) -> str:
    return json.dumps({
        "novdescription":    row["novdescription"],
        "novtype":           row["novtype"],
        "ordernumber":       row["ordernumber"],
        "currentstatus":     row["currentstatus"],
        "currentstatusdate": row["currentstatusdate"].isoformat() if row["currentstatusdate"] else None,
        "certifieddate":     row["certifieddate"].isoformat() if row["certifieddate"] else None,
        "rentimpairing":     row["rentimpairing"],
        "registrationid":    row["registrationid"],
        "apartment":         row["apartment"],
    })


def _violation_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="hpd_violations", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(VIOLATIONS_SQL)
        batch = []
        for row in cur:
            batch.append({
                "event_id":         _event_id(row["violationid"]),
                "bbl":              row["bbl"],
                "violation_class":  row["class"],
                "status":           row["violationstatus"],
                "event_date":       row["inspectiondate"].isoformat() if row["inspectiondate"] else None,
                "source_id":        str(row["novid"]) if row["novid"] is not None else None,
                "source_record_id": str(row["violationid"]),
                "raw_record":       _raw_record(row),
            })
            if len(batch) == EVENT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_violations(session, conn):
    """
    MERGE Event(Violation, HPD) nodes and HAS_EVENT edges. Building-first:
    rows whose BBL has no Building node are skipped entirely (no orphan
    Event nodes). Returns (events_written, skipped_missing_building).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (b:Building {bbl: row.bbl})
    MERGE (e:Event:WatchlineNode {event_id: row.event_id})
    SET e.event_type       = 'Violation',
        e.source_name      = 'HPD',
        e.source_id        = row.source_id,
        e.source_record_id = row.source_record_id,
        e.event_date        = CASE WHEN row.event_date IS NULL THEN null ELSE date(row.event_date) END,
        e.status            = row.status,
        e.violation_class   = row.violation_class,
        e.legal_authority   = $legal_authority,
        e.raw_record        = row.raw_record,
        e.created_at        = CASE WHEN e.created_at IS NULL THEN datetime($now) ELSE e.created_at END
    MERGE (b)-[:HAS_EVENT]->(e)
    """
    now = _now()
    total = 0
    missing_bbls = set()
    for batch in _violation_batches(conn):
        # Track BBLs in this batch with no Building node in a global set, so a
        # BBL recurring across many batches is only counted once (not once
        # per batch it appears in).
        bbls = {row["bbl"] for row in batch}
        matched = session.run(
            "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN collect(bbl) AS matched",
            bbls=list(bbls),
        ).single()["matched"]
        missing_bbls.update(bbls - set(matched))

        session.run(cypher, batch=batch, now=now, legal_authority=LEGAL_AUTHORITY)
        total += len(batch)
        if total % 100_000 == 0:
            print(f"    {total:,} violation rows processed ...")
    return total, len(missing_bbls)


def step_violations(driver) -> None:
    print("Step 1 -- Writing Event(Violation, HPD) nodes + HAS_EVENT edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_violations(session, conn)
        print(f"  {total:,} violation rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node (rows skipped).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all(driver) -> None:
    step_violations(driver)
    print("")
    print("HPD violations ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG HPD violations ingestion")
    parser.add_argument(
        "--step",
        choices=["violations"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "violations":
            step_violations(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
