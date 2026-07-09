"""
Watchline Discovery KG — DOB Violations Ingestion Pipeline
watchline/discovery/ingest/dob_violations/pipeline.py

Creates a second Event source in the DISCOVERY knowledge graph: DOB (Department
of Buildings) construction/equipment code violations.

What this pipeline creates:
    Event nodes (event_type='Violation', source_name='DOB'), keyed
    event_id = EVT-DOB-<isndobbisviol>.
    (Building)-[:HAS_EVENT]->(Event) edges.

No Actor linkage: same rationale as hpd_violations -- DOB violations carry
no deterministic actor identity in WoW, so no PARTY_TO edges here.

Field mapping (`dob_violations`, ~2.48M rows, isndobbisviol is a stable,
globally-unique key -- verified 1:1 with row count):
    event_date       <- issuedate (null in only 34 rows).
    status            <- derived from violationcategory by keyword
                         ('DISMISSED'/'RESOLVED'/'ACTIVE' -> 'Dismissed'/
                         'Resolved'/'Active'), since DOB has no dedicated
                         status column the way HPD does. Deterministic
                         substring match, not identity resolution -- allowed
                         under the "no fuzzy matching" rule, which is about
                         actor identity, not text categorization.
    violation_class   <- violationtypecode (short code: E, C, LL6291, ...),
                         the DOB analogue of HPD's A/B/C/I class.
    source_id         <- ecbnumber (ECB docket number), present on ~8.5% of
                         rows where the violation escalated to an ECB
                         hearing -- the DOB analogue of HPD's novid.
    source_record_id  <- isndobbisviol, as a string.
    legal_authority   <- constant "NYC Construction Codes (Admin Code Title
                         28)" -- the general basis for DOB violations; the
                         specific code/local law lives in raw_record.
    raw_record        <- compact JSON of violationtype, violationnumber,
                         number, dispositiondate/-comments, devicenumber,
                         description, violationcategory (raw).

BBL: unlike hpd_violations, boro/block/lot reconstruction is NOT used here.
Checked first: of the ~14.3K blank-bbl rows, only ~1.4K have boro/block/lot
present, and those lot values are garbage (e.g. '0BB-1', '006T.', '<0041')
-- not reconstructable BBLs. A further ~3.6K rows carry a 10-char bbl with
an invalid boro digit (leading '0'). All of these simply fail to MATCH any
real Building node and are skipped and counted like any other unmatched
BBL -- no special-casing needed.

Dependency order: run AFTER the buildings pipeline. Rows whose bbl has no
Building node are skipped and counted.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied (portfolio pipeline `--step schema`).
    - Buildings pipeline already run.

Usage:
    uv run python -m watchline.discovery.ingest.dob_violations.pipeline
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Iterator, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE

EVENT_BATCH_SIZE = 2000

LEGAL_AUTHORITY = "NYC Construction Codes (Admin Code Title 28)"


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(isndobbisviol) -> str:
    return f"EVT-DOB-{isndobbisviol}"


def _status(category: Optional[str]) -> Optional[str]:
    if not category:
        return None
    c = category.upper()
    if "DISMISSED" in c:
        return "Dismissed"
    if "RESOLVED" in c:
        return "Resolved"
    if "ACTIVE" in c:
        return "Active"
    return None


# ---------------------------------------------------------------------------
# Step 1: Event(Violation, DOB) nodes + HAS_EVENT edges
# ---------------------------------------------------------------------------

# bbl / violationtypecode are CHAR/text with padding -> trim. No boro/block/lot
# reconstruction (see module docstring) -- rows with an unusable bbl simply
# fail to MATCH a Building and are skipped like any other unmatched row.
VIOLATIONS_SQL = """
SELECT
    isndobbisviol,
    trim(bbl)                   AS bbl,
    trim(violationtypecode)     AS violationtypecode,
    violationtype,
    violationcategory,
    issuedate,
    ecbnumber,
    violationnumber,
    number,
    dispositiondate,
    dispositioncomments,
    devicenumber,
    description
FROM dob_violations
"""


def _raw_record(row: dict) -> str:
    return json.dumps({
        "violationtype":       (row["violationtype"] or "").strip() or None,
        "violationnumber":     row["violationnumber"],
        "number":              row["number"],
        "dispositiondate":     row["dispositiondate"].isoformat() if row["dispositiondate"] else None,
        "dispositioncomments": row["dispositioncomments"],
        "devicenumber":        row["devicenumber"],
        "description":         row["description"],
        "violationcategory":   row["violationcategory"],
    })


def _violation_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="dob_violations", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(VIOLATIONS_SQL)
        batch = []
        for row in cur:
            batch.append({
                "event_id":         _event_id(row["isndobbisviol"]),
                "bbl":              row["bbl"],
                "violation_class":  row["violationtypecode"],
                "status":           _status(row["violationcategory"]),
                "event_date":       row["issuedate"].isoformat() if row["issuedate"] else None,
                "source_id":        row["ecbnumber"],
                "source_record_id": str(row["isndobbisviol"]),
                "raw_record":       _raw_record(row),
            })
            if len(batch) == EVENT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_violations(session, conn):
    """
    MERGE Event(Violation, DOB) nodes and HAS_EVENT edges. Building-first:
    rows whose BBL has no Building node are skipped entirely (no orphan
    Event nodes). Returns (events_written, skipped_missing_building).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (b:Building {bbl: row.bbl})
    MERGE (e:Event:WatchlineNode {event_id: row.event_id})
    SET e.event_type       = 'Violation',
        e.source_name      = 'DOB',
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
    print("Step 1 -- Writing Event(Violation, DOB) nodes + HAS_EVENT edges ...")
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
    print("DOB violations ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG DOB violations ingestion")
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
