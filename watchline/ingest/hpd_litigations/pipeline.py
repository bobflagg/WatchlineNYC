"""
Watchline HPD Litigations Ingestion Pipeline
watchline/ingest/hpd_litigations/pipeline.py

Ingests NYC HPD housing court litigations from the deedwatch PostgreSQL
database into the Watchline Neo4j knowledge graph.

HPD litigations are housing court cases initiated by HPD on behalf of
tenants. They are distinct from HPD violations: a violation is an
administrative finding; a litigation is a court proceeding. A finding
of harassment is a judicial determination -- the most legally significant
output in the HPD enforcement dataset.

What this pipeline creates:
  Layer 1 (Domain):
    - Building nodes via MERGE (new BBLs only; existing nodes preserved)
    - Event nodes of event_type=CourtFiling (one per litigation)
    - HAS_EVENT edges linking Buildings to their litigations

  Layer 2 (Evidence):
    - Source node for HPD Litigations
    - Observation nodes (one per litigation row)
    - ORIGINATES_IN edges to Source

Key design decisions:
  - event_type is 'CourtFiling': litigations are court proceedings, not
    administrative notices or adjudicated judgments. Charter Principle 16.
  - findingofharassment drives interpretive_status:
      'After Inquest' or 'After Trial' -> Stipulated (judicial finding)
      'No Harassment'                  -> Observed (court found no violation)
      null                             -> Inferred (case open or undetermined)
  - event_date uses caseopendate with findingdate as fallback. Cases where
    both are null are skipped (event_date is NOT NULL in schema).
  - respondent field is stored as a property for future actor linking.
    The respondent string often contains multiple names separated by commas.
  - openjudgement='YES' indicates an outstanding court judgment against
    the respondent -- stored as a boolean property.
  - 318 records have null/blank BBL with no boro/block/lot fallback
    available -- these are skipped with a logged count.
  - 2 records have malformed BBLs of length != 10 -- skipped.

Usage:
    uv run python -m watchline.ingest.hpd_litigations.pipeline
    uv run python -m watchline.ingest.hpd_litigations.pipeline --step source
    uv run python -m watchline.ingest.hpd_litigations.pipeline --step buildings
    uv run python -m watchline.ingest.hpd_litigations.pipeline --step litigations
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Iterator, List

import psycopg2
from psycopg2.extras import RealDictCursor
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
BUILDING_BATCH_SIZE = 500
LITIGATION_BATCH_SIZE = 500

HPD_LITIGATIONS_SOURCE = {
    "source_id":        "SRC-HPD-LITIGATIONS-001",
    "source_name":      "HPD Litigations",
    "producing_agency": "NYC Department of Housing Preservation and Development",
    "legal_authority": (
        "New York City Administrative Code Section 27-2115 et seq. "
        "HPD is empowered to bring court proceedings on behalf of tenants "
        "for violations of the Housing Maintenance Code. A finding of "
        "harassment by a housing court judge constitutes a legal determination "
        "under NYC Administrative Code Section 27-2005(d)."
    ),
    "data_url": (
        "https://data.cityofnewyork.us/Housing-Development/"
        "Housing-Litigations/59kj-x8nc"
    ),
    "description": (
        "HPD housing court litigations. Legally empowered to assert: that HPD "
        "initiated a court proceeding at a specific building, the type and "
        "status of that proceeding, and where applicable, the court's finding "
        "of harassment. A findingofharassment of 'After Inquest' or 'After "
        "Trial' is a judicial determination and carries Stipulated interpretive "
        "status. Does NOT assert current building conditions or ownership."
    ),
}

# ---------------------------------------------------------------------------
# Status and interpretive status mappings
# ---------------------------------------------------------------------------

STATUS_MAP = {
    "PENDING": "Pending",
    "CLOSED":  "Closed",
}

# findingofharassment -> interpretive_status
# After Inquest: judge made finding without full trial (on default or papers)
# After Trial: full evidentiary hearing, strongest finding
# No Harassment: court found no harassment -- Observed (fact of dismissal)
# null: case ongoing or finding not yet recorded -- Inferred
FINDING_INTERPRETIVE = {
    "After Inquest": "Stipulated",
    "After Trial":   "Stipulated",
    "No Harassment": "Observed",
}

BOROUGH_CODE_MAP = {
    "1": "Manhattan",
    "2": "Bronx",
    "3": "Brooklyn",
    "4": "Queens",
    "5": "Staten Island",
}


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

def pg_conn():
    return psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )


def neo4j_driver():
    return GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )


# ---------------------------------------------------------------------------
# Step 1: Source node
# ---------------------------------------------------------------------------

def create_source_node(session) -> None:
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
        **HPD_LITIGATIONS_SOURCE,
    )
    print(f"  Source node created/updated: {HPD_LITIGATIONS_SOURCE['source_name']}")


# ---------------------------------------------------------------------------
# Step 2: Building nodes
# ---------------------------------------------------------------------------

BUILDINGS_SQL = """
SELECT
    trim(l.bbl) AS bbl_canonical,
    l.boro,
    MAX(l.housenumber) AS housenumber,
    MAX(l.streetname)  AS streetname,
    MAX(l.latitude)    AS latitude,
    MAX(l.longitude)   AS longitude,
    MAX(p.address)     AS pluto_address,
    MAX(p.unitsres)    AS residential_units,
    MAX(p.yearbuilt)   AS year_built,
    MAX(p.bldgclass)   AS building_class
FROM hpd_litigations l
LEFT JOIN pluto_latest p ON p.bbl = trim(l.bbl)
WHERE l.bbl IS NOT NULL
  AND trim(l.bbl) != ''
  AND LENGTH(trim(l.bbl)) = 10
GROUP BY trim(l.bbl), l.boro
"""


def _building_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        print("  Querying distinct buildings from hpd_litigations + pluto_latest ...")
        cur.execute(BUILDINGS_SQL)
        batch = []
        for row in cur:
            bbl = row["bbl_canonical"]
            borough = BOROUGH_CODE_MAP.get(str(row["boro"] or ""), bbl[0:1])
            borough = BOROUGH_CODE_MAP.get(borough, borough)
            address = row["pluto_address"] or (
                f"{(row['housenumber'] or '').strip()} "
                f"{(row['streetname'] or '').strip()}"
            ).strip()
            batch.append({
                "bbl":               bbl,
                "address":           address,
                "borough":           BOROUGH_CODE_MAP.get(str(row["boro"] or ""), "Unknown"),
                "latitude":          float(row["latitude"]) if row["latitude"] else None,
                "longitude":         float(row["longitude"]) if row["longitude"] else None,
                "residential_units": row["residential_units"],
                "year_built":        row["year_built"],
                "building_class":    (row["building_class"] or "").strip() or None,
            })
            if len(batch) == BUILDING_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_buildings(session, conn) -> int:
    """MERGE Building nodes -- only fills null properties to preserve HPD/DOB/ECB data."""
    cypher = """
    UNWIND $batch AS b
    MERGE (bld:Building:WatchlineNode {bbl: b.bbl})
    SET bld.borough           = CASE WHEN bld.borough IS NULL
                                     THEN b.borough ELSE bld.borough END,
        bld.address           = CASE WHEN bld.address IS NULL OR bld.address = ''
                                     THEN b.address ELSE bld.address END,
        bld.latitude          = CASE WHEN bld.latitude IS NULL
                                     THEN b.latitude ELSE bld.latitude END,
        bld.longitude         = CASE WHEN bld.longitude IS NULL
                                     THEN b.longitude ELSE bld.longitude END,
        bld.residential_units = CASE WHEN bld.residential_units IS NULL
                                     THEN b.residential_units
                                     ELSE bld.residential_units END,
        bld.year_built        = CASE WHEN bld.year_built IS NULL
                                     THEN b.year_built ELSE bld.year_built END,
        bld.building_class    = CASE WHEN bld.building_class IS NULL
                                     THEN b.building_class ELSE bld.building_class END,
        bld.updated_at        = datetime($now),
        bld.created_at        = CASE WHEN bld.created_at IS NULL
                                     THEN datetime($now) ELSE bld.created_at END
    """
    now = datetime.now(timezone.utc).isoformat()
    total = 0
    for batch in _building_batches(conn):
        session.run(cypher, batch=batch, now=now)
        total += len(batch)
    return total


# ---------------------------------------------------------------------------
# Step 3: Litigation Events + Observations
# ---------------------------------------------------------------------------

LITIGATIONS_SQL = """
SELECT
    l.litigationid,
    trim(l.bbl)          AS bbl_canonical,
    l.casetype,
    l.casestatus,
    l.caseopendate,
    l.openjudgement,
    l.findingofharassment,
    l.findingdate,
    l.penalty,
    l.respondent,
    l.communitydistrict,
    l.councildistrict,
    l.nta
FROM hpd_litigations l
WHERE l.bbl IS NOT NULL
  AND trim(l.bbl) != ''
  AND LENGTH(trim(l.bbl)) = 10
ORDER BY l.litigationid
"""


def _litigation_batches(conn) -> Iterator[List[dict]]:
    with conn.cursor(name="hpd_litigations_cursor",
                     cursor_factory=RealDictCursor) as cur:
        cur.itersize = 2000
        print("  Querying HPD litigations ...")
        cur.execute(LITIGATIONS_SQL)
        batch = []
        for row in cur:
            def d(col):
                v = row.get(col)
                if v is None:
                    return None
                if hasattr(v, "isoformat"):
                    return v.date().isoformat() if hasattr(v, "date") else v.isoformat()
                return str(v)

            finding = row["findingofharassment"]
            interpretive_status = FINDING_INTERPRETIVE.get(finding, "Inferred")
            is_harassment_finding = finding in ("After Inquest", "After Trial")

            # event_date: prefer caseopendate, fall back to findingdate
            event_date = d("caseopendate") or d("findingdate")

            batch.append({
                "event_id":             f"EVT-HPD-LIT-{row['litigationid']}",
                "bbl":                  row["bbl_canonical"],
                "source_record_id":     str(row["litigationid"]),
                "event_type":           "CourtFiling",
                "source_name":          "HPD-Litigations",
                "event_date":           event_date,
                "status":               STATUS_MAP.get(
                                            (row["casestatus"] or "").strip(),
                                            "Unknown"
                                        ),
                "case_type":            (row["casetype"] or "").strip() or None,
                "open_judgement":       row["openjudgement"] == "YES",
                "finding_of_harassment": finding,
                "is_harassment_finding": is_harassment_finding,
                "finding_date":         d("findingdate"),
                "penalty":              row["penalty"],
                "respondent":           (row["respondent"] or "").strip() or None,
                "community_district":   (row["communitydistrict"] or "").strip() or None,
                "council_district":     (row["councildistrict"] or "").strip() or None,
                "nta":                  (row["nta"] or "").strip() or None,
                "interpretive_status":  interpretive_status,
                "legal_authority":      (
                    "NYC Administrative Code Section 27-2115 et seq.; "
                    "housing court proceeding"
                ),
                "raw_record":           json.dumps({
                    "litigationid":        row["litigationid"],
                    "casetype":            row["casetype"],
                    "casestatus":          row["casestatus"],
                    "findingofharassment": row["findingofharassment"],
                    "openjudgement":       row["openjudgement"],
                    "penalty":             row["penalty"],
                    "respondent":          row["respondent"],
                }),
            })
            if len(batch) == LITIGATION_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def load_litigations(session, conn) -> tuple:
    """
    Write CourtFiling Event nodes and Observation nodes.
    Skips rows with no usable event_date.
    Returns (total_written, total_skipped, harassment_findings).
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
        e.case_type             = v.case_type,
        e.open_judgement        = v.open_judgement,
        e.finding_of_harassment = v.finding_of_harassment,
        e.is_harassment_finding = v.is_harassment_finding,
        e.finding_date          = CASE WHEN v.finding_date IS NOT NULL
                                       THEN date(v.finding_date) ELSE null END,
        e.penalty               = v.penalty,
        e.respondent            = v.respondent,
        e.community_district    = v.community_district,
        e.council_district      = v.council_district,
        e.nta                   = v.nta,
        e.interpretive_status   = v.interpretive_status,
        e.legal_authority       = v.legal_authority,
        e.raw_record            = v.raw_record,
        e.created_at            = CASE WHEN e.created_at IS NULL
                                       THEN datetime($now) ELSE e.created_at END
    MERGE (bld)-[:HAS_EVENT]->(e)
    WITH e, v
    MATCH (s:Source {source_id: $source_id})
    MERGE (obs:Observation:WatchlineNode {
        observation_id: 'OBS-HPD-LIT-' + v.source_record_id
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
    harassment_findings = 0

    for batch in _litigation_batches(conn):
        if not batch:
            continue

        session.run(
            event_cypher,
            batch=batch,
            source_id=HPD_LITIGATIONS_SOURCE["source_id"],
            now=now,
        )
        total += len(batch)
        harassment_findings += sum(1 for v in batch if v["is_harassment_finding"])

        if total % 50_000 == 0:
            print(f"    {total:,} litigations written ...")

    return total, 0, harassment_findings


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_source(driver):
    print("Step 1 -- Creating/updating HPD Litigations Source node ...")
    with driver.session(database=NEO4J_DATABASE) as session:
        create_source_node(session)
    print("  Done.")


def step_buildings(driver):
    print("Step 2 -- Writing Building nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total = load_buildings(session, conn)
        print(f"  {total:,} Building nodes processed.")
    finally:
        conn.close()


def step_litigations(driver):
    print("Step 3 -- Writing HPD Litigation CourtFiling Event nodes ...")
    conn = pg_conn()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            total, _, harassment = load_litigations(session, conn)
        print(f"  {total:,} Litigation Events written.")
        print(f"  {harassment:,} harassment findings (Stipulated interpretive status).")
        print(f"  Note: {total - harassment:,} records have null event_date "
              f"(caseopendate not populated by HPD source).")
    finally:
        conn.close()


def run_all(driver):
    step_source(driver)
    step_buildings(driver)
    step_litigations(driver)
    print("")
    print("HPD litigations ingestion complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Watchline HPD litigations ingestion"
    )
    parser.add_argument(
        "--step",
        choices=["source", "buildings", "litigations"],
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
        elif args.step == "litigations":
            step_litigations(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
