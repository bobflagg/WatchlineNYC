"""
Watchline ECB/OATH Violations Ingestion Pipeline
watchline/ingest/ecb_violations/pipeline.py

Ingests NYC Environmental Control Board (ECB) / OATH violations from the
WoW PostgreSQL database (`wow`, port 5434) into the Watchline Neo4j knowledge graph.

ECB violations are adjudicated enforcement actions issued by the Office of
Administrative Trials and Hearings (OATH), distinct from HPD and DOB
administrative violations. They carry financial penalties and represent a
formal legal finding against a respondent.

What this pipeline creates:
  Layer 1 (Domain):
    - Building nodes via MERGE (new BBLs only; existing nodes unchanged)
    - Event nodes of event_type=Judgment (one per ECB violation)
    - HAS_EVENT edges linking Buildings to their ECB Judgments

  Layer 2 (Evidence):
    - Source node for ECB Violations
    - Observation nodes (one per violation row)
    - ORIGINATES_IN edges to Source

Key design decisions:
  - event_type is 'Judgment' not 'Violation': ECB records are adjudicated
    outcomes, not administrative notices. Charter Principle 16 (Scope of
    Jurisdiction) requires this distinction.
  - Interpretive status of Stipulated applies where hearingstatus indicates
    a formal finding (IN VIOLATION, DEFAULT, ADMIT/IN-VIO, POP/IN-VIO,
    STIPULATION/IN-VIO). Dismissed records are Observed.
  - Financial fields (penalityimposed, amountpaid, balancedue) are stored
    as Event properties -- they are legally significant facts.
  - dobviolationnumber is stored as a property on ECB Event nodes for
    reference but cannot be used to join to DOB Event nodes: the ECB
    dobviolationnumber format (e.g. 112808NRF) encodes a legacy DOB
    inspection identifier that does not correspond to any field in the
    current DOB violations dataset.
  - Infraction codes (up to 5) are concatenated as a pipe-delimited string.
  - Severity taxonomy: DOB-referred use CLASS 1/2/3; HPD-referred use
    Hazardous/Non-Hazardous. Both are preserved in violation_class.

Usage:
    uv run python -m watchline.evidentiary.ingest.ecb_violations.pipeline
    uv run python -m watchline.evidentiary.ingest.ecb_violations.pipeline --step source
    uv run python -m watchline.evidentiary.ingest.ecb_violations.pipeline --step buildings
    uv run python -m watchline.evidentiary.ingest.ecb_violations.pipeline --step violations
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Iterator, List

import psycopg2
from psycopg2.extras import RealDictCursor

from watchline.shared.batching import BATCH_SIZE, CURSOR_ITERSIZE
from watchline.shared.bbl import borough_from_bbl
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE
VIOLATION_BATCH_SIZE = BATCH_SIZE

ECB_VIOLATIONS_SOURCE = {
    "source_id":        "SRC-ECB-VIOLATIONS-001",
    "source_name":      "ECB Violations",
    "producing_agency": "NYC Office of Administrative Trials and Hearings (OATH)",
    "legal_authority": (
        "New York City Charter Section 1049-a. OATH is empowered to adjudicate "
        "violations referred by city agencies including DOB and HPD. ECB "
        "violations represent formal adjudicated findings, not administrative "
        "notices. A finding of IN VIOLATION or DEFAULT constitutes a legal "
        "determination that the respondent violated the cited code section."
    ),
    "data_url": (
        "https://data.cityofnewyork.us/City-Government/"
        "ECB-Violations/6bgk-3dad"
    ),
    "description": (
        "OATH/ECB adjudicated violations. Legally empowered to assert: that "
        "OATH held a hearing and reached a disposition on a violation referred "
        "by a city agency, the penalty imposed, the amount paid, and the "
        "outstanding balance due. A hearing status of IN VIOLATION or DEFAULT "
        "is a legal finding. DISMISSED means no violation was found. "
        "Financial fields reflect the official OATH record. Does NOT assert "
        "current property condition or ownership."
    ),
}

# ---------------------------------------------------------------------------
# Status mapping
# ecbviolationstatus -> Event.status
# ---------------------------------------------------------------------------
STATUS_MAP = {
    "ACTIVE":   "Active",
    "RESOLVE":  "Closed",
    "Unknown":  "Unknown",
}

# hearingstatus -> interpretive_status for the Event node
# Findings that constitute formal legal determinations -> Stipulated
# Dismissals -> Observed (the fact of dismissal is observable)
# Pending -> Inferred (outcome not yet determined)
HEARING_STATUS_INTERPRETIVE = {
    "IN VIOLATION":      "Stipulated",
    "DEFAULT":           "Stipulated",
    "ADMIT/IN-VIO":      "Stipulated",
    "POP/IN-VIO":        "Stipulated",
    "STIPULATION/IN-VIO": "Stipulated",
    "CURED/IN-VIO":      "Stipulated",
    "DISMISSED":         "Observed",
    "WRITTEN OFF":       "Observed",
    "PENDING":           "Inferred",
}




def normalize_bbl(bbl, boro, block, lot) -> str:
    bbl = (bbl or "").strip()
    if len(bbl) == 10:
        return bbl
    return (
        str(boro  or "0").strip().zfill(1) +
        str(block or "0").strip().zfill(5) +
        str(lot   or "0").strip().zfill(4)
    )


# ---------------------------------------------------------------------------
# Step 1: Source nodes
# ---------------------------------------------------------------------------

def create_source_nodes(session) -> None:
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
        **ECB_VIOLATIONS_SOURCE,
    )
    print(f"  Source node created/updated: {ECB_VIOLATIONS_SOURCE['source_name']}")


# ---------------------------------------------------------------------------
# Step 2: Building nodes
# ---------------------------------------------------------------------------

# Schema-only stub (ADR-001): PLUTO enrichment is done by the shared buildings
# substrate (evidentiary-buildings). This step only ensures a landing node
# exists for every BBL seen in ecb_violations that wasn't covered by PLUTO.
_BACKFILL_SQL = """
SELECT DISTINCT
    CASE
        WHEN trim(bbl) = '' OR bbl IS NULL
        THEN lpad(boro::text,1,'0')||lpad(block::text,5,'0')||lpad(lot::text,4,'0')
        ELSE trim(bbl)
    END AS bbl
FROM ecb_violations
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
    with conn.cursor(name="ecb_viol_bbls", cursor_factory=RealDictCursor) as cur:
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
    """Ensure a Building node exists for every ECB violation BBL.

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
# Step 3: ECB Violation (Judgment) Events + Observations
# ---------------------------------------------------------------------------

VIOLATIONS_SQL = """
SELECT
    e.ecbviolationnumber,
    e.ecbviolationstatus,
    e.dobviolationnumber,
    e.hearingdate,
    e.serveddate,
    e.issuedate,
    e.severity,
    e.violationtype,
    e.respondentname,
    e.violationdescription,
    e.penalityimposed,
    e.amountpaid,
    e.balancedue,
    e.infractioncode1, e.sectionlawdescription1,
    e.infractioncode2, e.sectionlawdescription2,
    e.infractioncode3, e.sectionlawdescription3,
    e.infractioncode4, e.sectionlawdescription4,
    e.infractioncode5, e.sectionlawdescription5,
    e.aggravatedlevel,
    e.hearingstatus,
    e.certificationstatus,
    CASE
        WHEN trim(e.bbl) = '' OR e.bbl IS NULL
        THEN lpad(e.boro::text,1,'0')||lpad(e.block::text,5,'0')||lpad(e.lot::text,4,'0')
        ELSE trim(e.bbl)
    END AS bbl_canonical
FROM ecb_violations e
WHERE e.bbl IS NOT NULL
"""


def _collect_infraction_codes(row) -> str:
    """Concatenate up to 5 non-null infraction codes as a pipe-delimited string."""
    codes = []
    for i in range(1, 6):
        code = (row.get(f"infractioncode{i}") or "").strip()
        if code:
            desc = (row.get(f"sectionlawdescription{i}") or "").strip()
            # Trim the heavily padded section law descriptions
            desc = " ".join(desc.split())[:120] if desc else ""
            codes.append(f"{code}: {desc}" if desc else code)
    return " | ".join(codes) if codes else None


def _violation_batches(conn) -> Iterator[List[dict]]:
    # Use a named server-side cursor to stream rows from Postgres rather than
    # buffering all 1.8M rows in memory before iteration begins.
    # itersize controls how many rows Postgres sends per network round-trip.
    with conn.cursor(name="ecb_violations_cursor",
                     cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        print("  Querying ECB violations ...")
        cur.execute(VIOLATIONS_SQL)
        batch = []
        for row in cur:
            def d(col):
                v = row.get(col)
                return v.isoformat() if v else None

            hearing_status = (row["hearingstatus"] or "").strip()
            ecb_status = (row["ecbviolationstatus"] or "").strip()
            interpretive_status = HEARING_STATUS_INTERPRETIVE.get(
                hearing_status, "Observed"
            )

            # event_date: prefer issuedate, fall back to serveddate, hearingdate
            event_date = d("issuedate") or d("serveddate") or d("hearingdate")

            # Financial fields -- store as floats, None if null
            def money(col):
                v = row.get(col)
                return float(v) if v is not None else None

            batch.append({
                "event_id":              f"EVT-ECB-{row['ecbviolationnumber']}",
                "bbl":                   row["bbl_canonical"],
                "source_record_id":      row["ecbviolationnumber"],
                "event_type":            "Judgment",
                "source_name":           "ECB",
                "event_date":            event_date,
                "status":                STATUS_MAP.get(ecb_status, "Unknown"),
                "violation_class":       (row["severity"] or "").strip() or None,
                "hearing_date":          d("hearingdate"),
                "served_date":           d("serveddate"),
                "issue_date":            d("issuedate"),
                "hearing_status":        hearing_status or None,
                "certification_status":  (row["certificationstatus"] or "").strip() or None,
                "violation_type":        (row["violationtype"] or "").strip() or None,
                "violation_description": (row["violationdescription"] or "").strip() or None,
                "respondent_name":       (row["respondentname"] or "").strip() or None,
                "dob_violation_number":  (row["dobviolationnumber"] or "").strip() or None,
                "penalty_imposed":       money("penalityimposed"),
                "amount_paid":           money("amountpaid"),
                "balance_due":           money("balancedue"),
                "infraction_codes":      _collect_infraction_codes(row),
                "aggravated_level":      (row["aggravatedlevel"] or "").strip() or None,
                "interpretive_status":   interpretive_status,
                "legal_authority":       "NYC Charter Section 1049-a; OATH adjudication",
                "raw_record":            json.dumps({
                    "ecbviolationnumber": row["ecbviolationnumber"],
                    "ecbviolationstatus": row["ecbviolationstatus"],
                    "hearingstatus":      row["hearingstatus"],
                    "severity":           row["severity"],
                    "penalityimposed":    str(row["penalityimposed"]),
                    "balancedue":         str(row["balancedue"]),
                    "dobviolationnumber": row["dobviolationnumber"],
                }),
            })
            if len(batch) == VIOLATION_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_violations(session, conn) -> tuple:
    """
    Write ECB Judgment Event nodes and Observation nodes.
    Also stores dob_violation_number as a property on ECB Event nodes.
    Note: direct graph linking to DOB Event nodes is not feasible because
    the ECB dobviolationnumber format does not match the DOB number field.
    where dobviolationnumber matches an existing EVT-DOB-* event_id.
    Skips rows with no usable event_date (event_date is NOT NULL in schema).
    """
    event_cypher = """
    UNWIND $batch AS v
    MATCH (bld:Building {bbl: v.bbl})
    MERGE (e:Event:WatchlineNode {event_id: v.event_id})
    SET e.event_type            = v.event_type,
        e.source_id             = $source_id,
        e.source_name           = v.source_name,
        e.source_record_id      = v.source_record_id,
        e.event_date            = date(v.event_date),
        e.status                = v.status,
        e.violation_class       = v.violation_class,
        e.hearing_date          = CASE WHEN v.hearing_date IS NOT NULL
                                       THEN date(v.hearing_date) ELSE null END,
        e.served_date           = CASE WHEN v.served_date IS NOT NULL
                                       THEN date(v.served_date) ELSE null END,
        e.issue_date            = CASE WHEN v.issue_date IS NOT NULL
                                       THEN date(v.issue_date) ELSE null END,
        e.hearing_status        = v.hearing_status,
        e.certification_status  = v.certification_status,
        e.violation_type        = v.violation_type,
        e.violation_description = v.violation_description,
        e.respondent_name       = v.respondent_name,
        e.dob_violation_number  = v.dob_violation_number,
        e.penalty_imposed       = v.penalty_imposed,
        e.amount_paid           = v.amount_paid,
        e.balance_due           = v.balance_due,
        e.infraction_codes      = v.infraction_codes,
        e.aggravated_level      = v.aggravated_level,
        e.interpretive_status   = v.interpretive_status,
        e.legal_authority       = v.legal_authority,
        e.raw_record            = v.raw_record,
        e.created_at            = CASE WHEN e.created_at IS NULL
                                       THEN datetime($now) ELSE e.created_at END
    MERGE (bld)-[:HAS_EVENT]->(e)
    WITH e, v
    MATCH (s:Source {source_id: $source_id})
    MERGE (obs:Observation:WatchlineNode {
        observation_id: 'OBS-ECB-' + v.source_record_id
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
        valid = [v for v in batch if v["event_date"] is not None]
        total_skipped += len(batch) - len(valid)
        if not valid:
            continue

        session.run(
            event_cypher,
            batch=valid,
            source_id=ECB_VIOLATIONS_SOURCE["source_id"],
            now=now,
        )
        total += len(valid)

        if total % 100_000 == 0:
            print(f"    {total:,} ECB violations written ...")

    return total, total_skipped


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_source(driver):
    print("Step 1 -- Creating/updating ECB Violations Source node ...")
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
    print("Step 3 -- Writing ECB Judgment Event nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_violations(session, conn)
        print(f"  {total:,} ECB Judgment Events written.")
        if skipped:
            print(f"  {skipped:,} violations skipped (no usable date).")
    finally:
        conn.close()


def run_all(driver):
    step_source(driver)
    step_buildings(driver)
    step_violations(driver)
    print("")
    print("ECB violations ingestion complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Watchline ECB violations ingestion")
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
