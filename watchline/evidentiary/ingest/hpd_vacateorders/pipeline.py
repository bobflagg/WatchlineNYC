"""
Watchline Evidentiary — HPD Vacate Orders Ingestion Pipeline
watchline/evidentiary/ingest/hpd_vacateorders/pipeline.py

Ingests HPD vacate orders -- HPD's determination that a building (or part of
it) was dangerous enough that residents had to leave -- into the evidentiary
graph. Substrate for Rule VA-001 (Vacate History, RUL-00015). This is a
stronger displacement/safety signal than a Class C violation: actual
displacement caused by conditions, not a citation that may or may not be
remediated.

Field mapping and verified facts are identical to discovery's
hpd_vacateorders pipeline (re-verified against live WoW this session:
8,752 total rows, 4,247 rescinded, 8,740 with a clean 10-digit bbl, reasons
{Fire Damage: 4,693, Illegal Occupancy: 3,423, Habitability: 636}) -- see
that module's docstring for the full verified data-shape notes (table
scale, BBL reconstruction limits, the 2-letter vs full-name vs numeric
borough-encoding note). Event id matches discovery exactly (Reconciliation
Principle 2): EVT-HPD-VACATE-{vacateordernumber}.

Differences from discovery's shape, matching this session's evidentiary
conventions (hpd_complaints, acris_mortgages):
  - A Source node (SRC-HPD-VACATE-001) and one Observation node per row
    (OBS-HPD-VACATE-{vacateordernumber}), both ORIGINATES_IN the Source --
    discovery has neither (discovery deliberately carries no Evidence-layer
    element types at all).
  - source_id on the Event is the Source's own source_id (a foreign key),
    not registrationid as discovery uses it. registrationid is instead
    promoted to its own distinctly-named property, registration_id.
  - Additional top-level properties promoted beyond discovery's raw_record
    blob, per the evidentiary convention of richer Event fields:
    rescind_date (the actual date, not just the derived status), vacate_type
    ('Partial' | 'Entire Building'), units_vacated. violation_class still
    reuses the shared classification slot for primaryvacatereason, same as
    discovery.

Table scale note: 8,752 rows -- small compared to every other evidentiary
Event source ingested this session. Single-pass, no batching concerns.

Building linking: MATCH-only, skip-and-count (no minimal Building-stub
creation) -- same choice made for hpd_complaints and acris_mortgages this
session, on the same reasoning: by the time this runs (after
evidentiary-buildings and evidentiary-hpd), the ~444K Buildings from HPD
violation ingestion already cover the overwhelming majority of BBLs a
vacate order could reference.

Prerequisites:
    - Reads WoW (`wow`, port 5434), NOT `deedwatch`.
    - Evidentiary graph type applied (`make evidentiary-schema`). No new
      declared fields needed -- Event is open-schema beyond its declared
      core, same as every other evidentiary Event pipeline.
    - Buildings and HPD violations pipelines already run.

Usage:
    uv run python -m watchline.evidentiary.ingest.hpd_vacateorders.pipeline
    uv run python -m watchline.evidentiary.ingest.hpd_vacateorders.pipeline --step source
    uv run python -m watchline.evidentiary.ingest.hpd_vacateorders.pipeline --step vacateorders
"""

import argparse
import json
from datetime import datetime, timezone
from typing import Iterator, List

from psycopg2.extras import RealDictCursor

from watchline.shared.connections import pg_conn, neo4j_driver, NEO4J_EVIDENTIARY_DATABASE


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = NEO4J_EVIDENTIARY_DATABASE
EVENT_BATCH_SIZE = 2000

HPD_VACATE_SOURCE = {
    "source_id":        "SRC-HPD-VACATE-001",
    "source_name":      "HPD Vacate Orders",
    "producing_agency": "NYC Department of Housing Preservation and Development",
    "legal_authority": (
        "NYC Multiple Dwelling Law / Housing Maintenance Code (Admin Code "
        "Title 27) -- HPD vacate order (imminent hazard)."
    ),
    "data_url": None,  # not independently verified this session
    "description": (
        "HPD vacate orders: HPD's determination that a building, or part of "
        "one, is dangerous enough that residents must leave. Legally "
        "empowered to assert: that HPD issued an order requiring residents "
        "to vacate a specific building (or unit) on a specific date, the "
        "primary reason (Fire Damage, Illegal Occupancy, or Habitability), "
        "and whether that order has since been rescinded. Does NOT assert "
        "the building's current condition, current occupancy status, or "
        "that displaced residents have or have not returned -- only that "
        "HPD's order was issued and, if applicable, later rescinded."
    ),
}

LEGAL_AUTHORITY = HPD_VACATE_SOURCE["legal_authority"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(vacateordernumber) -> str:
    # Matches discovery's scheme exactly (Reconciliation Principle 2).
    return f"EVT-HPD-VACATE-{vacateordernumber}"


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
        **HPD_VACATE_SOURCE,
    )
    print(f"  Source node created/updated: {HPD_VACATE_SOURCE['source_name']}")


# ---------------------------------------------------------------------------
# Step 2: VacateOrder Events + Observations
# ---------------------------------------------------------------------------

# bbl has no block/lot reconstruction fallback in this table (verified --
# see module docstring) -- rows with a non-clean bbl are simply excluded.
VACATE_ORDERS_SQL = """
SELECT
    vacateordernumber,
    trim(bbl)              AS bbl,
    vacateeffectivedate,
    rescinddate,
    primaryvacatereason,
    vacatetype,
    numberofvacatedunits,
    registrationid,
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
        "registrationid":       row["registrationid"],
        "rescinddate":          row["rescinddate"].isoformat() if row["rescinddate"] else None,
    })


def _vacate_order_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="ev_hpd_vacateorders", cursor_factory=RealDictCursor) as cur:
        cur.itersize = 5000
        cur.execute(VACATE_ORDERS_SQL)
        batch: List[dict] = []
        for row in cur:
            batch.append({
                "event_id":          _event_id(row["vacateordernumber"]),
                "bbl":               row["bbl"],
                "source_record_id":  str(row["vacateordernumber"]),
                "registration_id":   str(row["registrationid"]) if row["registrationid"] is not None else None,
                "event_date":        row["vacateeffectivedate"].isoformat() if row["vacateeffectivedate"] else None,
                "status":            "Rescinded" if row["rescinddate"] else "Active",
                "rescind_date":      row["rescinddate"].isoformat() if row["rescinddate"] else None,
                "violation_class":   row["primaryvacatereason"],
                "vacate_type":       row["vacatetype"],
                "units_vacated":     row["numberofvacatedunits"],
                "raw_record":        _raw_record(row),
            })
            if len(batch) == EVENT_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_vacate_orders(session, conn) -> tuple:
    """
    MERGE Event(VacateOrder, HPD) + Observation nodes, both ORIGINATES_IN
    the Source. Building-first, skip-and-count (MATCH, not MERGE). Returns
    (events_written, skipped_missing_building).
    """
    event_cypher = """
    UNWIND $batch AS v
    MATCH (b:Building {bbl: v.bbl})
    MERGE (e:Event:WatchlineNode {event_id: v.event_id})
    SET e.event_type       = 'VacateOrder',
        e.source_name      = 'HPD',
        e.source_id        = $source_id,
        e.source_record_id = v.source_record_id,
        e.registration_id   = v.registration_id,
        e.event_date        = CASE WHEN v.event_date IS NOT NULL THEN date(v.event_date) ELSE null END,
        e.status             = v.status,
        e.rescind_date       = CASE WHEN v.rescind_date IS NOT NULL THEN date(v.rescind_date) ELSE null END,
        e.violation_class    = v.violation_class,
        e.vacate_type        = v.vacate_type,
        e.units_vacated      = v.units_vacated,
        e.legal_authority   = $legal_authority,
        e.raw_record        = v.raw_record,
        e.created_at        = CASE WHEN e.created_at IS NULL THEN datetime($now) ELSE e.created_at END
    MERGE (b)-[:HAS_EVENT]->(e)
    WITH e, v
    MATCH (s:Source {source_id: $source_id})
    MERGE (obs:Observation:WatchlineNode {
        observation_id: 'OBS-HPD-VACATE-' + v.source_record_id
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
    for batch in _vacate_order_batches(conn):
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
            source_id=HPD_VACATE_SOURCE["source_id"],
            legal_authority=LEGAL_AUTHORITY,
        )
        total += len(batch)
    return total, len(missing_bbls)


def step_source(driver):
    print("Step 1 -- Creating/updating HPD Vacate Orders Source node ...")
    with driver.session(database=NEO4J_DATABASE) as session:
        create_source_node(session)
    print("  Done.")


def step_vacate_orders(driver):
    print("Step 2 -- Writing Event(VacateOrder, HPD) + Observation nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, skipped = load_vacate_orders(session, conn)
        print(f"  {total:,} vacate order rows processed.")
        if skipped:
            print(f"  {skipped:,} distinct BBLs had no Building node (rows skipped).")
    finally:
        conn.close()


def run_all(driver):
    step_source(driver)
    step_vacate_orders(driver)
    print("")
    print("HPD vacate orders ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="Watchline evidentiary HPD vacate orders ingestion")
    parser.add_argument(
        "--step",
        choices=["source", "vacateorders"],
        help="Run a single step (omit to run all steps in order)",
    )
    args = parser.parse_args()

    driver = neo4j_driver()
    try:
        if args.step is None:
            run_all(driver)
        elif args.step == "source":
            step_source(driver)
        elif args.step == "vacateorders":
            step_vacate_orders(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
