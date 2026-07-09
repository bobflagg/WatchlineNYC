"""
Watchline Discovery KG — HPD Litigations Ingestion Pipeline
watchline/discovery/ingest/hpd_litigations/pipeline.py

Creates a fourth Event source in the DISCOVERY knowledge graph: HPD housing
court litigations (tenant actions, heat/hot-water cases, harassment
findings, access warrants, etc.).

What this pipeline creates:
    Event nodes (event_type='CourtFiling', source_name='HPD'), keyed
    event_id = EVT-HPD-LIT-<litigationid>.
    (Building)-[:HAS_EVENT]->(Event) edges.

event_id uses a 3-token EVT-HPD-LIT-<id> form, NOT the usual EVT-HPD-<id>
used by hpd_violations. This is deliberate, not stylistic: litigationid and
violationid are independently-assigned integer sequences in WoW and DO
overlap in practice -- 35,474 litigationid values also exist as a
violationid (checked directly). Reusing EVT-HPD-<id> here would silently
MERGE unrelated Violation and CourtFiling records onto the same Event node.

PARTY_TO is deliberately NOT written in v1, despite CLAUDE.md's general
mapping table listing it for this source. `respondent` is a single free-text
column holding a comma-separated, unstructured list of names (e.g.
"DAVID BILDIRICI,EAST 14TH DELAWARE REALTY, LLC,YUSUF Y. BILDIRICI" --
note a legal entity name can itself contain a comma, so naive splitting is
unsafe too). There is no bridge table analogous to wow_landlords'
(name, bizaddr) join to landlords_with_connections, so resolving these to
Actor nodes would require fuzzy name matching, which is forbidden in this
layer (see CLAUDE.md "No fuzzy identity matching"). The raw respondent
string is preserved in raw_record for traceability; promoting it to
PARTY_TO is a deferred refinement requiring a deterministic resolution
step, same category of deferral as REGISTERED_FOR.role.

Field mapping (`hpd_litigations`, ~239K rows; litigationid is a stable,
globally-unique key -- verified 1:1 with row count, 0 nulls):
    event_date       <- caseopendate (null in only 298 rows).
    status            <- casestatus, passed through verbatim (e.g. CLOSED,
                         PENDING, "GRANTED - <date>", "WithDrawn/Abandoned-").
    violation_class   <- casetype (Tenant Action, Heat and Hot Water, ...) --
                         reuses the shared classification property; not
                         literally a "violation" but the same generic slot
                         HPD/DOB/ECB use for their category/severity code.
    source_id         <- left null; no secondary cross-reference id exists
                         in this table (unlike novid/ecbnumber elsewhere).
    source_record_id  <- litigationid, as a string.
    legal_authority   <- constant "NYC Housing Court (HMC/MDL housing
                         litigation)".
    raw_record        <- compact JSON: respondent (raw, unparsed),
                         openjudgement, findingofharassment, findingdate,
                         penalty.

BBL: unlike dob_violations/ecb_violations, reconstruction from boro/block/lot
IS used here and IS safe -- checked directly: all 319 blank-bbl rows and all
321 non-blank-but-invalid-format rows (bbl='0', space-padded) have a valid
boro (1-5) and numeric block/lot, with max block/lot well within the 5/4
digit canonical widths. No unreconstructable rows exist in this table.

Dependency order: run AFTER the buildings pipeline.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied (portfolio pipeline `--step schema`).
    - Buildings pipeline already run.

Usage:
    uv run python -m watchline.discovery.ingest.hpd_litigations.pipeline
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

LEGAL_AUTHORITY = "NYC Housing Court (HMC/MDL housing litigation)"


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(litigationid) -> str:
    return f"EVT-HPD-LIT-{litigationid}"


# ---------------------------------------------------------------------------
# Step 1: Event(CourtFiling, HPD) nodes + HAS_EVENT edges
# ---------------------------------------------------------------------------

# bbl is CHAR(n) -> trim. When bbl isn't a well-formed 10-digit 1-5-boro BBL
# (blank, or the '0' sentinel padded to width), reconstruct from boro/block/
# lot -- verified safe for every row in this table (see module docstring).
LITIGATIONS_SQL = """
SELECT
    litigationid,
    CASE WHEN trim(bbl) ~ '^[1-5][0-9]{9}$' THEN trim(bbl)
         ELSE boro::text || lpad(block::text, 5, '0') || lpad(lot::text, 4, '0')
    END                      AS bbl,
    casetype,
    casestatus,
    caseopendate,
    respondent,
    openjudgement,
    findingofharassment,
    findingdate,
    penalty
FROM hpd_litigations
"""


def _raw_record(row: dict) -> str:
    return json.dumps({
        "respondent":          row["respondent"],
        "openjudgement":       row["openjudgement"],
        "findingofharassment": row["findingofharassment"],
        "findingdate":         row["findingdate"].isoformat() if row["findingdate"] else None,
        "penalty":             row["penalty"],
    })


def _litigation_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="hpd_litigations", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(LITIGATIONS_SQL)
        batch = []
        for row in cur:
            batch.append({
                "event_id":         _event_id(row["litigationid"]),
                "bbl":              row["bbl"],
                "violation_class":  row["casetype"],
                "status":           row["casestatus"],
                "event_date":       row["caseopendate"].isoformat() if row["caseopendate"] else None,
                "source_record_id": str(row["litigationid"]),
                "raw_record":       _raw_record(row),
            })
            if len(batch) == EVENT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_litigations(session, conn):
    """
    MERGE Event(CourtFiling, HPD) nodes and HAS_EVENT edges. Building-first:
    rows whose BBL has no Building node are skipped entirely (no orphan
    Event nodes). Returns (events_written, skipped_missing_building).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (b:Building {bbl: row.bbl})
    MERGE (e:Event:WatchlineNode {event_id: row.event_id})
    SET e.event_type       = 'CourtFiling',
        e.source_name      = 'HPD',
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
    for batch in _litigation_batches(conn):
        bbls = {row["bbl"] for row in batch}
        matched = session.run(
            "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN collect(bbl) AS matched",
            bbls=list(bbls),
        ).single()["matched"]
        missing_bbls.update(bbls - set(matched))

        session.run(cypher, batch=batch, now=now, legal_authority=LEGAL_AUTHORITY)
        total += len(batch)
        if total % 50_000 == 0:
            print(f"    {total:,} litigation rows processed ...")
    return total, len(missing_bbls)


def step_litigations(driver) -> None:
    print("Step 1 -- Writing Event(CourtFiling, HPD) nodes + HAS_EVENT edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_litigations(session, conn)
        print(f"  {total:,} litigation rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node (rows skipped).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all(driver) -> None:
    step_litigations(driver)
    print("")
    print("HPD litigations ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG HPD litigations ingestion")
    parser.add_argument(
        "--step",
        choices=["litigations"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "litigations":
            step_litigations(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
