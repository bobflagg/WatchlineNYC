"""
Watchline Discovery KG — HPD Complaints Ingestion Pipeline
watchline/discovery/ingest/hpd_complaints/pipeline.py

Creates a new Event source in the DISCOVERY knowledge graph: HPD tenant-
initiated complaints, as distinct from inspector-issued violations
(hpd_violations). A complaint is what a tenant reported; a violation is what
an inspector confirmed. The gap between the two -- many complaints, few
resulting violations -- is itself an accountability signal this graph didn't
previously carry.

What this pipeline creates:
    Event nodes (event_type='Complaint', source_name='HPD'), keyed
    event_id = EVT-HPD-COMPLAINT-<problemid>.
    (Building)-[:HAS_EVENT]->(Event) edges.

No Actor linkage: like hpd_violations, this table carries no name/contact
column at all (no landlord, no complainant identity beyond an anonymous
flag), so no PARTY_TO edges are written here.

Event granularity -- problemid, not complaintid (verified directly against
hpd_complaints_and_problems, 16,164,450 rows):
    problemid    is 100% unique (16,164,450 distinct) -- one row per problem,
                 the same role violationid plays for hpd_violations.
    complaintid  is NOT unique (8,825,737 distinct) -- one complaint can
                 report multiple problems (e.g. a single tenant call citing
                 both HEATING and PLUMBING). Using complaintid as the Event
                 key would collapse those into one Event and lose the
                 per-problem category/status/date detail, so the Event is
                 keyed on problemid and complaintid is carried as source_id
                 (the grouping key) -- the same pattern hpd_violations uses
                 for novid grouping multiple violationid rows under one NOV.

Field mapping:
    event_date       <- receiveddate (0 nulls, verified -- unlike
                         hpd_violations' inspectiondate, no fallback needed).
    status            <- problemstatus ('OPEN' | 'CLOSE', 0 nulls, passed
                         through verbatim). NOTE: this table cases its
                         status values as 'OPEN'/'CLOSE' (all-caps), while
                         hpd_violations passes through 'Open'/'Close' (mixed
                         case) from violationstatus. Both are stored
                         verbatim, per the "no relabeling" convention
                         established there -- so Event.status is NOT
                         uniformly cased across source_name values. A
                         consumer matching on status should compare
                         case-insensitively or filter by source_name first.
                         complaintstatus (the parent complaint's own status,
                         which can differ from problemstatus if a complaint
                         has multiple problems closed at different times) is
                         kept in raw_record rather than promoted to `status`,
                         since problemid is the atomic entity here.
    violation_class   <- type ('EMERGENCY' | 'NON EMERGENCY' |
                         'IMMEDIATE EMERGENCY' | 'HAZARDOUS' | 'REFERRAL', 0
                         nulls) -- reuses the shared classification slot for
                         complaint urgency, the closest analog to violation
                         class A/B/C.
    source_id         <- complaintid, as a string (groups multiple problemid
                         rows under one complaint; see "Event granularity").
    source_record_id  <- problemid, as a string.
    legal_authority   <- constant "NYC Housing Maintenance Code (Admin Code
                         Title 27) -- tenant complaint intake". Deliberately
                         distinct wording from hpd_violations' citation: a
                         complaint is a tenant report, not itself a
                         confirmed code violation -- HPD may or may not
                         issue a corresponding Violation event separately.
    raw_record        <- compact JSON: complaintstatus, complaintstatusdate,
                         problemstatusdate, statusdescription, majorcategory,
                         minorcategory, problemcode, unittype, spacetype,
                         apartment, problemduplicateflag,
                         complaintanonymousflag, uniquekey.

BBL: `borough` in this table is a full name ('MANHATTAN', 'BRONX',
'BROOKLYN', 'QUEENS', 'STATEN ISLAND' -- verified these are the only 5
values present), NOT a numeric boroid the way hpd_violations.boroid is, so
reconstruction maps the name to its digit first. 39,208 rows (0.24%) have a
blank/malformed bbl; ALL rows in the table (including every one of those
39,208) carry a non-null borough/block/lot, so reconstruction always has
the inputs it needs -- verified directly, no unreconstructable rows.
A small number of those (571, all sampled with block=0/lot=0) will
reconstruct to a syntactically valid but non-existent BBL (block 0 is not a
real tax lot); this is not special-cased here because it doesn't need to
be -- the Building-first pattern below will simply find no matching
Building for that fake BBL and skip the row, same outcome as any other
unreconstructable row, just arrived at one step later.

Dependency order: run AFTER the buildings pipeline. Rows whose (real or
reconstructed) BBL has no Building node are skipped and counted.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied (portfolio pipeline `--step schema`).
    - Buildings pipeline already run.

Usage:
    uv run python -m watchline.discovery.ingest.hpd_complaints.pipeline
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Iterator, List

import psycopg2
from psycopg2.extras import RealDictCursor
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE

EVENT_BATCH_SIZE = 2000

LEGAL_AUTHORITY = "NYC Housing Maintenance Code (Admin Code Title 27) -- tenant complaint intake"



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(problemid) -> str:
    # Distinct token (COMPLAINT) from EVT-HPD-<violationid> and
    # EVT-HPD-LIT-<litigationid> -- same defensive reasoning hpd_litigations
    # documents: independently-assigned WoW id sequences are not safe to
    # assume disjoint, so give every source table its own namespaced prefix
    # rather than rely on numeric ranges never colliding.
    return f"EVT-HPD-COMPLAINT-{problemid}"


# ---------------------------------------------------------------------------
# Step 1: Event(Complaint, HPD) nodes + HAS_EVENT edges
# ---------------------------------------------------------------------------

# borough is a full name here, not a numeric boroid (unlike hpd_violations) --
# verified only these 5 values occur. bbl is CHAR(n) -> trim; reconstruct
# from borough/block/lot when it isn't a well-formed 10-digit 1-5-boro BBL --
# verified safe for every row in this table (see module docstring "BBL").
COMPLAINTS_SQL = """
SELECT
    problemid,
    complaintid,
    CASE WHEN trim(bbl) ~ '^[1-5][0-9]{9}$' THEN trim(bbl)
         ELSE (CASE borough
                   WHEN 'MANHATTAN'     THEN '1'
                   WHEN 'BRONX'         THEN '2'
                   WHEN 'BROOKLYN'      THEN '3'
                   WHEN 'QUEENS'        THEN '4'
                   WHEN 'STATEN ISLAND' THEN '5'
               END) || lpad(block::text, 5, '0') || lpad(lot::text, 4, '0')
    END                      AS bbl,
    type,
    receiveddate,
    problemstatus,
    complaintstatus,
    complaintstatusdate,
    problemstatusdate,
    statusdescription,
    majorcategory,
    minorcategory,
    problemcode,
    unittype,
    spacetype,
    apartment,
    problemduplicateflag,
    complaintanonymousflag,
    uniquekey
FROM hpd_complaints_and_problems
WHERE borough IN ('MANHATTAN', 'BRONX', 'BROOKLYN', 'QUEENS', 'STATEN ISLAND')
  AND block IS NOT NULL AND lot IS NOT NULL
"""


def _raw_record(row: dict) -> str:
    return json.dumps({
        "complaintstatus":        row["complaintstatus"],
        "complaintstatusdate":    row["complaintstatusdate"].isoformat() if row["complaintstatusdate"] else None,
        "problemstatusdate":      row["problemstatusdate"].isoformat() if row["problemstatusdate"] else None,
        "statusdescription":      row["statusdescription"],
        "majorcategory":          row["majorcategory"],
        "minorcategory":          row["minorcategory"],
        "problemcode":            row["problemcode"],
        "unittype":               row["unittype"],
        "spacetype":              row["spacetype"],
        "apartment":              row["apartment"],
        "problemduplicateflag":   row["problemduplicateflag"],
        "complaintanonymousflag": row["complaintanonymousflag"],
        "uniquekey":              row["uniquekey"],
    })


def _complaint_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="hpd_complaints", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(COMPLAINTS_SQL)
        batch = []
        for row in cur:
            batch.append({
                "event_id":         _event_id(row["problemid"]),
                "bbl":              row["bbl"],
                "violation_class":  row["type"],
                "status":           row["problemstatus"],
                "event_date":       row["receiveddate"].isoformat() if row["receiveddate"] else None,
                "source_id":        str(row["complaintid"]) if row["complaintid"] is not None else None,
                "source_record_id": str(row["problemid"]),
                "raw_record":       _raw_record(row),
            })
            if len(batch) == EVENT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_complaints(session, conn):
    """
    MERGE Event(Complaint, HPD) nodes and HAS_EVENT edges. Building-first:
    rows whose BBL has no Building node are skipped entirely (no orphan
    Event nodes) -- including the small number of rows whose reconstructed
    BBL is syntactically valid but not a real tax lot (see module docstring
    "BBL"). Returns (events_written, skipped_missing_building).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (b:Building {bbl: row.bbl})
    MERGE (e:Event:WatchlineNode {event_id: row.event_id})
    SET e.event_type       = 'Complaint',
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
    for batch in _complaint_batches(conn):
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
        if total % 200_000 == 0:
            print(f"    {total:,} complaint rows processed ...")
    return total, len(missing_bbls)


def step_complaints(driver) -> None:
    print("Step 1 -- Writing Event(Complaint, HPD) nodes + HAS_EVENT edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_complaints(session, conn)
        print(f"  {total:,} complaint rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node (rows skipped).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all(driver) -> None:
    step_complaints(driver)
    print("")
    print("HPD complaints ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG HPD complaints ingestion")
    parser.add_argument(
        "--step",
        choices=["complaints"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "complaints":
            step_complaints(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
