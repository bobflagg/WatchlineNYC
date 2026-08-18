"""
Watchline Discovery KG — ECB Violations Ingestion Pipeline
watchline/discovery/ingest/ecb_violations/pipeline.py

Creates a third Event source in the DISCOVERY knowledge graph: ECB
(Environmental Control Board) hearing judgments -- the adjudicated outcome
of HPD/DOB violations that were escalated to an ECB hearing.

What this pipeline creates:
    Event nodes (event_type='Judgment', source_name='ECB'), keyed
    event_id = EVT-ECB-<ecbviolationnumber>.
    (Building)-[:HAS_EVENT]->(Event) edges.

No Actor linkage: `respondentname` is free text (no deterministic key into
an Actor node the way wow_landlords bridges to landlords_with_connections),
so linking it would require fuzzy name matching -- forbidden in the
discovery layer. Same rationale as hpd_violations/dob_violations; respondent details
are kept in raw_record only, not promoted to PARTY_TO.

Field mapping (`ecb_violations`, ~1.82M rows; ecbviolationnumber is a
stable, globally-unique key -- verified 1:1 with row count, 0 nulls):
    event_date       <- issuedate (null in only 64 rows).
    status            <- ecbviolationstatus ('RESOLVE' | 'ACTIVE' |
                         'Unknown', passed through verbatim).
    violation_class   <- severity ('CLASS - 1/2/3' | 'Hazardous' |
                         'Non-Hazardous' | 'Unknown'), the ECB analogue of
                         HPD's A/B/C/I and DOB's violationtypecode.
    source_id         <- dobviolationnumber, the originating DOB violation
                         this judgment resulted from (~88% populated) --
                         note this is the *inverse* cross-reference of
                         dob_violations.source_id (<- ecbnumber), so the two
                         event kinds can be correlated by matching
                         ecb.source_record_id <-> dob.source_id and vice
                         versa without a graph edge.
    legal_authority   <- constant "NYC Environmental Control Board (Admin
                         Code)" -- ECB hearings adjudicate violations issued
                         under NYC Admin Code; the specific infraction
                         code/section lives in raw_record.
    raw_record        <- compact JSON: hearing/serve dates & time,
                         hearingstatus, certificationstatus, aggravatedlevel,
                         violationtype, violationdescription, respondent
                         name/address, penalty/paid/balance amounts, and the
                         up-to-10 (infractioncodeN, sectionlawdescriptionN)
                         pairs collapsed into a single "infractions" list
                         with null pairs dropped (most rows only populate 1-2
                         of the 10).

BBL: no boro/block/lot reconstruction (checked: the ~27.2K blank-bbl rows
have block/lot as blank/whitespace, not reconstructable -- same situation as
dob_violations). Rows with an unmatched bbl are skipped and counted.

Dependency order: run AFTER the buildings pipeline.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Discovery graph type applied (portfolio pipeline `--step schema`).
    - Buildings pipeline already run.

Usage:
    uv run python -m watchline.discovery.ingest.ecb_violations.pipeline
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Iterator, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_DISCOVERY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_DISCOVERY_DATABASE

EVENT_BATCH_SIZE = 2000

LEGAL_AUTHORITY = "NYC Environmental Control Board (Admin Code)"

INFRACTION_PAIRS = 10



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(ecbviolationnumber) -> str:
    return f"EVT-ECB-{ecbviolationnumber}"


def _blank_to_none(v: Optional[str]) -> Optional[str]:
    return v.strip() if v and v.strip() else None


# ---------------------------------------------------------------------------
# Step 1: Event(Judgment, ECB) nodes + HAS_EVENT edges
# ---------------------------------------------------------------------------

# bbl is CHAR(n) -> trim. No boro/block/lot reconstruction (see module
# docstring) -- rows with an unusable bbl simply fail to MATCH a Building
# and are skipped like any other unmatched row.
_INFRACTION_COLS = ", ".join(
    f"infractioncode{i}, sectionlawdescription{i}" for i in range(1, INFRACTION_PAIRS + 1)
)

VIOLATIONS_SQL = f"""
SELECT
    ecbviolationnumber,
    trim(bbl)                AS bbl,
    trim(severity)            AS severity,
    ecbviolationstatus,
    issuedate,
    dobviolationnumber,
    hearingdate,
    hearingtime,
    serveddate,
    hearingstatus,
    certificationstatus,
    aggravatedlevel,
    violationtype,
    violationdescription,
    respondentname,
    respondenthousenumber,
    respondentstreet,
    respondentcity,
    respondentzip,
    penalityimposed,
    amountpaid,
    balancedue,
    {_INFRACTION_COLS}
FROM ecb_violations
"""


def _raw_record(row: dict) -> str:
    infractions = []
    for i in range(1, INFRACTION_PAIRS + 1):
        code = _blank_to_none(row[f"infractioncode{i}"])
        desc = _blank_to_none(row[f"sectionlawdescription{i}"])
        if code or desc:
            infractions.append({"code": code, "description": desc})

    return json.dumps({
        "hearingdate":          row["hearingdate"].isoformat() if row["hearingdate"] else None,
        "hearingtime":          row["hearingtime"],
        "serveddate":           row["serveddate"].isoformat() if row["serveddate"] else None,
        "hearingstatus":        row["hearingstatus"],
        "certificationstatus":  row["certificationstatus"],
        "aggravatedlevel":      row["aggravatedlevel"],
        "violationtype":        row["violationtype"],
        "violationdescription": row["violationdescription"],
        "respondentname":       row["respondentname"],
        "respondentaddress": {
            "housenumber": row["respondenthousenumber"],
            "street":      row["respondentstreet"],
            "city":        row["respondentcity"],
            "zip":         row["respondentzip"],
        },
        "penalityimposed":      float(row["penalityimposed"]) if row["penalityimposed"] is not None else None,
        "amountpaid":           float(row["amountpaid"]) if row["amountpaid"] is not None else None,
        "balancedue":           float(row["balancedue"]) if row["balancedue"] is not None else None,
        "infractions":          infractions,
    })


def _violation_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="ecb_violations", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(VIOLATIONS_SQL)
        batch = []
        for row in cur:
            batch.append({
                "event_id":         _event_id(row["ecbviolationnumber"]),
                "bbl":              row["bbl"],
                "violation_class":  row["severity"],
                "status":           row["ecbviolationstatus"],
                "event_date":       row["issuedate"].isoformat() if row["issuedate"] else None,
                "source_id":        _blank_to_none(row["dobviolationnumber"]),
                "source_record_id": row["ecbviolationnumber"],
                "raw_record":       _raw_record(row),
            })
            if len(batch) == EVENT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_violations(session, conn):
    """
    MERGE Event(Judgment, ECB) nodes and HAS_EVENT edges. Building-first:
    rows whose BBL has no Building node are skipped entirely (no orphan
    Event nodes). Returns (events_written, skipped_missing_building).
    """
    cypher = """
    UNWIND $batch AS row
    MATCH (b:Building {bbl: row.bbl})
    MERGE (e:Event:WatchlineNode {event_id: row.event_id})
    SET e.event_type       = 'Judgment',
        e.source_name      = 'ECB',
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
    print("Step 1 -- Writing Event(Judgment, ECB) nodes + HAS_EVENT edges ...")
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
    print("ECB violations ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline discovery KG ECB violations ingestion")
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
