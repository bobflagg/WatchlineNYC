"""
Watchline Discovery KG — HPD Vacate Orders Ingestion Pipeline
watchline/discovery/ingest/hpd_vacateorders/pipeline.py

Creates a new Event source in the DISCOVERY knowledge graph: HPD vacate
orders -- HPD determined the building (or part of it) was dangerous enough
that residents had to leave. This is a stronger displacement/safety signal
than a Class C violation: it represents actual displacement caused by
conditions, not a citation that may or may not be remediated.

What this pipeline creates:
    Event nodes (event_type='VacateOrder', source_name='HPD'), keyed
    event_id = EVT-HPD-VACATE-<vacateordernumber>.
    (Building)-[:HAS_EVENT]->(Event) edges.

No Actor linkage: like hpd_violations and hpd_complaints, this table
carries no name/contact column at all, so no PARTY_TO edges are written
here.

Table scale note: this is a small table (8,752 rows, verified) compared to
every other Event source ingested so far (violations/complaints/ACRIS are
all millions of rows) -- vacate orders are a rare, severe event, not a
routine one. Do not expect this pipeline to take long to run.

Field mapping (`hpd_vacateorders`, vacateordernumber is a stable,
globally-unique key -- verified 1:1 with row count, 8,752 rows):
    event_date       <- vacateeffectivedate (0 nulls, verified).
    status            <- derived, not a passthrough column: 'Active' if
                         rescinddate IS NULL, else 'Rescinded' (this table
                         has no status column of its own; rescinddate's
                         presence/absence IS the status, per
                         next-ingestion-steps.md Priority 3). Verified
                         split: 4,247 / 8,752 (48.5%) have a rescinddate.
    violation_class   <- primaryvacatereason ('Fire Damage' | 'Illegal
                         Occupancy' | 'Habitability' -- verified these are
                         the only 3 values, 0 nulls) -- reuses the shared
                         classification slot for the vacate cause, the
                         closest analog to violation class A/B/C.
    source_id         <- registrationid, as a string (links back to the
                         HPD registration in effect at vacate time; left
                         null if WoW has it null -- no cross-reference
                         attempted here, same conservative choice
                         hpd_litigations makes for its own source_id).
    source_record_id  <- vacateordernumber, as a string.
    legal_authority   <- constant "NYC Multiple Dwelling Law / Housing
                         Maintenance Code (Admin Code Title 27) -- HPD
                         vacate order (imminent hazard)".
    raw_record        <- compact JSON: vacatetype ('Partial' |
                         'Entire Building' -- verified only these 2 values),
                         numberofvacatedunits, buildingid, street, number,
                         nta.

BBL: unlike every other HPD table ingested so far, hpd_vacateorders has NO
block/lot columns at all -- there is no reconstruction fallback available
here. Verified directly: 8,740 / 8,752 rows (99.86%) have a clean 10-digit
bbl; the remaining 12 are blank with no way to derive a BBL from this table
alone (borough alone -- a 2-letter code, see below -- is not enough).
`registrationid` is populated on those rows and could in principle bridge to
hpd_registrations for a bbl, but 12 rows out of 8,752 does not justify that
join's complexity; they are simply excluded via the WHERE clause below, the
same outcome the Building-first pattern would produce for them anyway (no
orphan Event, no silent partial data).

`borough` in this table is a 2-letter code (BK/BX/QN/MN/SI -- verified these
are the only 5 values), a THIRD distinct borough encoding across the tables
ingested so far (hpd_violations uses numeric boroid '1'-'5';
hpd_complaints_and_problems uses full names like 'BROOKLYN'). It is not
used at all here -- not selected, not mapped -- because without block/lot a
borough digit alone still can't reconstruct a BBL, so there's nothing useful
to do with it for the 12 blank-bbl rows; noted only so a future pipeline
that also touches this table doesn't assume the encoding matches one
already handled elsewhere.

Dependency order: run AFTER the buildings pipeline. Rows whose BBL has no
Building node are skipped and counted.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied (portfolio pipeline `--step schema`).
    - Buildings pipeline already run.

Usage:
    uv run python -m watchline.discovery.ingest.hpd_vacateorders.pipeline
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

LEGAL_AUTHORITY = ("NYC Multiple Dwelling Law / Housing Maintenance Code "
                    "(Admin Code Title 27) -- HPD vacate order (imminent hazard)")



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(vacateordernumber) -> str:
    # Distinct token (VACATE), same defensive reasoning as every other HPD
    # source in this graph: don't assume WoW's independently-assigned id
    # sequences are disjoint (see hpd_litigations, hpd_complaints).
    return f"EVT-HPD-VACATE-{vacateordernumber}"


# ---------------------------------------------------------------------------
# Step 1: Event(VacateOrder, HPD) nodes + HAS_EVENT edges
# ---------------------------------------------------------------------------

# No block/lot in this table -- unlike every other HPD source, there is no
# reconstruction fallback for a blank/malformed bbl, so rows without a clean
# 10-digit bbl are excluded outright (verified: only 12 of 8,752 rows, see
# module docstring "BBL"). status is derived here, not passed through --
# this table has no status column; rescinddate's presence/absence IS the
# status (next-ingestion-steps.md Priority 3).
VACATEORDERS_SQL = """
SELECT
    vacateordernumber,
    trim(bbl)               AS bbl,
    primaryvacatereason,
    CASE WHEN rescinddate IS NULL THEN 'Active' ELSE 'Rescinded' END AS status,
    vacateeffectivedate,
    registrationid,
    vacatetype,
    numberofvacatedunits,
    buildingid,
    street,
    number,
    nta
FROM hpd_vacateorders
WHERE trim(bbl) ~ '^[1-5][0-9]{9}$'
"""


def _raw_record(row: dict) -> str:
    return json.dumps({
        "vacatetype":           row["vacatetype"],
        "numberofvacatedunits": row["numberofvacatedunits"],
        "buildingid":           row["buildingid"],
        "street":               row["street"],
        "number":               row["number"],
        "nta":                  row["nta"],
    })


def _vacateorder_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="hpd_vacateorders", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(VACATEORDERS_SQL)
        batch = []
        for row in cur:
            batch.append({
                "event_id":         _event_id(row["vacateordernumber"]),
                "bbl":              row["bbl"],
                "violation_class":  row["primaryvacatereason"],
                "status":           row["status"],
                "event_date":       row["vacateeffectivedate"].isoformat() if row["vacateeffectivedate"] else None,
                "source_id":        str(row["registrationid"]) if row["registrationid"] is not None else None,
                "source_record_id": str(row["vacateordernumber"]),
                "raw_record":       _raw_record(row),
            })
            if len(batch) == EVENT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_vacateorders(session, conn):
    """
    MERGE Event(VacateOrder, HPD) nodes and HAS_EVENT edges. Building-first:
    rows whose BBL has no Building node are skipped entirely (no orphan
    Event nodes). Returns (events_written, skipped_missing_building).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (b:Building {bbl: row.bbl})
    MERGE (e:Event:WatchlineNode {event_id: row.event_id})
    SET e.event_type       = 'VacateOrder',
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
    for batch in _vacateorder_batches(conn):
        bbls = {row["bbl"] for row in batch}
        matched = session.run(
            "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN collect(bbl) AS matched",
            bbls=list(bbls),
        ).single()["matched"]
        missing_bbls.update(bbls - set(matched))

        session.run(cypher, batch=batch, now=now, legal_authority=LEGAL_AUTHORITY)
        total += len(batch)
        if total % 2_000 == 0:
            print(f"    {total:,} vacate order rows processed ...")
    return total, len(missing_bbls)


def step_vacateorders(driver) -> None:
    print("Step 1 -- Writing Event(VacateOrder, HPD) nodes + HAS_EVENT edges ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_vacateorders(session, conn)
        print(f"  {total:,} vacate order rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node (rows skipped).")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_all(driver) -> None:
    step_vacateorders(driver)
    print("")
    print("HPD vacate orders ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG HPD vacate orders ingestion")
    parser.add_argument(
        "--step",
        choices=["vacateorders"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "vacateorders":
            step_vacateorders(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
