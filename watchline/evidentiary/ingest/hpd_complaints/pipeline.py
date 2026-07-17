"""
Watchline Evidentiary — HPD Tenant Complaints Ingestion Pipeline
watchline/evidentiary/ingest/hpd_complaints/pipeline.py

Ingests HPD tenant-initiated complaints from the WoW PostgreSQL database
(`wow`, port 5434) into the evidentiary knowledge graph. A complaint is what
a tenant reported; a violation (hpd_violations) is what an inspector
confirmed. The gap between the two is itself an accountability signal.

What this pipeline creates:
  Layer 1 (Domain):
    - Event nodes of event_type=Complaint, source_name=HPD
    - HAS_EVENT edges linking Buildings to their Complaints
  Layer 2 (Evidence):
    - Source node for HPD Complaints
    - Observation nodes (one per complaint row)
    - ORIGINATES_IN edges from both Event and Observation to Source

event_id scheme matches discovery exactly (Reconciliation Principle 2):
EVT-HPD-COMPLAINT-{problemid}, keyed on problemid (not complaintid) --
problemid is 100% unique (verified 16,164,450 distinct rows this session,
matching discovery/ingest/hpd_complaints' verified count); complaintid is
NOT unique (one complaint can report multiple problems), so it is carried
as the complaint_id property (the grouping key) rather than the Event key,
same reasoning discovery's pipeline documents in full.

Field promotion follows the evidentiary convention (richer top-level Event
properties, not discovery's raw_record-blob-only approach -- see
hpd_violations/hpd_litigations for the precedent): status, violation_class,
description, and several complaint-specific fields (complaint_status,
major/minor_category, problem_code, unit_type, space_type, apartment,
duplicate_flag, anonymous_flag) are promoted to distinct properties.
duplicate_flag and anonymous_flag are native SQL booleans in
hpd_complaints_and_problems (verified this session via live WoW: no string
encoding to guess at) -- anonymous_flag has a third state, NULL (1,453,187
rows), passed through as null rather than coerced to false.

NOTE on data_url: unlike the other evidentiary Source nodes in this
codebase, no NYC Open Data URL is recorded here. The exact dataset URL for
hpd_complaints_and_problems was not independently verified this session
(Reconciliation Principle 9 -- verify before asserting), and this project's
own epistemic standard is to not assert what hasn't been checked. Fill in
once confirmed against the live NYC Open Data catalog.

BBL reconstruction and Building-linking: identical logic and rationale to
discovery/ingest/hpd_complaints (borough is a full name here, not a numeric
boroid; ~0.24% of rows need reconstruction from borough/block/lot; a small
number of those reconstruct to a syntactically valid but non-existent BBL
and are simply skipped as unmatched, not special-cased). Per
notes/evidentiary-ingestion-plan.md task 3, this pipeline deliberately uses
discovery's Building-first skip-and-count pattern (MATCH, not MERGE) rather
than hpd_violations/hpd_litigations' minimal-stub-creation pattern: by the
time this runs (after evidentiary-hpd in the Makefile dependency order),
the ~444K Buildings from HPD violations ingestion already cover the
overwhelming majority of BBLs seen here, so stub creation would be almost
entirely redundant.

Dependency order: run AFTER evidentiary-buildings and evidentiary-hpd.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Evidentiary graph type applied (`make evidentiary-schema`). No new
      declared Building/Event fields required -- Event is open-schema
      beyond its declared core (same as hpd_violations/hpd_litigations,
      which already write many undeclared top-level properties).
    - Buildings and HPD violations pipelines already run.

Usage:
    uv run python -m watchline.evidentiary.ingest.hpd_complaints.pipeline
    uv run python -m watchline.evidentiary.ingest.hpd_complaints.pipeline --step source
    uv run python -m watchline.evidentiary.ingest.hpd_complaints.pipeline --step complaints
"""

import argparse
import json
from datetime import datetime, timezone
from typing import Iterator, List

from psycopg2.extras import RealDictCursor

from watchline.shared.batching import BATCH_SIZE, CURSOR_ITERSIZE
from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE
COMPLAINT_BATCH_SIZE = BATCH_SIZE

HPD_COMPLAINTS_SOURCE = {
    "source_id":        "SRC-HPD-COMPLAINTS-001",
    "source_name":      "HPD Complaints",
    "producing_agency": "NYC Department of Housing Preservation and Development",
    "legal_authority": (
        "NYC Housing Maintenance Code (Admin Code Title 27) -- tenant "
        "complaint intake. HPD is required to record and triage complaints "
        "reported by tenants or their representatives; a complaint does not "
        "itself constitute a Housing Maintenance Code violation finding."
    ),
    "data_url": None,  # not independently verified this session -- see module docstring
    "description": (
        "HPD tenant-initiated complaints and their constituent reported "
        "problems. Legally empowered to assert: that a tenant (or their "
        "representative) reported a specific problem condition to HPD, the "
        "problem's self-reported category and urgency, and the intake/"
        "resolution status of that report. Does NOT assert that an HPD "
        "inspector confirmed the condition, that the condition still "
        "exists, or that the reported apartment/building was actually "
        "inspected -- a complaint is what a tenant reported, not what an "
        "inspector confirmed. See HPD Violations (source_name='HPD', "
        "event_type='Violation') for inspector-confirmed conditions."
    ),
}

LEGAL_AUTHORITY = (
    "NYC Housing Maintenance Code (Admin Code Title 27) -- tenant complaint intake"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(problemid) -> str:
    # Matches discovery's scheme exactly (Reconciliation Principle 2) --
    # EVT-HPD-COMPLAINT-{problemid}, distinct from EVT-HPD-{violationid}
    # and EVT-HPD-LIT-{litigationid}.
    return f"EVT-HPD-COMPLAINT-{problemid}"


# ---------------------------------------------------------------------------
# Step 1: Source node
# ---------------------------------------------------------------------------

def create_source_node(session) -> None:
    now   = _now()
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
        **HPD_COMPLAINTS_SOURCE,
    )
    print(f"  Source node created/updated: {HPD_COMPLAINTS_SOURCE['source_name']}")


# ---------------------------------------------------------------------------
# Step 2: Complaint Events + Observations
# ---------------------------------------------------------------------------

# borough is a full name here, not a numeric boroid (unlike hpd_violations) --
# verified in discovery's session only these 5 values occur. bbl is CHAR(n) ->
# trim; reconstruct from borough/block/lot when it isn't a well-formed
# 10-digit 1-5-boro BBL.
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
        "complaintid":            row["complaintid"],
        "problemid":               row["problemid"],
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
    with conn.cursor(name="ev_hpd_complaints", cursor_factory=RealDictCursor) as cur:
        cur.itersize = CURSOR_ITERSIZE
        cur.execute(COMPLAINTS_SQL)
        batch: List[dict] = []
        for row in cur:
            batch.append({
                "event_id":              _event_id(row["problemid"]),
                "bbl":                   row["bbl"],
                "source_record_id":      str(row["problemid"]),
                "complaint_id":          str(row["complaintid"]) if row["complaintid"] is not None else None,
                "event_date":            row["receiveddate"].isoformat() if row["receiveddate"] else None,
                "status":                row["problemstatus"],
                "violation_class":       row["type"],
                "description":           row["statusdescription"],
                "complaint_status":      row["complaintstatus"],
                "complaint_status_date": row["complaintstatusdate"].isoformat() if row["complaintstatusdate"] else None,
                "problem_status_date":   row["problemstatusdate"].isoformat() if row["problemstatusdate"] else None,
                "major_category":        row["majorcategory"],
                "minor_category":        row["minorcategory"],
                "problem_code":          row["problemcode"],
                "unit_type":             row["unittype"],
                "space_type":            row["spacetype"],
                "apartment":             row["apartment"],
                "duplicate_flag":        row["problemduplicateflag"],
                "anonymous_flag":        row["complaintanonymousflag"],
                "unique_key":            row["uniquekey"],
                "raw_record":            _raw_record(row),
            })
            if len(batch) == COMPLAINT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_complaints(session, conn) -> tuple:
    """
    MERGE Event(Complaint, HPD) + Observation nodes, both ORIGINATES_IN the
    Source. Building-first, skip-and-count (MATCH, not MERGE) -- same
    pattern as discovery's hpd_complaints; see module docstring. Returns
    (events_written, skipped_missing_building).
    """
    event_cypher = """
    UNWIND $batch AS v
    MATCH (bld:Building {bbl: v.bbl})
    MERGE (e:Event:WatchlineNode {event_id: v.event_id})
    SET e.event_type            = 'Complaint',
        e.source_id             = $source_id,
        e.source_name           = 'HPD',
        e.source_record_id      = v.source_record_id,
        e.complaint_id          = v.complaint_id,
        e.event_date            = CASE WHEN v.event_date IS NOT NULL
                                       THEN date(v.event_date) ELSE null END,
        e.status                = v.status,
        e.violation_class       = v.violation_class,
        e.description           = v.description,
        e.complaint_status      = v.complaint_status,
        e.complaint_status_date = CASE WHEN v.complaint_status_date IS NOT NULL
                                       THEN date(v.complaint_status_date) ELSE null END,
        e.problem_status_date   = CASE WHEN v.problem_status_date IS NOT NULL
                                       THEN date(v.problem_status_date) ELSE null END,
        e.major_category        = v.major_category,
        e.minor_category        = v.minor_category,
        e.problem_code          = v.problem_code,
        e.unit_type             = v.unit_type,
        e.space_type            = v.space_type,
        e.apartment             = v.apartment,
        e.duplicate_flag        = v.duplicate_flag,
        e.anonymous_flag        = v.anonymous_flag,
        e.unique_key            = v.unique_key,
        e.legal_authority       = $legal_authority,
        e.raw_record            = v.raw_record,
        e.created_at            = CASE WHEN e.created_at IS NULL
                                       THEN datetime($now) ELSE e.created_at END
    MERGE (bld)-[:HAS_EVENT]->(e)
    WITH e, v
    MATCH (s:Source {source_id: $source_id})
    MERGE (obs:Observation:WatchlineNode {
        observation_id: 'OBS-HPD-COMPLAINT-' + v.source_record_id
    })
    SET obs.source_id        = $source_id,
        obs.raw_content      = v.raw_record,
        obs.source_record_id = v.source_record_id,
        obs.ingested_at      = CASE WHEN obs.ingested_at IS NULL
                                    THEN datetime($now) ELSE obs.ingested_at END
    MERGE (obs)-[:ORIGINATES_IN]->(s)
    MERGE (e)-[:ORIGINATES_IN]->(s)
    """
    now = _now()
    total = 0
    missing_bbls = set()
    for batch in _complaint_batches(conn):
        # Track BBLs in this batch with no Building node in a global set, so a
        # BBL recurring across many batches is only counted once.
        bbls = {row["bbl"] for row in batch}
        matched = session.run(
            "UNWIND $bbls AS bbl MATCH (b:Building {bbl: bbl}) RETURN collect(bbl) AS matched",
            bbls=list(bbls),
        ).single()["matched"]
        missing_bbls.update(bbls - set(matched))

        session.run(
            event_cypher,
            batch=batch,
            now=now,
            source_id=HPD_COMPLAINTS_SOURCE["source_id"],
            legal_authority=LEGAL_AUTHORITY,
        )
        total += len(batch)
        if total % 200_000 == 0:
            print(f"    {total:,} complaint rows processed ...")
    return total, len(missing_bbls)


def step_source(driver):
    print("Step 1 -- Creating/updating HPD Complaints Source node ...")
    with driver.session(database=NEO4J_DATABASE) as session:
        create_source_node(session)
    print("  Done.")


def step_complaints(driver):
    print("Step 2 -- Writing Event(Complaint, HPD) + Observation nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_complaints(session, conn)
        print(f"  {total:,} complaint rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node (rows skipped).")
    finally:
        conn.close()


def run_all(driver):
    step_source(driver)
    step_complaints(driver)
    print("")
    print("HPD complaints ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline evidentiary HPD complaints ingestion")
    parser.add_argument(
        "--step",
        choices=["source", "complaints"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "source":
            step_source(driver)
        elif args.step == "complaints":
            step_complaints(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
